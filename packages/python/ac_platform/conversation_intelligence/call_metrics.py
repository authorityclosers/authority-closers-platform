"""Pure Python twin of Sales Xray's call-metrics/2 transcript measurements."""

from __future__ import annotations

import math
import re
from typing import Final, TypedDict

CALL_METRICS_RULES: Final = "call-metrics/2"
MONOLOGUE_GAP_MS: Final = 2000
_MONOLOGUE_LIMIT: Final = 3
_PRICE_MOMENT_LIMIT: Final = 20
_STORED_CUT_IN_LIMIT: Final = 50
_END_PUNCTUATION: Final = re.compile(r"[.?!।？！…]$")
_QUESTION_MARKS: Final = re.compile(r"[?？]+")
PRICE_WORDS: Final = re.compile(
    r"(budget|बजट|price|प्राइस|कीमत|fees?|फीस|charges|कितने का है|कितने का पड़ेगा)",
    re.IGNORECASE,
)


class QuietRules(TypedDict):
    bin_ms: int
    below: float
    min_bins: int
    recover: float


class CutInRules(TypedDict):
    overlap_ms: int
    latch_ms: int


QUIET_RULES: Final[QuietRules] = {
    "bin_ms": 60000,
    "below": 0.1,
    "min_bins": 3,
    "recover": 0.25,
}
CUT_IN_RULES: Final[CutInRules] = {"overlap_ms": 250, "latch_ms": 100}


class TranscriptSegment(TypedDict):
    id: str
    speaker_id: str | None
    start_ms: int
    end_ms: int
    text: str


class TimedTranscriptSegment(TypedDict):
    id: str
    speaker_id: str
    start_ms: int
    end_ms: int
    text: str


class SpeakerMetrics(TypedDict):
    talk_ms: int
    talk_share: float | None
    questions: int
    questions_per_minute: float | None
    cut_ins: int
    longest_monologue_ms: int


class CurveBin(TypedDict):
    start_ms: int
    shares: dict[str, float | None]


class Monologue(TypedDict):
    speaker_id: str
    start_ms: int
    end_ms: int


class CutIn(TypedDict):
    speaker_id: str
    over_speaker_id: str
    segment_id: str
    over_segment_id: str
    at_ms: int
    overlap_ms: int


class PriceMoment(TypedDict):
    segment_id: str
    speaker_id: str
    at_ms: int
    silence_ms: int | None
    next_speaker_id: str | None
    next_segment_id: str | None


class LongestReplyAfterQuestion(TypedDict):
    speaker_id: str
    question_segment_id: str
    start_ms: int
    end_ms: int


class CallMetrics(TypedDict):
    time_used_ms: int
    speakers: dict[str, SpeakerMetrics]
    curve: list[CurveBin]
    monologues: list[Monologue]
    cut_ins: list[CutIn]
    price_moments: list[PriceMoment]
    longest_reply_after_question: LongestReplyAfterQuestion | None


class TimePromiseEvidence(TypedDict):
    segment_id: str


class TimePromise(TypedDict):
    promised_ms: int
    evidence: list[TimePromiseEvidence]


class QuietRun(TypedDict):
    start_ms: int
    recovered: bool


class StoredSpeakerSummary(TypedDict):
    talk_ms: int
    talk_share: float | None
    questions: int
    questions_per_minute: float | None
    cut_ins: int
    longest_monologue_ms: int


class StoredSummary(TypedDict):
    rules: str
    time_used_ms: int
    speakers: dict[str, StoredSpeakerSummary]
    quiet: dict[str, QuietRun | None]
    cut_ins: list[CutIn]
    price_moments: list[PriceMoment]
    longest_reply_after_question: LongestReplyAfterQuestion | None


Interval = tuple[int, int]


def _round2(value: float) -> float:
    """Round a non-negative ratio with the shared half-up rule."""
    return math.floor(value * 100 + 0.5) / 100


def _count_questions(text: str) -> int:
    return len(_QUESTION_MARKS.findall(text))


def _timed_segments(segments: list[TranscriptSegment]) -> list[TimedTranscriptSegment]:
    timed: list[TimedTranscriptSegment] = []
    for segment in segments:
        speaker_id = segment["speaker_id"]
        if speaker_id is None or segment["end_ms"] <= segment["start_ms"]:
            continue
        timed.append(
            {
                "id": segment["id"],
                "speaker_id": speaker_id,
                "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"],
                "text": segment["text"],
            }
        )
    return sorted(timed, key=lambda segment: (segment["start_ms"], segment["end_ms"]))


