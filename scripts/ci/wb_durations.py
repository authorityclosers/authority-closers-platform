"""scripts/ci/wb_durations.py: build scripts/ci/wb-python-durations.json (wb-ci's own shard balance) from a Workbench checks run's JUnit reports.

usage: python3 scripts/ci/wb_durations.py <run-id> <source-sha> <output>   (run on ac as acdev; read-only for the workbench)
Measured: per-file sum of testcase times on GitHub runners. Unmeasured files: the main CI durations file, else the
shard script's group weight. Same schema as scripts/ci/python-test-durations.json, so python_test_shard.py reads it.
"""
import datetime, json, subprocess, sys, tempfile, xml.etree.ElementTree as ET
from pathlib import Path

WB = Path("/home/acdev/src/dev-live/authority-closers-platform")
sys.path.insert(0, str(WB / "scripts/ci"))
import python_test_shard as shard  # noqa: E402

run_id, source_sha, output = sys.argv[1:4]
discovered = set(shard.discover_test_files(WB))
by_module = {p[:-3].replace("/", "."): p for p in discovered}
seconds: dict[str, float] = {}
tmp = Path(tempfile.mkdtemp())
names = subprocess.run(["gh", "api", f"repos/authorityclosers/authority-closers-platform/actions/runs/{run_id}/artifacts",
                        "--jq", ".artifacts[].name"], capture_output=True, text=True, check=True).stdout.split()
for name in [n for n in names if n.startswith("python-test-shard-") or n.startswith("wb-python-")]:
    subprocess.run(["gh", "run", "download", run_id, "-R", "authorityclosers/authority-closers-platform", "-n", name,
                    "-D", str(tmp / name)], check=True, capture_output=True)
    for testcase in ET.parse(tmp / name / "junit.xml").getroot().iter("testcase"):
        parts = (testcase.get("classname") or "").split(".")
        path = next((by_module[".".join(parts[:k])] for k in range(len(parts), 0, -1) if ".".join(parts[:k]) in by_module), None)
        if path:
            seconds[path] = seconds.get(path, 0.0) + float(testcase.get("time") or 0)
old = json.loads((WB / "scripts/ci/python-test-durations.json").read_text())["seconds_by_file"]
try:  # the previous wb-ci measurement beats the main CI file for files this run did not time
    old = {**old, **json.loads((WB / "scripts/ci/wb-python-durations.json").read_text())["seconds_by_file"]}
except (OSError, ValueError, KeyError):
    pass
measured = len(seconds)
costs = {}
for path in sorted(discovered):
    value = seconds.get(path) or old.get(path) or float(shard.test_weight(path))
    costs[path] = round(max(value, 0.05), 3)
doc = {"schema": "ac.ci.python-durations/1",
       "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
       "source": {"sha": source_sha, "run_id": run_id, "measured_files": measured, "assigned_files": len(costs),
                  "note": "wb-ci shard balance from GitHub-hosted runners; refresh with: wb-ci --refresh-durations <run-id>"},
       "seconds_by_file": costs}
Path(output).write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
total = sum(costs.values())
print(f"{len(costs)} files, {measured} measured, total {total/60:.1f} min, max {max(costs.values()):.0f}s; 12 shards ~{total/12:.0f}s each")

