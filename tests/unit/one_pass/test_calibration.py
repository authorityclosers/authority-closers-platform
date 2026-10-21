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
    # Statuses and the input are untouched; a calibrated review is never shifted twice.
    assert [p["status"] for p in calibrated["pointers"]] == [
        p["status"] for p in review["pointers"]
    ]
    assert review["pointers"][0]["score"] == 90 and "calibration" not in review
    assert calibration.calibrate(calibrated) == calibrated


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
