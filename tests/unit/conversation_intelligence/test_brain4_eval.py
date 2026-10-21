"""Brain 4.0 and the pointer review against the gold set (AC-SVAL evidence)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ac_platform.conversation_intelligence import brain4, brain4_eval
from ac_platform.conversation_intelligence.brain4_eval import Dataset, GoldLine, Label

START = datetime(2026, 10, 16, tzinfo=UTC)


def line(
    call: str,
    target: str,
    *,
    verdict: str | None = "agree",
    score: int | None = None,
    status: str | None = None,
    reasons: tuple[str, ...] = (),
    skip: str | None = None,
    ai_score: int | None = 80,
    ai_status: str | None = "good",
    minute: int = 0,
) -> GoldLine:
    return GoldLine(
        recording_id=call,
        review_id=f"review-{call}",
        target=target,
        created_at=START + timedelta(minutes=minute),
        verdict=verdict,
        score=score,
        status=status,
        reasons=reasons,
        skip=skip,
        ai_status=ai_status,
        ai_score=ai_score,
    )


def review(**ratings: int | None) -> dict:
    return {
        "dimensions": [
            {
                "id": d,
                "rating": ratings.get(d, 4),
                "applicability": "applicable" if ratings.get(d, 4) is not None else "x",
            }
            for d in brain4.DIMENSION_IDS
        ]
    }


def test_labels_follow_what_the_reviewer_said() -> None:
    assert brain4_eval.label(line("c", "tone_energy", skip="not_sure")) is None
    assert brain4_eval.label(line("c", "tone_energy")) == Label("band", "good")
    assert brain4_eval.label(line("c", "tone_energy", verdict="disagree", score=45)) == Label(
        "band", "needs_improvement"
    )
    assert brain4_eval.label(
        line("c", "tone_energy", verdict="disagree", status="not_observed")
    ) == Label("unscored", "not_observed")
    assert brain4_eval.label(
        line("c", "tone_energy", verdict="partly", reasons=("too_harsh",))
    ) == Label("direction", "up")
    assert (
        brain4_eval.label(
            line("c", "tone_energy", verdict="partly", reasons=("too_harsh", "too_generous"))
        )
        is None
    )
    assert brain4_eval.label(
        line("c", "tone_energy", ai_score=None, ai_status="not_applicable")
    ) == Label("unscored", "not_applicable")


def test_statistics() -> None:
    assert brain4_eval.weighted_kappa([(0, 0), (1, 1), (2, 2), (3, 3)]) == 1.0
    assert brain4_eval.weighted_kappa([(2, 2), (2, 2)]) is None
    assert brain4_eval.weighted_kappa([(0, 3), (3, 0), (1, 2), (2, 1)]) < 0
    low, high = brain4_eval.wilson(8, 10)
    assert 0.49 < low < 0.5 and 0.94 < high < 0.95
    assert brain4_eval.wilson(0, 0) is None


def test_bootstrap_is_repeatable_and_resamples_calls() -> None:
    clusters = {"a": [1, 1], "b": [0], "c": [1, 0, 1]}

    def share(sample: list[int]) -> float:
        return sum(sample) / len(sample)

    first = brain4_eval.bootstrap(clusters, share, runs=200)
    assert first == brain4_eval.bootstrap(clusters, share, runs=200)
    assert first is not None and 0 <= first[0] <= first[1] <= 1
    assert brain4_eval.bootstrap({"a": [1]}, share) is None


def test_evaluation_compares_both_scorers_on_the_same_lines() -> None:
    lines = []
    runs = {}
    for n in range(30):
        call = f"c{n}"
        # Gold: the reviewer agrees with "good" on active listening; says next steps
        # deserved 45 (needs improvement) where today's review said 80.
        lines.append(line(call, "active_listening", minute=n))
        lines.append(line(call, "next_steps", verdict="disagree", score=45, minute=n))
        lines.append(line(call, "call_control", minute=n))  # no dimension
        runs[f"review-{call}"] = [review(D18=2), review(D18=2)]
    result = brain4_eval.evaluate(Dataset(tuple(lines), runs), now=START)
    dims = {d["id"]: d for d in result["dimensions"]}
    listening, steps = dims["D04"], dims["D18"]
    assert listening["brain4"]["exact"] == 1.0
    assert listening["classic"]["exact"] == 1.0
    assert steps["brain4"]["exact"] == 1.0
    assert steps["classic"]["exact"] == 0.0
    assert steps["classic"]["lean"] == 2.0  # today's review two bands too generous
    assert steps["brain4"]["calls"] == 30
    assert steps["readiness"]["state"] == "beta"  # below 50 calls; kappa undefined
    assert dims["D01"]["brain4"]["lines"] == 0
    assert dims["D01"]["readiness"]["state"] == "needs_data"
    assert result["classic_acceptance"]["agree"] == 60
    assert result["classic_acceptance"]["disagree"] == 30
    assert result["gold"] == {
        "lines": 90,
        "calls": 30,
        "calls_with_brain4": 30,
        "first": START.isoformat(),
        "last": (START + timedelta(minutes=29)).isoformat(),
    }
    assert result["stability"]["D18"] == {"calls": 30, "same": 1.0}
    assert result["alerts"] == []
    assert not any("opinion" in str(key) for key in result)


def test_readiness_never_says_official() -> None:
    strong = {"calls": 80, "kappa": 0.82, "kappa_ci": (0.74, 0.88), "within_one": 0.97}
    assert brain4_eval.readiness(strong) == {"state": "gate3_candidate", "needs": []}
    weak = {"calls": 80, "kappa": 0.55, "kappa_ci": (0.4, 0.7), "within_one": 0.97}
    assert brain4_eval.readiness(weak)["state"] == "beta"
    assert brain4_eval.readiness({"calls": 5})["state"] == "needs_data"


def test_drop_alert_needs_a_real_fall() -> None:
    steady = [(START + timedelta(minutes=n), n % 5 != 0) for n in range(200)]
    assert brain4_eval.drops(steady)["alert"] is False
    fall = [(START + timedelta(minutes=n), n < 140 or n % 3 == 0) for n in range(200)]
    result = brain4_eval.drops(fall)
    assert result["alert"] is True and result["recent"] < result["before"]
    assert brain4_eval.drops(steady[:50]) is None


def test_calibration_fit_keeps_order_and_needs_enough_pairs() -> None:
    lines, runs = [], {}
    for n in range(20):
        call = f"c{n}"
        # Brain 4.0 says 4 on next steps; the reviewer endorses "average" (shown as 3).
        lines.append(line(call, "next_steps", verdict="disagree", score=60))
        runs[f"review-{call}"] = [review(D18=4)]
    fitted = brain4_eval.fit_calibration(
        Dataset(tuple(lines), runs), revision="brain4-calibration/1"
    )
    assert fitted.maps == {"D18": {4: 3}}
    assert fitted.basis == "gold_set"
    few = brain4_eval.fit_calibration(
        Dataset(tuple(lines[:3]), runs), revision="brain4-calibration/1"
    )
    assert few.maps == {}


def test_the_gold_v1_checkpoint_is_counts_only_and_in_the_evaluation() -> None:
    import json

    found = brain4_eval.checkpoints()
    assert [item["checkpoint"] for item in found] == ["gold-v1/2026-10-21"]
    gold = found[0]
    assert gold["calls"] == 6 and gold["labels"]["total"] == 43
    for scorer in gold["scorers"]:
        overall = scorer["overall"]
        assert 0 <= overall["agree"] <= overall["rated"] <= overall["labels"]
        assert overall["labels"] % 43 == 0  # one set of labels per read of each call
        assert set(scorer["dimensions"]) <= set(brain4.DIMENSION_IDS)
    # Counts and agreement only: no call id, quote or note.
    text = json.dumps(gold)
    assert "rc-" not in text and "statement" not in text and "quote" not in text
    result = brain4_eval.evaluate(Dataset((), {}), now=START)
    assert result["checkpoints"][0]["checkpoint"] == "gold-v1/2026-10-21"
