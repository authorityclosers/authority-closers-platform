#!/usr/bin/env python3
"""Network-free protocol checks, illustrative cost arithmetic and call-level statistics.
This is NOT a provider runner and does not generate/evaluate Sales Xray reports.
Python 3.10+, standard library only. Unknown values are not converted to zero.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, random, statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def check(path: Path) -> None:
    spec = json.loads(path.read_text(encoding='utf-8'))
    auth = spec['authorization']
    assert auth['provider_calls_allowed'] is False, 'Provider execution must remain disabled.'
    assert auth['external_spend_authorized'] is False
    assert Decimal(auth['max_external_spend_usd']) == 0
    assert auth['deployment_allowed'] is False
    ids = [r['id'] for r in spec['requirements']]
    assert len(ids) == len(set(ids))
    assert {f'SXQ-{n:02d}' for n in range(1,11)} <= set(ids)
    rows = list(csv.DictReader((path.parent/spec['corpus']['manifest_file']).open(encoding='utf-8')))
    families = [r['family_id'] for r in rows]
    assert len(families) == len(set(families)), 'A family must not cross splits.'
    totals = {}
    for split, expected_n, expected_min in [('screen',18,360),('holdout',36,1140)]:
        selected = [r for r in rows if r['split'] == split]
        minutes = sum(Decimal(r['planned_minutes']) for r in selected)
        assert len(selected) == expected_n and minutes == expected_min
        totals[split] = {'planned_families':len(selected),'planned_minutes':str(minutes)}
    assert not any(r['audio_sha256'] for r in rows), 'Template should not invent recordings.'
    raw = path.read_bytes()
    emit({'artifact_sha256':hashlib.sha256(raw).hexdigest(), 'protocol_checks':'passed',
          'benchmark_runs':0, 'provider_calls':0, 'authorized_external_usd':'0',
          'corpus':totals, 'paid_execution':'blocked',
          'meaning':'Artifact consistency only; no product quality or cost was measured.'})


def example_cost() -> None:
    # Explicit fictional usage, NOT a measured report or approved budget.
    minute = Decimal(60)
    asr = Decimal('0.22')
    llm = Decimal(60000)*Decimal('0.75')/Decimal(10**6) + Decimal(10000)*Decimal('3.75')/Decimal(10**6)
    total = asr+llm
    emit({'status':'illustrative_assumptions_not_actual_usage',
          'audio_minutes':60,'processed_channels':1,
          'all_C4_C5_uncached_input_tokens':60000,
          'all_visible_output_plus_reasoning_tokens':10000,
          'ASR_usd':str(asr),'LLM_usd':str(llm),
          'provider_subtotal_usd':str(total),'provider_subtotal_per_unique_minute_usd':str(total/minute),
          '2027_same_usage_provider_subtotal_usd':str(asr+llm*2),
          'two_processed_channels_same_LLM_usage_usd':str(asr*2+llm),
          'infrastructure_tax_fx_retries_actual':None,
          'complete_actual_cost_usd':None,
          'zero_severe_errors_36_calls_one_sided95_upper':1-0.05**(1/36),
          'zero_error_calls_for_upper_below_1_percent':math.ceil(math.log(.05)/math.log(.99))})


def percentile(xs: list[float], p: float) -> float:
    xs=sorted(xs); at=(len(xs)-1)*p; lo=math.floor(at); hi=math.ceil(at)
    return xs[lo]+(xs[hi]-xs[lo])*(at-lo)


def intervals(groups: dict[str,list[float]], draws: int, seed: int) -> dict[str,Any]:
    vals=[v for vs in groups.values() for v in vs]
    if not vals:
        return {'n':0,'estimate':None,'ci95':None,'status':'no_evaluable_calls'}
    n=len(vals); mean=statistics.mean(vals); rng=random.Random(seed)
    boots=[]
    for _ in range(draws):
        boots.append(sum(sum(rng.choices(vs,k=len(vs))) for vs in groups.values())/n)
    low=percentile(boots,.025); high=percentile(boots,.975)
    lower90=percentile(boots,.10)
    degenerate=(low==high) or (len(set(vals))==1)
    if degenerate:
        half=math.sqrt(2*math.log(2/.05)/n)
        lo_h=max(-1.,mean-half); hi_h=min(1.,mean+half)
        low=min(low,lo_h); high=max(high,hi_h)
        lower90=min(lower90,max(-1.,mean-math.sqrt(2*math.log(1/.10)/n)))
    return {'n':n,'estimate':mean,'ci95':[low,high],'one_sided90_lower':lower90,
            'method':'paired stratified call bootstrap; conservative Hoeffding widening when degenerate',
            'degeneracy_widening_used':degenerate,'minimum_cell_n':min(map(len,groups.values()))}


def summarize(path: Path, arm: str, track: str, split: str, seed: int, draws: int) -> None:
    rows=list(csv.DictReader(path.open(encoding='utf-8',newline='')))
    selected=[r for r in rows if r['arm_id']==arm and r['track']==track and r['split']==split and r['primary_render'].lower()=='true']
    family_ids=[r['family_id'] for r in selected]
    if len(family_ids)!=len(set(family_ids)):
        raise ValueError('Duplicate primary family. Do not treat languages, repeats or sections as independent calls.')
    values={'candidate':1.,'baseline':-1.,'tie':0.}
    groups=defaultdict(list); strata=defaultdict(list); counts={k:0 for k in ['candidate','baseline','tie','abstain']}
    invalid=0
    for r in selected:
        outcome=r['consensus_pair_decision']
        if outcome not in counts:
            raise ValueError('Use unblinded candidate/baseline/tie/abstain; do not feed raw A/B without assignment map.')
        counts[outcome]+=1
        if outcome=='abstain': continue
        value=values[outcome]
        cell=r['source_language']+'|'+r['duration_band']
        groups[cell].append(value)
        strata['language:'+r['source_language']].append(value)
        strata['duration:'+r['duration_band']].append(value)
        invalid += int(r['runtime_accepted'].lower()!='true')
    out=intervals(groups,draws,seed)
    n=len(selected); net=counts['candidate']-counts['baseline']; a=counts['abstain']
    out.update({'arm_id':arm,'track':track,'split':split,'counts':counts,'scheduled_families':n,
                'abstention_sensitivity':[(net-a)/n,(net+a)/n] if n else None,
                'subgroups':{k:intervals({k:vs},draws,seed) for k,vs in strata.items()},
                'promotion_decision':'not computed: requires all factual, coverage, language, reliability, cost and authorization gates',
                'cost_warning':'Join append-only attempt and receipt records; blank/unknown costs cannot become zero.',
                'interpretation':'Describes this benchmark sample only. No population or production claim.'})
    emit(out)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('check'); c.add_argument('spec',type=Path)
    sub.add_parser('example-cost')
    s=sub.add_parser('summarize');s.add_argument('results',type=Path);s.add_argument('--arm-id',required=True)
    s.add_argument('--track',choices=['prompt_only','audio_to_report'],required=True)
    s.add_argument('--split',choices=['screen','holdout'],default='holdout')
    s.add_argument('--seed',type=int,default=20260923);s.add_argument('--draws',type=int,default=10000)
    a=parser.parse_args()
    try:
        if a.cmd=='check':check(a.spec)
        elif a.cmd=='example-cost':example_cost()
        else:
            if not 1000<=a.draws<=100000:raise ValueError('draws must be between 1000 and 100000')
            summarize(a.results,a.arm_id,a.track,a.split,a.seed,a.draws)
    except (AssertionError,ValueError,KeyError,OSError,json.JSONDecodeError) as exc:
        parser.exit(2,'ERROR: '+str(exc)+'\n')
if __name__=='__main__':main()
