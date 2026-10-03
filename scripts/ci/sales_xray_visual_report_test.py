"""Regression coverage for provenance, hostile archives and unavailable diffs."""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image
from sales_xray_visual_report import choose_baseline, pixel_diff, report, unpack_baseline

SHA = "a" * 40
NAME = "shell-390x844.png"


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as stream:
        for name, data in entries.items():
            stream.writestr(name, data)
    return buffer.getvalue()


def image_bytes(size=(390, 844)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


class VisualReportTests(unittest.TestCase):
    def test_baseline_requires_green_main_same_sha_and_excludes_current(self):
        good = {
            "id": 1,
            "head_branch": "main",
            "event": "push",
            "conclusion": "success",
            "head_sha": SHA,
            "created_at": "2026-10-03T12:00:00Z",
        }
        newer = {**good, "id": 2, "head_sha": "b" * 40, "created_at": "2026-10-03T13:00:00Z"}
        pr = {**newer, "event": "pull_request", "head_sha": SHA}
        self.assertEqual(choose_baseline([good, newer, pr], {SHA}, "3"), good)
        self.assertIsNone(choose_baseline([good], {SHA}, "1"))
        self.assertIsNone(choose_baseline([good], set(), "3"))

    def test_archive_source_paths_dimensions_and_non_image_files(self):
        receipt = {
            "schema": "ac-sales-xray-visual/1",
            "source_sha": SHA,
            "rows": [{"screenshot": NAME, "capture_status": "measured"}],
        }
        entries = {
            "receipt.json": json.dumps(receipt),
            NAME: image_bytes(),
            "untrusted.js": "never execute or copy",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertEqual(unpack_baseline(archive(entries), output, SHA), {NAME})
            self.assertFalse((output / "untrusted.js").exists())
            for hostile in [
                {**entries, "../escaped.png": image_bytes()},
                {**entries, NAME: image_bytes((1, 1))},
                {**entries, "receipt.json": json.dumps({**receipt, "source_sha": "b" * 40})},
            ]:
                with self.assertRaises(ValueError):
                    unpack_baseline(archive(hostile), output, SHA)

    def test_diff_counts_changed_pixel_and_retains_unavailable(self):
        current = Image.new("RGB", (3, 2), "white")
        baseline = current.copy()
        baseline.putpixel((1, 1), (0, 0, 0))
        with tempfile.TemporaryDirectory() as directory:
            result = pixel_diff(current, baseline, Path(directory) / "diff.png")
            self.assertEqual(result["changed_pixels"], 1)
            self.assertAlmostEqual(result["ratio"], 1 / 6)
            mismatch = pixel_diff(
                current, Image.new("RGB", (1, 1)), Path(directory) / "missing.png"
            )
            self.assertEqual(mismatch["status"], "unavailable")
            self.assertIsNone(mismatch["ratio"])

    def test_report_does_not_fabricate_missing_baseline_or_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, baseline = root / "output", root / "baseline"
            output.mkdir()
            baseline.mkdir()
            Image.new("RGB", (390, 844), "white").save(output / NAME)
            row = {
                "id": "shell-390x844",
                "screenshot": NAME,
                "capture_status": "measured",
                "overflow_px": None,
                "overflow_count": None,
                "console_error_count": None,
                "uncaught_exception_count": None,
                "axe_critical_count": None,
                "axe_incomplete_count": None,
            }
            (output / "receipt.json").write_text(json.dumps({"source_sha": SHA, "rows": [row]}))
            (baseline / "baseline.json").write_text(
                json.dumps(
                    {"status": "unavailable", "run_id": None, "source_sha": None, "screenshots": []}
                )
            )
            result = report(output, baseline)
            self.assertIsNone(result["rows"][0]["diff"]["ratio"])
            self.assertIsNone(result["rows"][0]["axe_critical_count"])
            self.assertTrue((output / "contact-sheet.png").is_file())
            self.assertIn("unavailable", (output / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
