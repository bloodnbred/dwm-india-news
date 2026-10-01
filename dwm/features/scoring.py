"""Per-text feature extraction.

One pass over the corpus produces every text measure: sentiment, the five
sensationalism sub-signals, the composite score, and the headline's keywords.
Doing it in a single pass matters: the corpus is 3.15M rows, and three
separate passes would triple the I/O.

The scorer is written to be used from a worker process: it holds no DuckDB
state, and the VADER analyzer is created once per process rather than per row.

**What this is not.** Every measure here is a *style* signal. Nothing in this
module detects misinformation, and no output of it may be described as a
fake-news rate. The blueprint's honesty rule is enforced in the column names
(`is_risk_signal`, not `is_fake`) and in the dimension that backs them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dwm.features.lexicons import (
    KEYWORD_BLOCKLIST,
    NEGATIONS,
    STOPWORDS,
    SUPERLATIVES,
    URGENCY,
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_CAPS_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")


@dataclass(frozen=True, slots=True)
class TextMeasures:
    """Measures for one text. Field names are the fact-table column names."""

    sentiment_compound: float
    sentiment_positive: float
    sentiment_negative: float
    sentiment_neutral: float
    char_count: int
    token_count: int
    unique_token_count: int
    caps_token_count: int
    caps_token_ratio: float
    exclamation_count: int
    question_count: int
    superlative_count: int
    urgency_count: int
    negation_count: int
    sensational_score: float
    is_sensational: bool
    is_risk_signal: bool


class TextScorer:
    """Stateless-per-row scorer. Create one per process and reuse it."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        sens = cfg.get("sensationalism", {})
        self.weights: dict[str, float] = {
            "caps_ratio": 0.35,
            "exclamation": 0.20,
            "question": 0.10,
            "superlative": 0.20,
            "urgency": 0.15,
            **(sens.get("weights") or {}),
        }
        self.saturation: dict[str, float] = {
            "caps_ratio": 0.30,
            "exclamation": 2.0,
            "question": 2.0,
            "superlative": 2.0,
            "urgency": 2.0,
            **(sens.get("saturation") or {}),
        }
        self.min_caps_length = int(sens.get("min_caps_length", 3))
        self.threshold = float(sens.get("threshold", 0.5))

        sent = cfg.get("sentiment", {})
        self.negative_compound = float(sent.get("negative_compound", -0.5))
        self.positive_compound = float(sent.get("positive_compound", 0.5))

        self._analyzer = _new_analyzer()
        # A CAPS token of at least min_caps_length characters.
        self._caps_re = re.compile(rf"\b[A-Z][A-Z0-9]{{{self.min_caps_length - 1},}}\b")

    # -- sentiment ---------------------------------------------------------
    def sentiment(self, text: str) -> dict[str, float]:
        return self._analyzer.polarity_scores(text)

    # -- the one pass ------------------------------------------------------
    def measure(self, text: str | None) -> TextMeasures:
        text = text or ""
        tokens = _TOKEN.findall(text.lower())
        token_set = set(tokens)

        sentiment = self._analyzer.polarity_scores(text)

        caps_count = len(self._caps_re.findall(text))
        # Ratio is over alphabetic tokens, so a headline made of digits does
        # not register as shouting just by having no lowercase.
        alpha_total = sum(1 for t in tokens if t.isalpha())
        caps_ratio = (caps_count / alpha_total) if alpha_total else 0.0

        exclam = text.count("!")
        question = text.count("?")
        superlatives = len(token_set & SUPERLATIVES)
        urgency = len(token_set & URGENCY)
        negations = len(token_set & NEGATIONS)

        score = self._composite(caps_ratio, exclam, question, superlatives, urgency)
        is_sensational = score >= self.threshold

        return TextMeasures(
            sentiment_compound=round(sentiment["compound"], 6),
            sentiment_positive=round(sentiment["pos"], 6),
            sentiment_negative=round(sentiment["neg"], 6),
            sentiment_neutral=round(sentiment["neu"], 6),
            char_count=len(text),
            token_count=len(tokens),
            unique_token_count=len(token_set),
            caps_token_count=caps_count,
            caps_token_ratio=round(caps_ratio, 6),
            exclamation_count=exclam,
            question_count=question,
            superlative_count=superlatives,
            urgency_count=urgency,
            negation_count=negations,
            sensational_score=round(score, 6),
            is_sensational=is_sensational,
            # The blueprint's wording: a headline is "flagged by the
            # sensationalism signal". There is no classifier signal available
            # for TOI, so the risk signal IS the sensationalism flag.
            is_risk_signal=is_sensational,
        )

    def _composite(
        self,
        caps_ratio: float,
        exclam: int,
        question: int,
        superlatives: int,
        urgency: int,
    ) -> float:
        parts = {
            "caps_ratio": caps_ratio,
            "exclamation": float(exclam),
            "question": float(question),
            "superlative": float(superlatives),
            "urgency": float(urgency),
        }
        total = 0.0
        for name, value in parts.items():
            sat = self.saturation.get(name, 1.0) or 1.0
            total += self.weights.get(name, 0.0) * min(value / sat, 1.0)
        return max(0.0, min(1.0, total))

    def sentiment_flag(self, compound: float) -> str:
        """Coarse sentiment label. Reported as a style band, not a judgement."""
        if compound <= self.negative_compound:
            return "negative"
        if compound >= self.positive_compound:
            return "positive"
        return "neutral"

    # -- keywords ----------------------------------------------------------
    def keywords(self, text: str | None, vocabulary: dict[str, int], limit: int) -> list[int]:
        """Vocabulary indices present in the text, in vocabulary rank order.

        Intersects the text's own tokens with the vocabulary rather than
        scanning the vocabulary per row. The previous form tested all 300
        terms against every headline, which is 945M lookups over the corpus
        where the text has about 8 tokens. keyword_key is assigned in
        frequency-rank order, so sorting by it reproduces "most frequent
        first" exactly.
        """
        if not text or not vocabulary:
            return []
        hits = [
            vocabulary[token]
            for token in set(_TOKEN.findall(text.lower()))
            if token in vocabulary
        ]
        hits.sort()
        return hits[:limit]


def eligible_terms(texts: Sequence[str], *, min_length: int) -> dict[str, int]:
    """Document frequency over a corpus sample, for choosing a vocabulary.

    Counted on a sample because an exact count over 3.15M headlines buys
    nothing: the vocabulary is capped at 300 terms anyway, and the ordering
    within the top 300 is not sensitive to small frequency differences.
    """
    freq: dict[str, int] = {}
    for text in texts:
        for token in set(_TOKEN.findall((text or "").lower())):
            if len(token) < min_length:
                continue
            if token in STOPWORDS or token in KEYWORD_BLOCKLIST:
                continue
            if not any(ch.isalpha() for ch in token):
                continue
            freq[token] = freq.get(token, 0) + 1
    return freq


def _new_analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()