def _union(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start_ms, end_ms in sorted(intervals, key=lambda interval: interval[0]):
        if merged and start_ms <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
        else:
            merged.append((start_ms, end_ms))
    return merged


def _overlap_ms(intervals: list[Interval], from_ms: int, to_ms: float) -> int:
    return sum(
        int(max(0, min(end_ms, to_ms) - max(start_ms, from_ms))) for start_ms, end_ms in intervals
    )


def compute_call_metrics(segments: list[TranscriptSegment], duration_ms: int | None) -> CallMetrics:
    """Compute the deterministic timing measurements for transcript segments."""
    timed = _timed_segments(segments)
    last_end = max(0, *(segment["end_ms"] for segment in timed))
    time_used = duration_ms if duration_ms is not None and duration_ms > 0 else last_end

    talk: dict[str, list[Interval]] = {}
    questions: dict[str, int] = {}
    for source_segment in segments:
        speaker_id = source_segment["speaker_id"]
        if speaker_id is None:
            continue
        talk.setdefault(speaker_id, [])
        questions[speaker_id] = questions.get(speaker_id, 0) + _count_questions(
            source_segment["text"]
        )
    for timed_segment in timed:
        talk[timed_segment["speaker_id"]].append(
            (timed_segment["start_ms"], timed_segment["end_ms"])
        )
    talk = {speaker_id: _union(intervals) for speaker_id, intervals in talk.items()}

    talk_ms = {
        speaker_id: _overlap_ms(intervals, 0, math.inf) for speaker_id, intervals in talk.items()
    }
    total_ms = sum(talk_ms.values())
    speakers: dict[str, SpeakerMetrics] = {}
    for speaker_id, milliseconds in talk_ms.items():
        question_count = questions.get(speaker_id, 0)
        speakers[speaker_id] = {
            "talk_ms": milliseconds,
            "talk_share": _round2(milliseconds / total_ms) if total_ms > 0 else None,
            "questions": question_count,
            "questions_per_minute": (
                _round2(question_count / (time_used / 60000)) if time_used > 0 else None
            ),
            "cut_ins": 0,
            "longest_monologue_ms": 0,
        }

    curve: list[CurveBin] = []
    for from_ms in range(0, time_used, QUIET_RULES["bin_ms"]):
        to_ms = min(from_ms + QUIET_RULES["bin_ms"], time_used)
        in_bin = {
            speaker_id: _overlap_ms(intervals, from_ms, to_ms)
            for speaker_id, intervals in talk.items()
        }
        bin_total = sum(in_bin.values())
        curve.append(
            {
                "start_ms": from_ms,
                "shares": {
                    speaker_id: _round2(milliseconds / bin_total) if bin_total > 0 else None
                    for speaker_id, milliseconds in in_bin.items()
                },
            }
        )

    runs: list[Monologue] = []
    for monologue_segment in timed:
        run = runs[-1] if runs else None
        if (
            run is not None
            and run["speaker_id"] == monologue_segment["speaker_id"]
            and monologue_segment["start_ms"] - run["end_ms"] <= MONOLOGUE_GAP_MS
        ):
            run["end_ms"] = max(run["end_ms"], monologue_segment["end_ms"])
        else:
            runs.append(
                {
                    "speaker_id": monologue_segment["speaker_id"],
                    "start_ms": monologue_segment["start_ms"],
                    "end_ms": monologue_segment["end_ms"],
                }
            )
    for run in runs:
        speaker = speakers[run["speaker_id"]]
        speaker["longest_monologue_ms"] = max(
            speaker["longest_monologue_ms"], run["end_ms"] - run["start_ms"]
        )

    cut_ins: list[CutIn] = []
    for index, cut_in_segment in enumerate(timed):
        over_segment: TimedTranscriptSegment | None = None
        for prior in timed[:index]:
            if prior["speaker_id"] != cut_in_segment["speaker_id"] and (
                over_segment is None or prior["end_ms"] >= over_segment["end_ms"]
            ):
                over_segment = prior
        if over_segment is None:
            continue

        overlap = over_segment["end_ms"] - cut_in_segment["start_ms"]
        gap = cut_in_segment["start_ms"] - over_segment["end_ms"]
        is_cut_in = overlap >= CUT_IN_RULES["overlap_ms"] or (
            0 <= gap <= CUT_IN_RULES["latch_ms"]
            and _END_PUNCTUATION.search(over_segment["text"].strip()) is None
        )
        if not is_cut_in:
            continue

        cut_ins.append(
            {
                "speaker_id": cut_in_segment["speaker_id"],
                "over_speaker_id": over_segment["speaker_id"],
                "segment_id": cut_in_segment["id"],
                "over_segment_id": over_segment["id"],
                "at_ms": cut_in_segment["start_ms"],
                "overlap_ms": max(0, overlap),
            }
        )
        speakers[cut_in_segment["speaker_id"]]["cut_ins"] += 1

    price_moments: list[PriceMoment] = []
    for index, price_segment in enumerate(timed):
        if PRICE_WORDS.search(price_segment["text"]) is None:
            continue
        next_segment = next(
            (
                candidate
                for candidate in timed[index + 1 :]
                if candidate["speaker_id"] != price_segment["speaker_id"]
            ),
            None,
        )
        price_moments.append(
            {
                "segment_id": price_segment["id"],
                "speaker_id": price_segment["speaker_id"],
                "at_ms": price_segment["start_ms"],
                "silence_ms": (
                    max(0, next_segment["start_ms"] - price_segment["end_ms"])
                    if next_segment is not None
                    else None
                ),
                "next_speaker_id": next_segment["speaker_id"] if next_segment else None,
                "next_segment_id": next_segment["id"] if next_segment else None,
            }
        )
        if len(price_moments) == _PRICE_MOMENT_LIMIT:
            break

    longest_reply: LongestReplyAfterQuestion | None = None
    for index, question_segment in enumerate(timed):
        if _count_questions(question_segment["text"]) == 0:
            continue
        reply_index = next(
            (
                candidate_index
                for candidate_index in range(index + 1, len(timed))
                if timed[candidate_index]["speaker_id"] != question_segment["speaker_id"]
            ),
            None,
        )
        if reply_index is None:
            continue

        reply = timed[reply_index]
        end_ms = reply["end_ms"]
        for next_segment in timed[reply_index + 1 :]:
            if (
                next_segment["speaker_id"] != reply["speaker_id"]
                or next_segment["start_ms"] - end_ms > MONOLOGUE_GAP_MS
            ):
                break
            end_ms = max(end_ms, next_segment["end_ms"])

        candidate: LongestReplyAfterQuestion = {
            "speaker_id": reply["speaker_id"],
            "question_segment_id": question_segment["id"],
            "start_ms": reply["start_ms"],
            "end_ms": end_ms,
        }
        if longest_reply is None or (
            candidate["end_ms"] - candidate["start_ms"]
            > longest_reply["end_ms"] - longest_reply["start_ms"]
        ):
            longest_reply = candidate

    monologues = sorted(
        runs,
        key=lambda run: (-(run["end_ms"] - run["start_ms"]), run["start_ms"]),
    )[:_MONOLOGUE_LIMIT]

    return {
        "time_used_ms": time_used,
        "speakers": speakers,
        "curve": curve,
        "monologues": monologues,
        "cut_ins": cut_ins,
        "price_moments": price_moments,
        "longest_reply_after_question": longest_reply,
    }


def quiet_from(metrics: CallMetrics, speaker_id: str) -> QuietRun | None:
    """Return the first unrecovered quiet run, or the first recovered one."""
    if speaker_id not in metrics["speakers"]:
        return None

    first_recovered: QuietRun | None = None
    run_start = -1
    run_length = 0
    for index, bin_ in enumerate(metrics["curve"]):
        share = bin_["shares"].get(speaker_id)
        low = share is not None and share < QUIET_RULES["below"]
        run_length = run_length + 1 if low else 0
        if run_length == 1:
            run_start = index
        if run_length == QUIET_RULES["min_bins"]:
            recovered = any(
                share is not None and share >= QUIET_RULES["recover"]
                for later in metrics["curve"][index + 1 :]
                if (share := later["shares"].get(speaker_id)) is not None
            )
            run: QuietRun = {
                "start_ms": metrics["curve"][run_start]["start_ms"],
                "recovered": recovered,
            }
            if not recovered:
                return run
            if first_recovered is None:
                first_recovered = run
    return first_recovered


def time_promise_overrun(
    promise: TimePromise | None,
    segments: list[TranscriptSegment],
    time_used_ms: int,
) -> int | None:
    """Return milliseconds over the first evidence-backed promise, if present."""
    if promise is None or not promise["evidence"]:
        return None
    evidence_id = promise["evidence"][0]["segment_id"]
    segment = next((item for item in segments if item["id"] == evidence_id), None)
    if segment is None:
        return None
    return max(0, time_used_ms - (segment["start_ms"] + promise["promised_ms"]))


def stored_summary(segments: list[TranscriptSegment], duration_ms: int | None) -> StoredSummary:
    """Build the compact, transcript-free summary for per-call storage."""
    metrics = compute_call_metrics(segments, duration_ms)
    return {
        "rules": CALL_METRICS_RULES,
        "time_used_ms": metrics["time_used_ms"],
        "speakers": {
            speaker_id: {
                "talk_ms": speaker["talk_ms"],
                "talk_share": speaker["talk_share"],
                "questions": speaker["questions"],
                "questions_per_minute": speaker["questions_per_minute"],
                "cut_ins": speaker["cut_ins"],
                "longest_monologue_ms": speaker["longest_monologue_ms"],
            }
            for speaker_id, speaker in metrics["speakers"].items()
        },
        "quiet": {
            speaker_id: quiet_from(metrics, speaker_id) for speaker_id in metrics["speakers"]
        },
        "cut_ins": metrics["cut_ins"][:_STORED_CUT_IN_LIMIT],
        "price_moments": metrics["price_moments"],
        "longest_reply_after_question": metrics["longest_reply_after_question"],
    }
