"""One pass's pointer scores, calibrated to today's review and labelled beta (B3)."""

from __future__ import annotations

from ac_platform.conversation_intelligence import pointer_review
from ac_platform.one_pass import calibration


def _review() -> dict:
    return {
        "version": pointer_review.VERSION,
        "overall": {
            "score": 72,
            "label": pointer_review.BAND_LABEL[pointer_review.band(72)],
            "line": "A clear call.",
            "method": "mean_of_scored_pointers",
            "scored_pointers": 3,
        },
        "pointers": [
            {"id": "next_steps", "status": "good", "score": 90},
            {"id": "prospect_role", "status": "average", "score": 50},
            {"id": "tone_energy", "status": "not_observed", "score": None},
            {"id": "unknown_pointer", "status": "good", "score": 3},
        ],
    }


def test_scores_move_by_each_pointers_measured_lean_and_the_overall_follows() -> None:
    review = _review()
    calibrated = calibration.calibrate(review)
    scores = {pointer["id"]: pointer["score"] for pointer in calibrated["pointers"]}
    assert scores == {
        "next_steps": 83,  # 90 - 7.1
        "prospect_role": 49,  # 50 - 1.4
        "tone_energy": None,  # not scored stays not scored
        "unknown_pointer": 0,  # global lean, never below 0
    }
    assert calibrated["overall"]["score"] == round((83 + 49 + 0) / 3)
    assert (
        calibrated["overall"]["label"]
        == pointer_review.BAND_LABEL[pointer_review.band(calibrated["overall"]["score"])]
    )
    assert calibrated["overall"]["line"] == "A clear call."
    assert calibrated["calibration"] == {
        "version": calibration.VERSION,
        "label": "beta",
        "basis": "one_pass_c4",
    }
    # Scored statuses follow the calibrated score; the input is untouched; a calibrated
    # review is never shifted twice.
    assert [p["status"] for p in calibrated["pointers"]] == [
        "good",  # 83
        "needs_improvement",  # 49, was average
        "not_observed",
        "needs_improvement",  # 0
    ]
    assert [p["status"] for p in review["pointers"]] == [
        "good",
        "average",
        "not_observed",
        "good",
    ]
    assert review["pointers"][0]["score"] == 90 and "calibration" not in review
    assert calibration.calibrate(calibrated) == calibrated


def test_a_scored_status_follows_its_calibrated_score_and_an_unscored_one_stays() -> None:
    review = _review()
    review["pointers"] = [
        {"id": "next_steps", "status": "excellent", "score": 96},  # 89: good
        {"id": "decision_process", "status": "good", "score": 72},  # 65: average
        {"id": "business_impact", "status": "average", "score": 55},  # 48: needs_improvement
        {"id": "stakeholders", "status": "good", "score": 80},  # 78: still good
        {"id": "tone_energy", "status": "not_observed", "score": None},
        {"id": "handling_competition", "status": "not_applicable", "score": None},
        {"id": "handling_silence", "status": "insufficient_evidence", "score": None},
    ]
    calibrated = calibration.calibrate(review)
    statuses = {p["id"]: (p["status"], p["score"]) for p in calibrated["pointers"]}
    assert statuses == {
        "next_steps": ("good", 89),
        "decision_process": ("average", 65),
        "business_impact": ("needs_improvement", 48),
        "stakeholders": ("good", 78),
        "tone_energy": ("not_observed", None),
        "handling_competition": ("not_applicable", None),
        "handling_silence": ("insufficient_evidence", None),
    }
    # No row contradicts its score, as parse_review promises.
    for pointer in calibrated["pointers"]:
        if pointer["score"] is not None:
            assert pointer["status"] == pointer_review.band(pointer["score"])
    # The Report's rating comes from the status, so it matches the calibrated score.
    structure: dict = {
        "overview": {},
        "pointers": [{"id": p["id"]} for p in review["pointers"]],
    }
    for pointer in review["pointers"]:
        pointer.update(what_happened=None, why_it_matters=None, evidence=[], how_to_improve=[])
    merged = pointer_review.merge_into_structure(structure, calibration.calibrate(review))
    ratings = {p["id"]: (p["rating"], p["score"]) for p in merged["pointers"]}
    assert ratings["decision_process"] == ("Average", 65)
    assert ratings["next_steps"] == ("Good", 89)
    assert ratings["tone_energy"] == (None, None)


def test_every_pointer_has_its_fitted_lean() -> None:
    assert set(calibration.OFFSETS) == set(pointer_review.POINTER_IDS)
    assert all(0 < offset < 10 for offset in calibration.OFFSETS.values())


def test_the_report_shows_a_calibrated_score_as_a_beta() -> None:
    structure: dict = {"overview": {}, "pointers": []}
    plain = pointer_review.merge_into_structure(structure, _review())
    assert "score_calibration" not in plain["overview"]
    beta = pointer_review.merge_into_structure(structure, calibration.calibrate(_review()))
    assert beta["overview"]["score_calibration"] == {
        "version": calibration.VERSION,
        "label": "beta",
    }
    assert beta["overview"]["score_status"] == "ai_draft"


def test_a_luna_read_takes_lunas_own_calibration() -> None:
    review = _review()
    for model in ("gpt-6-luna", "gpt-6-luna:flex"):
        luna = calibration.calibrate(review, model=model)
        assert luna["calibration"] == {
            "version": calibration.LUNA_VERSION,
            "label": "beta",
            "basis": "one_pass_c4_luna",
        }
        for before, after in zip(review["pointers"], luna["pointers"], strict=True):
            if before["score"] is None:
                assert after["score"] is None and after["status"] == before["status"]
                continue
            offset = calibration.LUNA_OFFSETS.get(before["id"], calibration.LUNA_GLOBAL_OFFSET)
            assert after["score"] == max(0, min(100, round(before["score"] - offset)))
            assert after["status"] == pointer_review.band(after["score"])
    # Gemini's (or no model named) stays calibration v1, unchanged.
    assert calibration.calibrate(review, model="gemini-3.8-flash:flex") == calibration.calibrate(
        review
    )
    assert calibration.calibrate(review)["calibration"]["version"] == calibration.VERSION


def test_lunas_table_covers_every_pointer_and_leans_the_other_way() -> None:
    assert set(calibration.LUNA_OFFSETS) == set(pointer_review.POINTER_IDS)
    # Luna reads harsher than today's review (the trial): its offsets raise scores.
    assert calibration.LUNA_GLOBAL_OFFSET < 0
    assert all(-25 < offset < 10 for offset in calibration.LUNA_OFFSETS.values())
