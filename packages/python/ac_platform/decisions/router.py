"""Local character TF-IDF embeddings over approved answer questions, no AI calls.

Fixture harness until Dipak's approved 500 Q&A arrive. A lexical embedding does
not establish semantic or multilingual accuracy. Threshold must be frozen on a
separate validation set, with approval/version retained on each answer.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Answer:
    key: str
    question: str
    answer: str
    version: str
    approved: bool


def grams(text: str) -> Counter[str]:
    normalized = " ".join(re.findall(r"\w+", text.casefold()))
    return Counter(normalized[i : i + 3] for i in range(max(0, len(normalized) - 2)))


class AnswerRouter:
    def __init__(self, answers: list[Answer], threshold: float = 0.65) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be in [0,1]")
        self.answers = [a for a in answers if a.approved and a.version]
        if len({a.key for a in self.answers}) != len(self.answers):
            raise ValueError("duplicate approved answer key")
        self.threshold = threshold
        documents = [grams(a.question) for a in self.answers]
        self.idf = {
            token: math.log((len(documents) + 1) / (1 + sum(token in d for d in documents))) + 1
            for token in {t for d in documents for t in d}
        }
        self.vectors = [self.embed(a.question) for a in self.answers]

    def embed(self, text: str) -> dict[str, float]:
        vector = {k: v * self.idf[k] for k, v in grams(text).items() if k in self.idf}
        norm = math.sqrt(sum(v * v for v in vector.values()))
        return {k: v / norm for k, v in vector.items()} if norm else {}

    def route(self, question: str) -> dict[str, str | float | None]:
        query = self.embed(question)
        scores = [
            sum(value * vector.get(k, 0) for k, value in query.items()) for vector in self.vectors
        ]
        best = max(range(len(scores)), key=lambda i: scores[i]) if scores else None
        if best is None or scores[best] < self.threshold:
            return {"answer_key": None, "similarity": max(scores, default=0), "status": "abstain"}
        answer = self.answers[best]
        return {
            "answer_key": answer.key,
            "answer": answer.answer,
            "version": answer.version,
            "similarity": scores[best],
            "status": "approved_suggestion",
        }
