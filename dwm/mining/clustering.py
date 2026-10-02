"""Topic clustering (RQ4): TF-IDF plus K-Means over the headlines.

What this answers and what it does not.

It answers "what groups of vocabulary do these headlines fall into". It does
NOT recover the publisher's own topics: the source already supplies
`headline_category`, and a cluster is a set of words, not a desk. The report
must present clusters as language groupings and may then compare them against
the supplied topics, which is the genuinely interesting part.

Three decisions:

**A fixed random sample, not the whole corpus.** K-Means on 1.1M short
documents is not practical and would not teach more than one on 60,000. The
sample is drawn with a fixed seed, so the clusters reproduce exactly.

**k is chosen by silhouette, and the full table is reported.** Guessing k
would make the answer arbitrary. Every candidate's score is returned, and a
weak silhouette is reported as weak rather than hidden, because "the data has
no strong cluster structure" is a real finding about short headlines.

**Cluster descriptions come from the top terms.** A label is built from the
terms with the highest centroid weight, so each cluster is readable.
"""

from __future__ import annotations

from typing import Any

import duckdb
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

from dwm.logging_utils import get
from dwm.mining.sampling import sample_rows


def pct(value: float | None, places: int = 2) -> str:
    """Local copy rather than an import from the report layer.

    The mining stage must not depend on the inference stage that renders it;
    a percentage-formatting helper duplicated between the two is a smaller
    cost than an inverted dependency between phases.
    """
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"

log = get("dwm.mining.clustering")


def sample_corpus(
    con: duckdb.DuckDBPyConnection, size: int, seed: int, in_window: bool = True
) -> tuple[list[str], list[int]]:
    """A reproducible random sample of headline text.

    The draw happens in SQL, ordered by a seeded hash, so it does not depend on
    fetching 1.1M rows into Python first. See `dwm/mining/sampling.py` for why
    the built-in sampler was not used.
    """
    where = "WHERE in_window" if in_window else ""
    rows = sample_rows(
        con,
        "headline_id, headline_text, topic_key",
        source="fact_headline",
        where=where,
        size=size,
        seed=seed,
    )
    return [r[1] for r in rows], [r[2] for r in rows]


