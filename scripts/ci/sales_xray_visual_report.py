"""Read-only CI baseline retrieval and bounded, count-only visual evidence.

Baseline archives are untrusted data: only validated, fixed-viewport PNGs are
decoded; no downloaded script, HTML, trace or receipt is executed/published.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

SCHEMA = "ac-sales-xray-visual/1"
ARTIFACT = "sales-xray-visual-"
SHA = re.compile(r"[0-9a-f]{40}\Z")
PNG = re.compile(r"[a-z0-9-]+-(?:1440x900|390x844)\.png\Z")
MAX_ARCHIVE = 50_000_000
MAX_EXPANDED = 80_000_000


def gh_api(path: str, *, binary: bool = False) -> object:
    executable = shutil.which("gh")
    if executable is None:
        raise OSError("gh unavailable")
    result = subprocess.run(  # noqa: S603 - fixed gh argv; no shell
        [executable, "api", path],
        capture_output=True,
        check=True,
        timeout=12,
    )
    if len(result.stdout) > MAX_ARCHIVE:
        raise ValueError("oversized response")
    return result.stdout if binary else json.loads(result.stdout)


def choose_baseline(visual_runs: list[dict], green_shas: set[str], current_id: str) -> dict | None:
    candidates = [
        run
        for run in visual_runs
        if run.get("head_branch") == "main"
        and run.get("event") == "push"
        and run.get("conclusion") == "success"
        and str(run.get("id")) != current_id
        and run.get("head_sha") in green_shas
        and SHA.fullmatch(run.get("head_sha", ""))
    ]
    return max(candidates, key=lambda run: run["created_at"], default=None)


def load_png(data: bytes, name: str) -> Image.Image:
    if not PNG.fullmatch(name) or len(data) > 8_000_000:
        raise ValueError("invalid screenshot")
    with Image.open(io.BytesIO(data)) as image:
        expected = (1440, 900) if name.endswith("1440x900.png") else (390, 844)
        if image.format != "PNG" or image.size != expected:
            raise ValueError("invalid screenshot dimensions")
        return image.convert("RGB")


def unpack_baseline(data: bytes, output: Path, source_sha: str) -> set[str]:
    if len(data) > MAX_ARCHIVE:
        raise ValueError("oversized archive")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 100 or sum(item.file_size for item in infos) > MAX_EXPANDED:
            raise ValueError("oversized archive")
        # Reject path traversal, duplicate names and symlinks, even for ignored files.
        names = [item.filename for item in infos]
        if len(set(names)) != len(names) or any(
            "/" in name or "\\" in name or name in {".", ".."} for name in names
        ):
            raise ValueError("invalid archive paths")
        if any((item.external_attr >> 16) & 0o170000 == 0o120000 for item in infos):
            raise ValueError("archive symlink")
        receipt_info = archive.getinfo("receipt.json")
        if receipt_info.file_size > 200_000:
            raise ValueError("oversized receipt")
        receipt = json.loads(archive.read(receipt_info))
        if receipt.get("schema") != SCHEMA or receipt.get("source_sha") != source_sha:
            raise ValueError("baseline source mismatch")
        valid = set()
        for row in receipt.get("rows", []):
            name = row.get("screenshot")
            if row.get("capture_status") != "measured" or not isinstance(name, str):
                continue
            if not PNG.fullmatch(name):
                raise ValueError("invalid screenshot name")
            image = load_png(archive.read(name), name)
            output.mkdir(parents=True, exist_ok=True)
            image.save(output / name)
            valid.add(name)
        return valid


def fetch_baseline(output: Path) -> dict:
    baseline = {"status": "unavailable", "run_id": None, "source_sha": None, "screenshots": []}
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        return baseline
    try:
        root = f"repos/{repository}/actions"
        # Bounded scan. Missing/expired/no-authority baselines stay unavailable.
        visual = gh_api(
            f"{root}/workflows/sales-xray-visual.yml/runs?branch=main&event=push&status=success&per_page=30"
        )
        application = gh_api(
            f"{root}/workflows/application.yml/runs?branch=main&event=push&status=success&per_page=30"
        )
        green = {
            run["head_sha"]
            for run in application["workflow_runs"]
            if run.get("conclusion") == "success"
        }
        run = choose_baseline(visual["workflow_runs"], green, os.environ.get("GITHUB_RUN_ID", ""))
        if run is None:
            return baseline
        baseline.update(run_id=str(run["id"]), source_sha=run["head_sha"])
        artifacts = gh_api(f"{root}/runs/{run['id']}/artifacts?per_page=100")
        artifact = next(
            (
                item
                for item in artifacts["artifacts"]
                if item["name"].startswith(ARTIFACT) and not item["expired"]
            ),
            None,
        )
        if artifact is None or artifact["size_in_bytes"] > MAX_ARCHIVE:
            return baseline
        data = gh_api(f"{root}/artifacts/{int(artifact['id'])}/zip", binary=True)
        names = unpack_baseline(data, output, run["head_sha"])
        baseline.update(status="available" if names else "unavailable", screenshots=sorted(names))
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
    ):
        pass  # Never publish provider errors, signed URLs, tokens or raw receipts.
    return baseline


def pixel_diff(current: Image.Image, baseline: Image.Image, output: Path) -> dict:
    if current.size != baseline.size:
        return {"status": "unavailable", "changed_pixels": None, "ratio": None, "image": None}
    difference = ImageChops.difference(current, baseline)
    # Pixel differs when any RGB channel differs by >20; fixed, advisory only.
    channels = [
        channel.point(lambda value: 255 if value > 20 else 0) for channel in difference.split()
    ]
    mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    changed = mask.histogram()[255]
    overlay = current.copy()
    overlay.paste((255, 0, 100), mask=mask)
    overlay.save(output)
    return {
        "status": "available",
        "changed_pixels": changed,
        "ratio": changed / (current.width * current.height),
        "image": output.name,
    }


def report(output: Path, baseline_dir: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "receipt.json").is_file():
        receipt = json.loads((output / "receipt.json").read_text())
    else:
        # Setup failures have no browser observations. Keep that gap explicit.
        receipt = {
            "schema": SCHEMA,
            "advisory": True,
            "source_sha": os.environ.get("VISUAL_SOURCE_SHA"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "renderer_status": "unavailable",
            "rows": [],
            "coverage_status": "unavailable",
            "elapsed_seconds": None,
        }
    baseline = {"status": "unavailable", "run_id": None, "source_sha": None, "screenshots": []}
    if (baseline_dir / "baseline.json").is_file():
        baseline = json.loads((baseline_dir / "baseline.json").read_text())
    receipt["baseline"] = baseline
    sheet = Image.new("RGB", (1020, max(1, (len(receipt["rows"]) + 1) // 2) * 360), "#eef0f4")
    draw = ImageDraw.Draw(sheet)
    lines = [
        "## Sales Xray visual check — advisory",
        "",
        f"Source: `{receipt['source_sha']}`",
        f"Baseline: {baseline['status']} (run {baseline['run_id']}, SHA {baseline['source_sha']})",
        "",
        "Missing measurements are `unavailable`. All counts and pixel diffs are report-only.",
        "",
        "| State / viewport | Capture | Overflow px / count | Console / uncaught | "
        "Axe critical / incomplete | Pixel difference |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    def value(item):
        return "unavailable" if item is None else str(item)

    for index, row in enumerate(receipt["rows"]):
        name = row["screenshot"]
        row["diff"] = {
            "status": "unavailable",
            "changed_pixels": None,
            "ratio": None,
            "image": None,
        }
        x, y = (index % 2) * 510 + 10, (index // 2) * 360 + 10
        draw.text((x, y), row["id"], fill="black")
        if name:
            current = load_png((output / name).read_bytes(), name)
            thumbnail = current.copy()
            thumbnail.thumbnail((490, 310))
            sheet.paste(thumbnail, (x, y + 25))
            if baseline["status"] == "available" and name in baseline["screenshots"]:
                previous = load_png((baseline_dir / name).read_bytes(), name)
                row["diff"] = pixel_diff(current, previous, output / f"diff-{name}")
        diff = row["diff"]
        ratio = f"{diff['ratio']:.2%}" if diff["ratio"] is not None else "unavailable"
        capture_link = f"[{row['capture_status']}]({name})" if name else row["capture_status"]
        diff_link = f"[{ratio}]({diff['image']})" if diff["image"] else ratio
        lines.append(
            f"| {row['id']} | {capture_link} | "
            f"{value(row['overflow_px'])} / {value(row['overflow_count'])} | "
            f"{value(row['console_error_count'])} / {value(row['uncaught_exception_count'])} | "
            f"{value(row['axe_critical_count'])} / {value(row['axe_incomplete_count'])} | "
            f"{diff_link} |"
        )
    sheet.save(output / "contact-sheet.png")
    receipt["contact_sheet"] = "contact-sheet.png"
    receipt["artifact_url"] = os.environ.get("VISUAL_ARTIFACT_URL") or None
    lines.extend(["", "[Contact sheet](contact-sheet.png)"])
    # Relative screenshot and diff links resolve within the downloaded artifact.
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (output / "report.md").write_text("\n".join(lines) + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as stream:
            stream.write("\n".join(lines) + "\n")
    return receipt


def selection(output: Path) -> None:
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()  # noqa: S603,S607
    base = os.environ.get("VISUAL_BASE_SHA", "")
    all_frames = os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
    paths = []
    if not all_frames:
        if not SHA.fullmatch(base):
            raise ValueError("invalid base SHA")
        paths = subprocess.check_output(  # noqa: S603 - validated SHA, no shell
            ["git", "diff", "--name-only", "-z", f"{base}...HEAD"],  # noqa: S607
            text=True,
        ).split("\0")
    output.write_text(
        json.dumps(
            {
                "source_sha": source,
                "run_id": os.environ.get("GITHUB_RUN_ID"),
                "all": all_frames,
                "paths": paths,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["selection", "baseline", "report"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path)
    args = parser.parse_args()
    if args.command == "selection":
        selection(args.output)
    elif args.command == "baseline":
        args.output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        result = fetch_baseline(args.output)
        result["fetch_seconds"] = round(time.monotonic() - started, 2)
        (args.output / "baseline.json").write_text(json.dumps(result, indent=2) + "\n")
    else:
        report(args.output, args.baseline_dir)


if __name__ == "__main__":
    main()
