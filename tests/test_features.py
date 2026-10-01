"""Feature stage tests: scoring semantics, vocabulary, and the fact gate.

The runner tests force the serial path (`use_multiprocessing: false`) so they
are deterministic and do not spawn processes. The serial and parallel paths
share the same scoring function, so the numbers are identical by construction;
`test_serial_and_parallel_agree` checks that on a small corpus.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from dwm.config import Settings, load_datasets_config
from dwm.etl import run_etl
from dwm.features.lexicons import STOPWORDS, SUPERLATIVES, URGENCY
from dwm.features.runner import (
    FEATURE_COLUMNS,
    _init_worker,
    _score_chunk,
    _split,
    build_vocabulary,
    load_features_config,
    run_features,
)
from dwm.features.scoring import TextScorer, eligible_terms
from dwm.ingest.staging import stage_dataset

TOI_ROWS = [
    "publish_date,headline_category,headline_text",
    "20160101,sports.cricket,India win the final over comfortably",
    "20160102,politics.parliament,Parliament passes the new bill after debate",
    "20160103,business.markets,Sensex gains as profits beat expectations",
    "20160104,city.mumbai,Mumbai rains bring relief after a long dry spell",
    "20160105,technology.gadgets,New phone launch promises faster charging",
    "20160106,sports.cricket,SHOCKING! India CRUSHED in final OVER!!!",
    "20160107,business.markets,Sensex gains as profits beat expectations again",
    "20160108,entertainment.bollywood,Actor says film is his best work yet",
    "20160109,world.diplomacy,Leaders meet in Delhi for trade talks",
    "20160110,health.health-news,Hospital reports a rise in dengue cases",
]

IFND_ROWS = [
    "id,Statement,Image,Web,Category,Date,Label",
    '1,"A calm statement about policy",a.jpg,SITE,POLITICS,Oct-20,TRUE',
    '2,"SHOCKING government admits massive failure!!",b.jpg,SITE,GOVERNMENT,Oct-20,Fake',
    '3,"Third statement with a neutral tone",c.jpg,SITE,VIOLENCE,Nov 2020,FALSE',
]

NIFTY_ROWS = [
    "Date,Open,High,Low,Close,Volume,Turnover",
    "04-01-2016,100,110,95,105,1000,10.5",
    "05-01-2016,105,115,100,112,1100,11.5",
    "06-01-2016,112,120,108,118,1200,12.5",
]


def _write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def serial_config() -> dict:
    cfg = copy.deepcopy(load_features_config())
    cfg["runtime"]["use_multiprocessing"] = False
    # A tiny vocabulary and chunk so the fixture corpus produces a few.
    cfg["keywords"]["min_doc_frequency"] = 1
    cfg["runtime"]["chunk_size"] = 4
    return cfg


@pytest.fixture
def warehouse(tmp_path: Path, settings: Settings, serial_config, monkeypatch):
    """Clean tables plus features and facts, all on a small fixture."""
    import dwm.features.runner as runner

    monkeypatch.setattr(runner, "load_features_config", lambda *a, **k: serial_config)

    specs = load_datasets_config()
    from dwm.db import connect

    con = connect(settings)
    paths = {
        "toi": _write(tmp_path, "india-news-headlines.csv", TOI_ROWS),
        "ifnd": _write(tmp_path, "IFND.csv", IFND_ROWS),
        "nifty": _write(tmp_path, "nifty50.csv", NIFTY_ROWS),
    }
    for code, path in paths.items():
        stage_dataset(con, specs[code], path, settings=settings)
    run_etl(settings, con=con)
    run_features(settings, con=con)
    yield con, settings
    con.close()


# ---------------------------------------------------------------------------
# the scorer itself
# ---------------------------------------------------------------------------


def test_sentiment_signs_are_sensible() -> None:
    s = TextScorer()
    pos = s.measure("Sensex gains as profits beat expectations and investors cheer")
    neg = s.measure("Crisis deepens as disaster ruins lives and economy collapses")
    assert pos.sentiment_compound > 0
    assert neg.sentiment_compound < 0
    assert s.sentiment_flag(pos.sentiment_compound) == "positive"
    assert s.sentiment_flag(neg.sentiment_compound) == "negative"
    assert s.sentiment_flag(0.0) == "neutral"


def test_vader_neutral_on_a_factual_headline() -> None:
    s = TextScorer()
    m = s.measure("Parliament passes the new bill after debate")
    # Factual political reporting should not read as strongly polarised.
    assert -0.6 < m.sentiment_compound < 0.6


def test_all_caps_and_punctuation_raise_the_sensationalism_score() -> None:
    s = TextScorer()
    calm = s.measure("Sensex gains as profits beat expectations")
    loud = s.measure("SHOCKING! Sensex CRUSHED, investors DEVASTATED!!!")
    assert loud.caps_token_count > calm.caps_token_count
    assert loud.exclamation_count == 4
    assert loud.caps_token_ratio > calm.caps_token_ratio
    assert loud.sensational_score > calm.sensational_score
    assert loud.is_sensational is True
    assert calm.is_sensational is False


def test_caps_ratio_ignores_short_tokens() -> None:
    s = TextScorer()
    # min_caps_length is 3, so "A" and "PM" are too short to count, but
    # "THE" and "DAY" are exactly 3 and do. All five tokens are alphabetic,
    # so the denominator is 5.
    m = s.measure("A PM OF THE DAY")
    assert m.caps_token_count == 2
    assert m.caps_token_ratio == pytest.approx(2 / 5)


def test_superlative_and_urgency_lexicons_are_disjoint() -> None:
    """A word in both lists would inflate two sub-signals from one token."""
    assert not (SUPERLATIVES & URGENCY)
    # "exclusive" is an attention signal, not an extreme claim.
    assert "exclusive" in URGENCY
    assert "exclusive" not in SUPERLATIVES


def test_caps_ratio_denominator_ignores_digits() -> None:
    s = TextScorer()
    m = s.measure("RBI 2026 CRASH")
    # tokens: rbi, 2026, crash -> alpha tokens = 2, caps tokens = 2
    assert m.caps_token_ratio == pytest.approx(1.0)


def test_superlative_and_urgency_lexicons_fire_independently() -> None:
    s = TextScorer()
    # "failure" is deliberately not in the urgency list, so the two
    # sub-signals are cleanly separated on these two texts.
    sup = s.measure("This is the biggest and worst failure of all time")
    urg = s.measure("BREAKING exclusive alert issued right now")
    assert sup.superlative_count == 2
    assert sup.urgency_count == 0
    assert urg.urgency_count == 3
    assert urg.superlative_count == 0


def test_score_is_bounded_and_weights_sum_to_one() -> None:
    cfg = load_features_config()
    weights = cfg["sensationalism"]["weights"]
    assert sum(weights.values()) == pytest.approx(1.0)
    s = TextScorer(cfg)
    extreme = s.measure("BREAKING! SHOCKING! " + " ".join(sorted(SUPERLATIVES)) + "!!! ???")
    assert 0.0 <= extreme.sensational_score <= 1.0


def test_threshold_is_configurable() -> None:
    cfg = load_features_config()
    low = copy.deepcopy(cfg)
    low["sensationalism"]["threshold"] = 0.0
    assert TextScorer(low).measure("Anything at all").is_sensational is True
    high = copy.deepcopy(cfg)
    high["sensationalism"]["threshold"] = 1.01
    assert TextScorer(high).measure("SHOCKING!!! BREAKING!!").is_sensational is False


def test_risk_signal_tracks_sensationalism_only() -> None:
    """No classifier signal exists for TOI, so the two flags are the same."""
    s = TextScorer()
    m = s.measure("SHOCKING!!! BREAKING!!!")
    assert m.is_risk_signal == m.is_sensational


def test_empty_and_none_text_do_not_raise() -> None:
    s = TextScorer()
    for value in (None, "", "   ", "!!!", "12345"):
        m = s.measure(value)
        assert 0.0 <= m.sensational_score <= 1.0
        assert m.sentiment_compound == 0.0


def test_token_and_character_counts() -> None:
    s = TextScorer()
    m = s.measure("one two three")
    assert m.char_count == 13
    assert m.token_count == 3
    assert m.unique_token_count == 3
    m = s.measure("one two two")
    assert m.unique_token_count == 2


# ---------------------------------------------------------------------------
# vocabulary and keywords
# ---------------------------------------------------------------------------


def test_eligible_terms_drops_stopwords_and_short_tokens() -> None:
    freq = eligible_terms(
        ["the quick brown fox a of quick SHOCKING 12 ab"], min_length=3
    )
    assert "quick" in freq
    assert "brown" in freq
    assert "shocking" in freq
    assert "the" not in freq
    assert "a" not in freq
    assert "of" not in freq
    assert "ab" not in freq
    assert "12" not in freq
    assert "the" in STOPWORDS
    assert "shocking" in SUPERLATIVES
    assert "breaking" in URGENCY


def test_keywords_are_capped_and_ordered() -> None:
    s = TextScorer()
    vocab = {f"t{i}": i for i in range(1, 11)}
    vocab["india"] = 3
    vocab["wins"] = 7
    hits = s.keywords("india wins something else entirely", vocab, limit=2)
    assert hits == [3, 7]
    assert len(s.keywords("india wins other", vocab, limit=1)) == 1


def test_keywords_on_unknown_text_is_empty() -> None:
    s = TextScorer()
    assert s.keywords("nothing matches", {"zzz": 1}, 8) == []
    assert s.keywords(None, {"a": 1}, 8) == []
    assert s.keywords("india", {}, 8) == []


def test_vocabulary_is_deterministic(warehouse) -> None:
    con, _ = warehouse
    cfg = load_features_config()
    a, _ = build_vocabulary(con, cfg)
    b, _ = build_vocabulary(con, cfg)
    assert a == b


def test_vocabulary_respects_the_cap(warehouse) -> None:
    con, _ = warehouse
    cfg = copy.deepcopy(load_features_config())
    cfg["keywords"]["vocabulary_size"] = 5
    # The fixture corpus is 10 headlines, so the production floor of 20
    # documents would leave the vocabulary empty.
    cfg["keywords"]["min_doc_frequency"] = 1
    vocab, stats = build_vocabulary(con, cfg)
    assert len(vocab) == 5
    assert stats["vocabulary_size"] == 5


def test_production_floor_rejects_a_small_corpus(warehouse) -> None:
    """The default min_doc_frequency of 20 keeps a tiny corpus empty."""
    con, _ = warehouse
    vocab, stats = build_vocabulary(con, load_features_config())
    assert vocab == {}
    assert stats["vocabulary_size"] == 0
    assert stats["terms_above_min_df"] == 0


# ---------------------------------------------------------------------------
# worker plumbing
# ---------------------------------------------------------------------------


def test_split_preserves_every_row() -> None:
    chunk = [(i, f"t{i}") for i in range(10)]
    parts = _split(chunk, 3)
    assert sum(len(p) for p in parts) == 10
    assert [k for p in parts for k, _ in p] == list(range(10))


def test_split_handles_more_workers_than_rows() -> None:
    chunk = [(1, "a"), (2, "b")]
    parts = _split(chunk, 8)
    assert sum(len(p) for p in parts) == 2


def test_chunks_cover_every_row_exactly_once(warehouse) -> None:
    """Regression: keyset pagination must not skip or repeat a row."""
    from dwm.features.runner import _chunks

    con, _ = warehouse
    for size in (1, 2, 3, 7, 100):
        keys = [
            k
            for chunk in _chunks(
                con, "SELECT headline_id, headline_text FROM cln_headline",
                size, "headline_id",
            )
            for k, _ in chunk
        ]
        expected = [
            r[0]
            for r in con.execute(
                "SELECT headline_id FROM cln_headline ORDER BY headline_id"
            ).fetchall()
        ]
        assert keys == expected, f"pagination wrong at chunk_size={size}"
        assert len(set(keys)) == len(keys)


def test_chunks_can_resume_from_a_cursor(warehouse) -> None:
    from dwm.features.runner import _chunks

    con, _ = warehouse
    sql = "SELECT headline_id, headline_text FROM cln_headline"
    everything = [
        k
        for chunk in _chunks(con, sql, 3, "headline_id")
        for k, _ in chunk
    ]
    # Resume after the fourth key and confirm the rest arrive exactly once.
    after = [
        k
        for chunk in _chunks(con, sql, 3, "headline_id", start_after=4)
        for k, _ in chunk
    ]
    assert after == [k for k in everything if k > 4]


def test_resume_point_reads_a_partial_table(con) -> None:
    from dwm.features.runner import _resume_point

    # A fresh connection has no feature table at all.
    assert _resume_point(con, "feat_nonexistent") == -1

    con.execute("CREATE TABLE rp (source_key BIGINT)")
    assert _resume_point(con, "rp") == -1  # exists but empty

    con.executemany("INSERT INTO rp VALUES (?)", [(1,), (2,), (3,)])
    assert _resume_point(con, "rp") == 3


def test_fingerprint_ignores_performance_settings() -> None:
    """Chunk size must not invalidate two minutes of scoring."""
    from dwm.features.runner import feature_fingerprint

    base = load_features_config()
    faster = copy.deepcopy(base)
    faster["runtime"]["chunk_size"] = 5
    faster["runtime"]["workers"] = 1
    assert feature_fingerprint(base) == feature_fingerprint(faster)


def test_fingerprint_tracks_measure_definitions() -> None:
    from dwm.features.runner import feature_fingerprint

    base = load_features_config()
    for path, value in (
        (("sensationalism", "threshold"), 0.99),
        (("sensationalism", "weights", "caps_ratio"), 0.9),
        (("sentiment", "negative_compound"), -0.9),
        (("keywords", "vocabulary_size"), 50),
        (("keywords", "max_per_headline"), 2),
    ):
        changed = copy.deepcopy(base)
        node = changed
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        assert feature_fingerprint(base) != feature_fingerprint(changed), path


def test_changed_threshold_discards_cached_features(warehouse, serial_config) -> None:
    """Regression risk: a threshold edit must not leave stale flags behind."""
    from dwm.features.runner import _check_fingerprint

    con, _ = warehouse
    # Must be the config the fixture actually built with, or the fingerprints
    # would differ for the wrong reason. The fixture already recorded it, so
    # there is a valid cache to reuse.
    cfg = serial_config
    before = con.execute("SELECT count(*) FROM feat_headline").fetchone()[0]
    assert before > 0

    # Unchanged config: the cache is reused and nothing is dropped.
    assert _check_fingerprint(con, cfg) is True
    assert con.execute("SELECT count(*) FROM feat_headline").fetchone()[0] == before

    # Changed threshold: the stale tables are dropped outright, not emptied.
    # Leaving an empty table behind would be worse, because the next stage
    # would then see a present-but-wrong feature table.
    changed = copy.deepcopy(cfg)
    changed["sensationalism"]["threshold"] = 0.9
    assert _check_fingerprint(con, changed) is False
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    for gone in ("feat_headline", "dim_keyword", "bridge_headline_keyword"):
        assert gone not in present, f"{gone} should have been discarded"
    # And it is now the current fingerprint, so a third call is a no-op.
    assert _check_fingerprint(con, changed) is True


def test_uncertified_features_are_discarded(warehouse, serial_config) -> None:
    """Features with no recorded fingerprint are treated as stale.

    Otherwise a warehouse built before fingerprinting existed would be trusted
    forever, and a threshold edit would leave the old flags in place.
    """
    from dwm.features.runner import _check_fingerprint

    con, _ = warehouse
    assert con.execute("SELECT count(*) FROM feat_headline").fetchone()[0] > 0
    con.execute("DELETE FROM feat_config")

    assert _check_fingerprint(con, serial_config) is False
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    assert "feat_headline" not in present
    # The fingerprint is now recorded, so the cache is trusted next time.
    assert _check_fingerprint(con, serial_config) is True


def test_rerun_is_idempotent(warehouse) -> None:
    """Re-running features must not duplicate rows.

    The stage is resumable, so a second run has to detect the work already
    done and leave the table the same size rather than doubling it.
    """
    from dwm.features.runner import _compute_features, _resume_point

    con, settings = warehouse
    before = con.execute("SELECT count(*) FROM feat_headline").fetchone()[0]
    source_before = con.execute("SELECT count(*) FROM cln_headline").fetchone()[0]
    assert before == source_before

    cfg = load_features_config()
    cfg["runtime"]["use_multiprocessing"] = False
    cfg["keywords"]["min_doc_frequency"] = 1
    resume = _resume_point(con, "feat_headline")
    assert resume >= 0
    _compute_features(
        con, source="cln_headline", key_column="headline_id",
        text_column="headline_text", target="feat_headline",
        config=cfg, vocabulary={}, run_id="t", dataset_code="toi",
        resume=resume,
    )
    after = con.execute("SELECT count(*) FROM feat_headline").fetchone()[0]
    assert after == before


def test_score_chunk_row_width_matches_columns() -> None:
    _init_worker(load_features_config(), {}, 8)
    out = _score_chunk([(1, "hello world")])
    assert len(out) == 1
    row = out[0]
    # source_key + one value per FEATURE_COLUMNS + the keyword list
    assert len(row) == 2 + len(FEATURE_COLUMNS)


def test_score_chunk_is_pure() -> None:
    _init_worker(load_features_config(), {"india": 1}, 8)
    a = _score_chunk([(1, "india wins")])
    b = _score_chunk([(1, "india wins")])
    assert a == b
