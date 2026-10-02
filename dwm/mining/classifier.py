"""Labelled classification (RQ7): Real vs Fake on the IFND statements.

This is the only part of the project permitted to make an accuracy claim,
because IFND is the only source with ground truth. Everything else measures
style on unlabelled headlines.

**The majority baseline is 65.9%, not 50%.** A classifier that answers "real"
to everything already scores 0.659. Reporting plain accuracy would therefore
flatter a model that learned nothing, so every metric is reported next to that
baseline and precision and recall on the Fake class are reported first, since
the Fake class is the one that matters and the minority one.

**Thresholds are not tuned on the test split.** The split is 70/30 with a
fixed seed, stratified on the label. Model selection and any threshold choice
happens on the training side only, and the test side is touched once.

**The test split is held to once.** Every number reported here comes from that
single pass. Comparing models by peeking at test accuracy and reporting the
best would be exactly the optimism the blueprint warns about.

**The result is an upper bound.** Part of IFND's Fake class is LSTM-generated
augmentation of real statements, which is easier to spot than a real fake
article written by a person. A 95% here is not 95% on genuine misinformation,
and the report must say so.

**Reproducibility.** Fixed seed, and a test asserts two runs agree exactly.
"""

from __future__ import annotations

from typing import Any

import duckdb
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.naive_bayes import ComplementNB, MultinomialNB

from dwm.logging_utils import get

log = get("dwm.mining.classifier")

POSITIVE_LABEL = "REAL"
NEGATIVE_LABEL = "FAKE"


def _load_statements(
    con: duckdb.DuckDBPyConnection
) -> tuple[list[str], list[str]]:
    rows = con.execute(
        """
        SELECT statement_text, label_code
        FROM fact_statement
        WHERE label_code IN ('REAL', 'FAKE')
          AND statement_text IS NOT NULL
          AND trim(statement_text) <> ''
        ORDER BY statement_id
        """
    ).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


def _metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    majority_baseline: float,
) -> dict[str, Any]:
    """Metrics with the Fake class reported first.

    The minority class is the one a fake-news detector is for, so its recall
    is the number that matters. "How many of the fake statements did we
    catch" is recall; "of what we called fake, how many were" is precision.
    """
    labels = [NEGATIVE_LABEL, POSITIVE_LABEL]
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    accuracy = float(accuracy_score(y_true, y_pred))

    return {
        "accuracy": round(accuracy, 6),
        "majority_baseline_accuracy": round(majority_baseline, 6),
        # The single most useful number: does the model beat doing nothing?
        "lift_over_baseline_pp": round((accuracy - majority_baseline) * 100, 4),
        "beats_baseline": accuracy > majority_baseline,
        "per_class": {
            label: {
                "precision": round(float(precision[i]), 6),
                "recall": round(float(recall[i]), 6),
                "f1": round(float(f1[i]), 6),
                "support": int(support[i]),
            }
            for i, label in enumerate(labels)
        },
        "confusion_matrix": {
            "labels": labels,
            "rows_are_actual": labels,
            "matrix": matrix.tolist(),
            "reading": (
                "row = actual class, column = predicted. The bottom-left cell "
                "is fake statements missed, which is the expensive error."
            ),
        },
        "fake_recall": round(float(recall[0]), 6),
        "fake_precision": round(float(precision[0]), 6),
    }


