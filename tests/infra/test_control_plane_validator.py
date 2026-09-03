from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_shell_validation_is_limited_to_tracked_repository_files() -> None:
    validator = (REPO_ROOT / "scripts" / "validate-control-plane.sh").read_text(encoding="utf-8")

    assert "git ls-files -z" in validator
    assert "find . -path './.git'" not in validator