def cluster_headlines(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ4: TF-IDF, then K-Means for each candidate k, scored by silhouette."""
    cfg = config.get("clustering", {})
    sample_size = int(cfg.get("sample_size", 60_000))
    seed = int(cfg.get("seed", 0))
    k_min, k_max = int(cfg.get("k_min", 4)), int(cfg.get("k_max", 12))
    ngram = tuple(cfg.get("ngram_range", [1, 2]))
    min_df = int(cfg.get("min_df", 5))
    max_features = int(cfg.get("max_features", 20_000))
    sublinear = bool(cfg.get("sublinear_tf", True))

    texts, topic_keys = sample_corpus(con, sample_size, seed)
    if len(texts) < k_max * 2:
        return {
            "ran": False,
            "reason": (
                f"only {len(texts)} headlines available, need at least "
                f"{k_max * 2} to score k up to {k_max}"
            ),
            "available": len(texts),
        }

    vectorizer = TfidfVectorizer(
        ngram_range=ngram,
        min_df=min_df,
        max_features=max_features,
        sublinear_tf=sublinear,
        strip_accents="unicode",
        lowercase=True,
        # Alphabetic tokens only, and no English stop words. Without the first
        # the top terms of every cluster are numerals; without the second they
        # are function words. Both were observed, and both made the cluster
        # descriptions useless as the only human-readable output of this stage.
        token_pattern=cfg.get("token_pattern", r"(?u)\b[a-zA-Z][a-zA-Z]+\b"),
        stop_words=cfg.get("stop_words", "english"),
    )
    tfidf = vectorizer.fit_transform(texts)
    terms = np.array(vectorizer.get_feature_names_out())
    log.info("tf-idf: %s documents x %s features", tfidf.shape[0], tfidf.shape[1])

    # Reduce with truncated SVD (LSA) before clustering.
    #
    # K-Means on the raw 20,000-dimensional sparse TF-IDF matrix measured a
    # silhouette of 0.005 at every k from 4 to 12, which is zero separation:
    # in that many dimensions every document is nearly equidistant from every
    # other, so distance-based clustering has nothing to work with. LSA is the
    # standard remedy for short text and is what makes the silhouette
    # informative. The reduction is reported, not hidden.
    n_components = int(cfg.get("svd_components", 100))
    n_components = min(n_components, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
    reducer = TruncatedSVD(n_components=n_components, random_state=seed)
    reduced = reducer.fit_transform(tfidf)
    explained = float(reducer.explained_variance_ratio_.sum())
    log.info(
        "lsa: %s -> %s components, %.1f%% variance explained",
        tfidf.shape[1], n_components, explained * 100,
    )

    scores = []
    best = None
    for k in range(k_min, k_max + 1):
        model = KMeans(n_clusters=k, random_state=seed, n_init=10)
        labels = model.fit_predict(reduced)
        # random_state is required. silhouette_score subsamples when the corpus
        # is large, and with no seed it draws a different subsample on every
        # call, so the score moved between runs of an otherwise identical
        # pipeline: 0.0652 then 0.0681 for the same k and the same sample.
        silhouette = float(
            silhouette_score(
                reduced,
                labels,
                sample_size=min(20_000, len(labels)),
                random_state=seed,
            )
        )
        scores.append({"k": k, "silhouette": round(silhouette, 4)})
        log.info("  k=%s silhouette=%.4f", k, silhouette)
        # Ties break to the smaller k, the more parsimonious reading.
        if best is None or silhouette > best[1]:
            best = (k, silhouette, labels, model)

    assert best is not None
    k, silhouette, labels, model = best

    # Describe each cluster by the mean TF-IDF of its own documents.
    #
    # Not by the K-Means centroid weights. The centroid lives in the 100-
    # dimension LSA space, and projecting its weights back onto the term axis
    # does not recover which words define the cluster: measured here, it
    # returned `aadhaar, aadmi, aap, aarti, aaryan` for every cluster, because
    # the SVD components carry an arbitrary sign and an arbitrary scale, and
    # small numerical asymmetries make alphabetically-early features win
    # systematically. A cluster described by words that appear in all of them
    # describes nothing.
    #
    # Averaging the members' own TF-IDF rows is the standard approach and is
    # immune to that: it says which words are actually over-represented inside
    # this cluster relative to the corpus.
    terms_per_cluster = int(cfg.get("top_terms", 12))
    # Topic names resolved once, rather than per cluster through SQL:
    # DuckDB 1.5.6 cannot cast a bound list parameter into an INTEGER[] for
    # unnest, and the histogram is a handful of rows either way.
    topic_names = dict(
        con.execute("SELECT topic_key, topic_name FROM dim_topic").fetchall()
    )
    descriptions = []
    for cluster_id in range(k):
        member_mask = labels == cluster_id
        members = int(member_mask.sum())
        # Mean TF-IDF across the cluster, over the original sparse matrix.
        profile = np.asarray(tfidf[member_mask].mean(axis=0)).ravel()
        top = [str(terms[i]) for i in profile.argsort()[::-1][:terms_per_cluster]]
        # Which supplied topics dominate this cluster, so a reader can see
        # whether it lines up with the publisher's own taxonomy.
        topic_hist: dict[int, int] = {}
        for tk, m in zip(topic_keys, member_mask, strict=True):
            if m:
                topic_hist[tk] = topic_hist.get(tk, 0) + 1
        top_topics = [
            {
                "topic": topic_names.get(key, str(key)),
                "count": c,
                "share": round(c / members, 4) if members else None,
            }
            for key, c in sorted(topic_hist.items(), key=lambda kv: -kv[1])[:5]
        ]
        descriptions.append(
            {
                "cluster_id": int(cluster_id),
                "size": members,
                "share_of_sample": round(members / len(texts), 4),
                "top_terms": top,
                "dominant_supplied_topics": top_topics,
            }
        )

    descriptions.sort(key=lambda d: -d["size"])

    # A single cluster holding almost everything inflates the silhouette.
    #
    # Silhouette scores a document by its distance to its own cluster against
    # its distance to the nearest other one, so a large undifferentiated blob
    # that sits far from a few small tight ones scores very well. Measured
    # here, removing stop words moved the silhouette from 0.068 to 0.26 and
    # produced exactly that shape: one cluster over 90% of the corpus and three
    # small topical ones. The number is real and it is also easy to over-read,
    # so the concentration is reported next to it.
    dominant_share = descriptions[0]["share_of_sample"] if descriptions else None
    concentrated = bool(dominant_share is not None and dominant_share >= 0.5)
    small_clusters = [d for d in descriptions[1:] if d["share_of_sample"] >= 0.01]

    # A silhouette near zero means the clusters are not really separated.
    strong = silhouette >= 0.25
    # A silhouette that keeps rising to the largest k tried is not evidence of
    # k_max clusters. It is evidence of no preferred k, because any partition
    # looks slightly better when cut more finely. This is a common trap and it
    # has to be named, not reported as "the best k is 12".
    best_value = max(s["silhouette"] for s in scores)
    rising = [s["silhouette"] for s in scores]
    monotone_rising = all(
        b >= a - 1e-9 for a, b in zip(rising, rising[1:], strict=False)
    ) and len(scores) > 2
    k_at_ceiling = best_value == rising[-1] and k_max > k_min

    return {
        "ran": True,
        "sample_size": len(texts),
        "feature_count": int(tfidf.shape[1]),
        "svd_components": n_components,
        "svd_variance_explained": round(explained, 4),
        "seed": seed,
        "k_candidates": scores,
        "chosen_k": k,
        "silhouette": round(silhouette, 4),
        "silhouette_is_strong": strong,
        "dominant_cluster_share": round(dominant_share, 4) if dominant_share is not None else None,
        "structure_is_concentrated": concentrated,
        "distinct_small_clusters": len(small_clusters),
        "concentration_note": (
            f"One cluster holds {pct(dominant_share)} of the sample and "
            f"{len(small_clusters)} further clusters hold at least 1% each. A high "
            "silhouette in this shape does not mean the corpus is well clustered: "
            "it means a small, well-separated topical minority exists and the "
            "remainder is undifferentiated. Read the score and the shape together."
        ) if concentrated else (
            f"The largest cluster holds {pct(dominant_share)} of the sample, so "
            "the silhouette is not being propped up by a single dominant blob."
        ),
        "no_preferred_k": bool(k_at_ceiling or monotone_rising),
        "k_note": (
            f"Silhouette is highest at k={k_max}, the largest value tried, and "
            "the series does not turn over. That indicates the data has no "
            f"preferred cluster count rather than that k={k_max} is correct. "
            f"The k={k} partition is reported as one reading, not as a finding."
        ) if (k_at_ceiling or monotone_rising) else (
            f"Silhouette peaks at k={k} and falls away on both sides, so this k "
            "is a genuine optimum rather than an edge of the search range."
        ),
        "clusters": descriptions,
        "note": (
            "A cluster is a group of vocabulary, not the publisher's own "
            "topic. The dominant supplied topics are shown for comparison. "
            + (
                "" if strong else
                "Silhouette is low, so these clusters are weakly separated "
                "and should be read as broad themes, not tight groups. That "
                "is expected for 8.6-word headlines."
            )
        ),
    }


def sample_stability(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """Run the clustering twice with different seeds and compare.

    K-Means is initialisation-sensitive, so a single run reports one local
    optimum. If two seeds produce wildly different partitions, the "clusters"
    are not a property of the data. Agreement is measured as the fraction of
    documents whose cluster identity is most consistent after aligning the two
    labelings by their best-matching cluster.
    """
    cfg = config.get("clustering", {})
    k = int(cfg.get("chosen_k", 6))
    base_seed = int(cfg.get("seed", 0))
    size = int(cfg.get("sample_size", 60_000))
    if k <= 0 or k > int(cfg.get("k_max", 12)):
        return {"ran": False, "reason": f"chosen k={k} not in the searched range"}

    # The SAME documents, clustered twice with different K-Means seeds.
    #
    # Comparing two different random samples would confound the sampling
    # variation with the initialisation variation, and would answer neither.
    # Only the initialisation may vary, so the corpus and the feature space are
    # built once and the model is refit with two seeds.
    texts, _keys = sample_corpus(con, size, base_seed)
    if len(texts) < k * 2:
        return {"ran": False, "reason": f"only {len(texts)} documents available"}

    vectorizer = TfidfVectorizer(
        ngram_range=tuple(cfg.get("ngram_range", [1, 2])),
        min_df=int(cfg.get("min_df", 5)),
        max_features=int(cfg.get("max_features", 20_000)),
        sublinear_tf=bool(cfg.get("sublinear_tf", True)),
        strip_accents="unicode",
        # Same token pattern and stop list as the main run, or the two
        # partitions would live in different feature spaces and cluster
        # identity would not transfer between them.
        token_pattern=cfg.get("token_pattern", r"(?u)\b[a-zA-Z][a-zA-Z]+\b"),
        stop_words=cfg.get("stop_words", "english"),
    )
    tfidf = vectorizer.fit_transform(texts)
    n_components = min(
        int(cfg.get("svd_components", 100)),
        tfidf.shape[1] - 1, tfidf.shape[0] - 1,
    )
    reduced = TruncatedSVD(
        n_components=n_components, random_state=base_seed
    ).fit_transform(tfidf)

    try:
        first = KMeans(n_clusters=k, random_state=base_seed, n_init=10)
        labels_a = first.fit_predict(reduced)
        second = KMeans(n_clusters=k, random_state=base_seed + 1, n_init=10)
        labels_b = second.fit_predict(reduced)
    except Exception as exc:  # pragma: no cover - defensive
        return {"ran": False, "reason": str(exc)[:200]}

    # Align the two labelings through the contingency table, then count the
    # documents that landed in each one's best-matching cluster.
    agreement = 0
    n = len(labels_a)
    for cluster in range(k):
        members = labels_a == cluster
        if not members.any():
            continue
        other = labels_b[members]
        best = int(np.bincount(other, minlength=k).argmax())
        agreement += int((other == best).sum())
    ratio = agreement / n if n else 0.0
    return {
        "ran": True,
        "k": k,
        "documents": n,
        "seeds": [base_seed, base_seed + 1],
        "agreement_ratio": round(ratio, 4),
        "is_stable": ratio >= 0.7,
        "note": (
            "The same documents are clustered twice with different K-Means "
            "seeds, so only the initialisation varies. High agreement means "
            "the partition is a property of the data; low agreement means the "
            "clusters are an artefact of the starting points."
        ),
    }


def run_clustering(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    result = cluster_headlines(con, config)
    if result.get("ran"):
        # Record the chosen k so the stability check uses the same value.
        config.setdefault("clustering", {})["chosen_k"] = result["chosen_k"]
        result["stability"] = sample_stability(con, config)
    else:
        result["stability"] = {"ran": False, "reason": "clustering did not run"}
    return result
