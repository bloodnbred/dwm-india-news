"""Word lists for feature engineering.

Kept in code rather than downloaded from NLTK on purpose: the pipeline must
run offline and reproducibly, and a stopword list that silently changes
between runs would move every keyword-based number in the report.

Every list here is a judgement call and is documented as such. They are
heuristics for a *risk signal*, not validated measures of anything.
"""

from __future__ import annotations

# Compact English stopword list. Deliberately short: the corpus is headlines,
# where most function words are already rare, and an aggressive list would
# strip meaning from a 45-character headline.
STOPWORDS: frozenset[str] = frozenset(
    ["a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "cannot", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "out", "over", "own", "said", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "us", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your"]
)

# Words that mark a claim as extreme or attention-grabbing. Used for the
# superlative component of the sensationalism score.
#
# Kept disjoint from URGENCY: a term in both lists would inflate two
# sub-signals from a single word and destroy the independence the composite
# score relies on. "exclusive" is an attention signal, so it lives in
# URGENCY only. A test asserts the two sets do not overlap.
SUPERLATIVES: frozenset[str] = frozenset(
    ["biggest", "largest", "smallest", "fastest", "slowest", "worst", "best", "greatest", "latest", "shocking", "stunning", "sensational", "dramatic", "drastic", "massive", "huge", "enormous", "incredible", "unstoppable", "unbeatable", "record-breaking", "historic", "unprecedented", "devastating", "catastrophic", "explosive", "mind-blowing", "jaw-dropping"]
)

# Words that manufacture urgency. Separate from superlatives because they
# signal a different thing: "breaking" is not an extreme claim, it is a
# demand for attention now.
URGENCY: frozenset[str] = frozenset(
    ["breaking", "exclusive", "urgent", "urgently", "alert", "warning", "warned", "crisis", "crackdown", "emergency", "sofort", "updates", "twist", "bombshell", "shock", "expose", "exposed", "leaked"]
)

# Negation words. VADER already handles these internally for its own lexicon;
# this list exists so the report can report a negation rate as a style signal.
NEGATIONS: frozenset[str] = frozenset(
    ["no", "not", "never", "none", "cannot", "cant", "dont", "doesnt", "didnt", "wont", "wouldnt", "couldnt", "shouldnt", "isnt", "arent", "wasnt", "werent", "hardly", "barely", "without"]
)

# Tokens that are never keywords regardless of frequency.
KEYWORD_BLOCKLIST: frozenset[str] = frozenset(
    ["news", "india", "indias", "times", "said", "says", "say", "new", "year", "years", "day", "days", "week", "month", "report", "reports", "reported", "update", "updates", "live", "video", "videos", "photo", "photos", "full", "read", "more", "watch", "listen", "click", "here", "home", "page"]
)


def all_lexicons() -> dict[str, frozenset[str]]:
    return {
        "stopwords": STOPWORDS,
        "superlatives": SUPERLATIVES,
        "urgency": URGENCY,
        "negations": NEGATIONS,
        "blocklist": KEYWORD_BLOCKLIST,
    }
