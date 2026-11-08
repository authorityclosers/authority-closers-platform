"""The QA robot (scripts/qa-engine): every file parses and the self-test passes.

Also checks that nothing secret is in the folder. Node only: nothing here opens a
browser or talks to a server.
"""

import py_compile
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "scripts" / "qa-engine"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
SOURCES = sorted(path for path in ROOT.rglob("*.cjs"))


@needs_node
@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(ROOT)))
def test_node_file_parses(path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [NODE, "--check", str(path)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr


@needs_node
def test_selftest_passes() -> None:
    result = subprocess.run(  # noqa: S603
        [NODE, str(ROOT / "selftest.cjs")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "selftest ok" in result.stdout


def test_matrix_wrapper_compiles(tmp_path: Path) -> None:
    py_compile.compile(str(ROOT / "matrix.py"), cfile=str(tmp_path / "matrix.pyc"), doraise=True)


def test_folder_holds_no_secret() -> None:
    pattern = re.compile(
        r"(password|passwd|secret|api[_-]?key|bearer)\s*[:=]\s*[\"'][^\"']{6,}[\"']",
        re.IGNORECASE,
    )
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".cjs", ".py", ".json", ".md"}:
            assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_design_rules_in_page_scan_match_capture_stage() -> None:
    """The four design rules live in lib/design-rules.cjs and inside the page scan: same code."""
    design = (ROOT / "lib" / "design-rules.cjs").read_text(encoding="utf-8")
    scan = (ROOT / "lib" / "invariants.cjs").read_text(encoding="utf-8")
    source = design.split("const DESIGN_SCAN = ", 1)[1].split(";\n\nmodule.exports", 1)[0]
    assert f"out.design = phone ? ({source})() : null;" in scan


def test_design_findings_are_filed_only_for_the_rules_the_flag_file_names() -> None:
    scan = (ROOT / "lib" / "invariants.cjs").read_text(encoding="utf-8")
    assert "design-filing.on" in scan
    assert "new Set(" in scan.split("const designFiling", 1)[1].split("\n", 1)[0]
    for rule in ("edge-mask", "boxed", "dead-row", "label-heading"):
        assert f'filed.has("{rule}")' in scan


def test_capture_command_is_wired() -> None:
    engine = (ROOT / "engine.cjs").read_text(encoding="utf-8")
    assert 'cmd === "capture"' in engine
    assert "393 px" in (ROOT / "lib" / "config.cjs").read_text(encoding="utf-8")


def test_owner_views_use_the_fictional_admin_and_the_real_alias_stays_guarded() -> None:
    config = (ROOT / "lib" / "config.cjs").read_text(encoding="utf-8")
    assert 'OWNER_ALIAS: process.env.QA_OWNER_ALIAS || "anjali"' in config
    assert '"363 px"' in config
    session = (ROOT / "lib" / "session.cjs").read_text(encoding="utf-8")
    assert 'opts.alias === "owner"' in session
    assert "NO-OWNER" in session


def test_persona_proxy_serves_the_sellers_and_the_admin_and_has_no_owner_alias() -> None:
    proxy = (ROOT / "persona-proxy.cjs").read_text(encoding="utf-8")
    for name in ("priya", "rohan", "sneha", "farah", "karan", "neha", "imran", "pooja", "anjali"):
        assert f"  {name}: [" in proxy
    assert "  owner: [" not in proxy
    assert "SANDBOX_LOGIN_AC_ANJALI" in proxy


def test_units_and_helpers_keep_nothing_in_tmp_and_run_in_the_strikes_slice() -> None:
    for path in [
        ROOT / "persona-proxy.cjs",
        ROOT / "engine.cjs",
        *ROOT.glob("lib/*.cjs"),
        *ROOT.glob("bin/*.sh"),
        *ROOT.glob("systemd/*.service"),
    ]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<!/var)/tmp/", text), path
    for unit in ROOT.glob("systemd/*.service"):
        text = unit.read_text(encoding="utf-8")
        assert "Slice=ac-strikes.slice" in text
        assert "WantedBy=multi-user.target" in text
    mixed = (ROOT / "systemd" / "qa-engine-mixed.service").read_text(encoding="utf-8")
    for cap in ("CPUQuota=60%", "MemoryMax=3200M", "Nice=15", "IOSchedulingClass=idle"):
        assert cap in mixed


def test_workspace_guard_is_for_the_real_owner_alias_only() -> None:
    """The guard blanks a non-sandbox workspace; the fictional Admin only has a sandbox."""
    session = (ROOT / "lib" / "session.cjs").read_text(encoding="utf-8")
    assert 'if (tab.opts.alias === "owner") {' in session
    assert "isOwnerAlias(tab.opts.alias)" not in session


def test_tap_loop_skips_controls_behind_an_open_dialog() -> None:
    """The covered check and the tap-size loop both leave out what an open sheet covers."""
    scan = (ROOT / "lib" / "invariants.cjs").read_text(encoding="utf-8")
    assert scan.count('!el.closest("[role=dialog],[aria-modal=true],dialog")) continue;') >= 2
    assert scan.count("under an open :modal dialog") >= 2


def test_empty_state_words_are_looked_for_one_block_of_text_at_a_time() -> None:
    """A tile label and the heading beside it must not read as one "no calls" phrase."""
    attack = (ROOT / "lib" / "attack.cjs").read_text(encoding="utf-8")
    assert "EMPTY.test(" not in attack
    assert attack.count("emptyHit(") >= 8
    assert "split(/\\n+/)" in attack
    source = re.search(r"^const EMPTY = /(.*)/i;$", attack, re.MULTILINE)
    assert source
    empty = re.compile(source.group(1), re.IGNORECASE)
    blocks = ["No owner", "Calls today", "No calls yet"]
    assert empty.search(" ".join(blocks[:2]))  # the old reading: two blocks run together
    assert not any(empty.search(block) for block in blocks[:2])
    assert empty.search(blocks[2])


def test_focus_look_takes_in_the_box_a_stretched_link_draws_its_ring_on() -> None:
    """A link's ring on its ::after covers the whole row, outside the link's own box plus 8 px."""
    attack = (ROOT / "lib" / "attack.cjs").read_text(encoding="utf-8")
    assert "const reach = (el, b) => {" in attack
    assert "rect: reach(el, r)," in attack
    assert "const prevRect = pr ? reach(prev, pr) : null;" in attack
    assert 'for (const pe of ["::after", "::before"])' in attack


def test_empty_list_scan_leaves_out_a_sliver_nobody_can_look_at() -> None:
    """An empty 8 px avatars list while the Team floor loads is not an empty state a person sees."""
    scan = (ROOT / "lib" / "invariants.cjs").read_text(encoding="utf-8")
    assert "if (box.width < 24 || box.height < 24) continue;" in scan
    assert scan.index("box.width < 24") < scan.index("out.emptyLists.push(")
