"""Synthetic offline tests only. No audio, model calls, or real review outcomes."""
import contextlib
import csv
import importlib.util
import io
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('benchmark_offline', ROOT / 'sx_benchmark_offline.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('sx_benchmark_experiment.json', 'sx_benchmark_corpus.csv', 'sx_benchmark_results_template.csv'):
            shutil.copyfile(ROOT / name, self.root / name)
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.temp.cleanup()

    def capture(self, fn, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(*args)
        return json.loads(out.getvalue())

    def change(self, fn):
        p = self.root / 'sx_benchmark_experiment.json'
        value = json.loads(p.read_text())
        fn(value)
        p.write_text(json.dumps(value))
        return p

    def corpus_rows(self):
        p = self.root / 'sx_benchmark_corpus.csv'
        with p.open(newline='') as f:
            reader = csv.DictReader(f)
            return p, reader.fieldnames, list(reader)

    def write_rows(self, p, fields, rows):
        with p.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def results(self, decisions, families=None, primary=None):
        p = self.root / 'sx_benchmark_results_template.csv'
        with p.open(newline='') as f:
            fields = next(csv.reader(f))
        rows = []
        for i, decision in enumerate(decisions):
            row = {name: '' for name in fields}
            row.update(arm_id='synthetic_arm', track='audio_to_report', split='holdout',
                       family_id=families[i] if families else f'fictional-family-{i}',
                       source_language='en', duration_band='short',
                       primary_render=primary[i] if primary else 'true',
                       consensus_pair_decision=decision, runtime_accepted='true')
            rows.append(row)
        self.write_rows(p, fields, rows)
        return p

    def summary(self, p):
        return self.capture(mod.summarize, p, 'synthetic_arm', 'audio_to_report', 'holdout', 20260923, 1000)

    def test_valid_protocol_zero_runs(self):
        result = self.capture(mod.check, self.root / 'sx_benchmark_experiment.json')
        self.assertEqual(result['benchmark_runs'], 0)
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(result['corpus']['holdout']['planned_families'], 36)

    def test_provider_execution_rejected(self):
        p = self.change(lambda x: x['authorization'].update(provider_calls_allowed=True))
        with self.assertRaises(AssertionError): mod.check(p)

    def test_spend_authorization_rejected(self):
        p = self.change(lambda x: x['authorization'].update(external_spend_authorized=True))
        with self.assertRaises(AssertionError): mod.check(p)

    def test_positive_cap_rejected(self):
        p = self.change(lambda x: x['authorization'].update(max_external_spend_usd='1'))
        with self.assertRaises(AssertionError): mod.check(p)

    def test_deployment_rejected(self):
        p = self.change(lambda x: x['authorization'].update(deployment_allowed=True))
        with self.assertRaises(AssertionError): mod.check(p)

    def test_duplicate_rule_rejected(self):
        p = self.change(lambda x: x['requirements'].append(x['requirements'][0]))
        with self.assertRaises(AssertionError): mod.check(p)

    def test_duplicate_family_rejected(self):
        p, fields, rows = self.corpus_rows()
        rows[1]['family_id'] = rows[0]['family_id']
        self.write_rows(p, fields, rows)
        with self.assertRaises(AssertionError): mod.check(self.root / 'sx_benchmark_experiment.json')

    def test_fabricated_audio_hash_rejected(self):
        p, fields, rows = self.corpus_rows()
        rows[0]['audio_sha256'] = '0' * 64
        self.write_rows(p, fields, rows)
        with self.assertRaises(AssertionError): mod.check(self.root / 'sx_benchmark_experiment.json')

    def test_wrong_corpus_duration_rejected(self):
        p, fields, rows = self.corpus_rows()
        rows[0]['planned_minutes'] = '4'
        self.write_rows(p, fields, rows)
        with self.assertRaises(AssertionError): mod.check(self.root / 'sx_benchmark_experiment.json')

    def test_empty_results_no_observations(self):
        result = self.summary(self.root / 'sx_benchmark_results_template.csv')
        self.assertEqual(result['n'], 0)
        self.assertIsNone(result['estimate'])
        self.assertIsNone(result['ci95'])
        self.assertTrue(result['promotion_decision'].startswith('not computed'))

    def test_synthetic_preferences_and_tie(self):
        result = self.summary(self.results(['candidate', 'baseline', 'tie']))
        self.assertEqual(result['n'], 3)
        self.assertEqual(result['estimate'], 0)
        self.assertEqual(result['counts']['tie'], 1)

    def test_abstention_sensitivity(self):
        result = self.summary(self.results(['candidate', 'abstain']))
        self.assertEqual(result['n'], 1)
        self.assertEqual(result['abstention_sensitivity'], [0, 1])

    def test_duplicate_primary_results_rejected(self):
        p = self.results(['candidate', 'candidate'], families=['same', 'same'])
        with self.assertRaises(ValueError): self.summary(p)

    def test_secondary_render_not_independent(self):
        p = self.results(['candidate', 'baseline'], families=['same', 'same'], primary=['true', 'false'])
        self.assertEqual(self.summary(p)['n'], 1)

    def test_blind_labels_require_unblinding(self):
        with self.assertRaises(ValueError): self.summary(self.results(['A']))

    def test_degenerate_interval_is_widened(self):
        result = mod.intervals({'synthetic': [0.0, 0.0, 0.0]}, 1000, 20260923)
        self.assertTrue(result['degeneracy_widening_used'])
        self.assertLess(result['ci95'][0], result['ci95'][1])

    def test_example_cost_is_not_actual(self):
        result = self.capture(mod.example_cost)
        self.assertEqual(result['status'], 'illustrative_assumptions_not_actual_usage')
        self.assertIsNone(result['complete_actual_cost_usd'])
        self.assertEqual(float(result['provider_subtotal_usd']), 0.3025)

    def test_private_sources_are_citations_only(self):
        value = json.loads((ROOT / 'sx_benchmark_experiment.json').read_text())
        for source in value['source_registry']:
            self.assertEqual(set(source), {'id', 'url', 'access'})
        self.assertFalse(value['facts']['benchmark_outputs_present'])
        for rate in value['ratecards']:
            self.assertEqual(rate['publication_verification'], 'provisional_reverify_primary_source_and_account')

    def test_json_schema_and_synthetic_unknown_attempt(self):
        from jsonschema import Draft202012Validator, ValidationError
        schema = json.loads((ROOT / 'sx_benchmark_records.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        row = dict(record_type='attempt', experiment_id='synthetic', arm_id='synthetic',
                   logical_report_id='synthetic', attempt_id='synthetic', stage='C5',
                   billing_state='unknown', request_sha256=None, model_requested=None,
                   settings_sha256=None, ratecard_revision=None, uncertain_charge=True)
        validator.validate(row)
        row['billing_state'] = 'made_up'
        with self.assertRaises(ValidationError): validator.validate(row)

    def test_result_template_is_empty(self):
        with (ROOT / 'sx_benchmark_results_template.csv').open(newline='') as f:
            self.assertEqual(list(csv.DictReader(f)), [])


if __name__ == '__main__':
    unittest.main()