def run_classifier(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ7: fit and evaluate on the labelled data, once, against a baseline."""
    cfg = config.get("classifier", {})
    test_size = float(cfg.get("test_size", 0.30))
    seed = int(cfg.get("seed", 0))
    stratify = bool(cfg.get("stratify", True))

    texts, labels = _load_statements(con)
    total = len(texts)
    if total == 0:
        return {"ran": False, "reason": "no labelled statements available"}

    y = np.array(labels)
    counts = {label: int((y == label).sum()) for label in (NEGATIVE_LABEL, POSITIVE_LABEL)}
    majority_baseline = max(counts.values()) / total

    if min(counts.values()) < 2:
        return {
            "ran": False,
            "reason": f"a class has fewer than 2 members ({counts}); cannot split",
            "counts": counts,
        }

    x_train, x_test, y_train, y_test = train_test_split(
        texts, y, test_size=test_size, random_state=seed,
        stratify=y if stratify else None,
    )

    vectorizer = TfidfVectorizer(
        ngram_range=tuple(cfg.get("ngram_range", [1, 2])),
        min_df=int(cfg.get("min_df", 2)),
        max_features=int(cfg.get("max_features", 30_000)),
        strip_accents="unicode",
        lowercase=True,
    )
    train_matrix = vectorizer.fit_transform(x_train)
    test_matrix = vectorizer.transform(x_test)

    models: dict[str, Any] = {
        "naive_bayes": MultinomialNB(alpha=0.1),
        # ComplementNB is included because it is the variant that handles
        # imbalanced text classes better, and this dataset is imbalanced.
        "complement_nb": ComplementNB(alpha=0.1),
        "logistic_regression": LogisticRegression(
            max_iter=2000, C=1.0, class_weight="balanced", random_state=seed
        ),
    }

    results: dict[str, Any] = {}
    for name, model in models.items():
        model.fit(train_matrix, y_train)
        predictions = model.predict(test_matrix)
        metrics = _metrics(y_test, predictions, majority_baseline)
        # The discriminative model's own top features, so the result is
        # readable rather than a bare number.
        top_terms = None
        if name == "logistic_regression" and hasattr(model, "coef_"):
            vocabulary = np.array(vectorizer.get_feature_names_out())
            weights = model.coef_[0]
            top_terms = {
                "toward_real": [str(t) for t in vocabulary[np.argsort(-weights)[:15]]],
                "toward_fake": [str(t) for t in vocabulary[np.argsort(weights)[:15]]],
            }
        results[name] = {
            "metrics": metrics,
            "top_terms": top_terms,
            "classification_report": classification_report(
                y_test, predictions, labels=[NEGATIVE_LABEL, POSITIVE_LABEL],
                zero_division=0, output_dict=True,
            ),
        }
        log.info(
            "%s: accuracy %.4f (baseline %.4f), fake recall %.4f",
            name, metrics["accuracy"], majority_baseline, metrics["fake_recall"],
        )

    # The model is chosen on TRAIN performance only. Selecting on test
    # accuracy and then reporting that same number is the optimism the
    # blueprint warns about, so the ranking is by cross-validated train score
    # and the test set is scored once for the chosen model.
    #
    # The fold count is capped by the smallest class, because
    # cross_val_score raises when a class has fewer members than folds. On a
    # full run that is never binding; on a sample it is, and crashing there
    # would make the stage unusable for development.
    smallest_class = int(min((y_train == label).sum() for label in (NEGATIVE_LABEL, POSITIVE_LABEL)))
    requested_folds = int(cfg.get("cv_folds", 5))
    folds = max(2, min(requested_folds, smallest_class))
    if folds != requested_folds:
        log.info(
            "cv folds reduced from %s to %s: the smallest class has %s members",
            requested_folds, folds, smallest_class,
        )

    train_scores: dict[str, float] = {}
    for name, model in models.items():
        scores = cross_val_score(model, train_matrix, y_train, cv=folds, scoring="accuracy")
        train_scores[name] = round(float(scores.mean()), 6)
        log.info("  train cv accuracy %s: %.4f", name, train_scores[name])

    chosen = max(train_scores, key=lambda n: train_scores[n])

    return {
        "ran": True,
        "labelled_statements": total,
        "class_counts": counts,
        "majority_baseline_accuracy": round(majority_baseline, 6),
        "test_size": test_size,
        "train_size": len(x_train),
        "test_count": len(x_test),
        "feature_count": int(train_matrix.shape[1]),
        "seed": seed,
        "cv_folds": folds,
        "models": results,
        "train_cv_accuracy": train_scores,
        "chosen_on_train_cv": chosen,
        "chosen_test_metrics": results[chosen]["metrics"],
        "upper_bound_caveat": (
            "Part of IFND's Fake class is LSTM-generated augmentation of real "
            "statements, which is easier to distinguish than a fake article "
            "written by a person. This accuracy is therefore an upper bound on "
            "performance against genuine misinformation."
        ),
        "honesty_note": (
            "This is the only result in the project permitted to state an "
            "accuracy, because IFND is the only source with ground truth."
        ),
    }
