"""Headline/market association (RQ6).

The question is whether business-headline behaviour relates to Nifty returns
or volatility. The word that matters is *relates*.

**This is correlation, and it is reported as correlation.** Nothing here
identifies an effect of news on markets, and the module will not use causal
language. A headline coefficient and a return coefficient computed over 1,235
trading days cannot separate news from the many other things moving the index
that day.

**Only trading days.** Headlines are published on 1,828 distinct days in the
window while the market trades on 1,235. A weekend has headlines and no close
price, so pairing them would invent data. The join goes through the market
table's own dates.

**Lags are reported, and zero is not privileged.** A lag-0 or lag-1
coefficient being the largest is exactly what one would expect from a shared
calendar effect and shared news flow, and is not evidence of leading
indicator behaviour.

**A coefficient is reported with a p-value and a count.** A correlation of
0.02 over 200 points is indistinguishable from noise, and a reader must be
able to see that without running anything.
"""

from __future__ import annotations

import math
from typing import Any

import duckdb
import numpy as np

from dwm.logging_utils import get

log = get("dwm.mining.market")


def paired_series(
    con: duckdb.DuckDBPyConnection, topic: str
) -> tuple[list[int], np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Daily headline and market series joined on trading days.

    Returns date_keys, headline count, mean sentiment, mean sensational score
    and the market return. Only dates where the market actually traded and at
    least one headline for the topic exists.
    """
    rows = con.execute(
        f"""
        WITH daily AS (
            SELECT
                c.date_key,
                sum(c.headline_count)         AS headline_count,
                sum(c.sum_sentiment_compound) AS sum_sentiment,
                sum(c.sum_sensational_score)  AS sum_sensational,
                sum(c.risk_signal_count)      AS risk_count
            FROM cube_day_topic c
            JOIN dim_topic t ON t.topic_key = c.topic_key
            WHERE t.topic_name = '{topic.replace(chr(39), chr(39) * 2)}'
            GROUP BY 1
        )
        SELECT
            m.date_key,
            m.trade_date,
            daily.headline_count,
            daily.sum_sentiment  / nullif(daily.headline_count, 0) AS mean_sentiment,
            daily.sum_sensational / nullif(daily.headline_count, 0) AS mean_sensational,
            daily.risk_count * 1.0 / nullif(daily.headline_count, 0) AS risk_rate,
            m.return_pct,
            m.volatility_20d
        FROM fact_market_daily m
        JOIN daily ON daily.date_key = m.date_key
        WHERE m.return_pct IS NOT NULL AND daily.headline_count > 0
        ORDER BY m.date_key
        """
    ).fetchall()

    # All five series must be built under ONE mask. Building sentiment with a
    # NULL filter and volume without would give arrays of different lengths,
    # and a lagged correlation between misaligned arrays is not a small
    # rounding issue, it is a different number that looks plausible.
    usable = [r for r in rows if r[3] is not None and r[4] is not None]
    keys = [r[0] for r in usable]
    dates = [str(r[1]) for r in usable]
    volume = np.array([float(r[2]) for r in usable])
    sentiment = np.array([float(r[3]) for r in usable])
    sensational = np.array([float(r[4]) for r in usable])
    returns = np.array([float(r[6]) for r in usable])
    return keys, volume, sentiment, sensational, returns, dates


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    xc, yc = x - x.mean(), y - y.mean()
    denom = math.sqrt(float((xc**2).sum()) * float((yc**2).sum()))
    if denom == 0:
        return float("nan")
    return float((xc * yc).sum() / denom)


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation, for when the relationship is monotone but not linear."""
    if len(x) < 3:
        return float("nan")
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return _pearson(rx, ry)


def _p_value(r: float, n: int) -> float | None:
    """Two-sided p-value for a correlation, from the t distribution.

    Uses the survival function of Student's t via scipy, because a
    coefficient with no significance test invites over-reading a number that
    is really noise.
    """
    if not np.isfinite(r) or n < 4 or abs(r) >= 1:
        return None
    try:
        from scipy import stats

        t = r * math.sqrt((n - 2) / (1 - r * r))
        return float(2 * stats.t.sf(abs(t), df=n - 2))
    except Exception:  # pragma: no cover - defensive
        return None


def lagged_correlation(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """Correlate each headline measure against the return at several lags.

    Lag L pairs a trading day with the return L trading days later, so a
    positive coefficient means the headline measure and the later return move
    together. It does not mean the headline preceded the return.
    """
    cfg = config.get("market", {})
    topic = str(cfg.get("topic", "Business"))
    lags = [int(value) for value in cfg.get("lags", [0, 1, 2, 3, 5])]
    min_obs = int(cfg.get("min_observations", 100))
    alpha = float(cfg.get("alpha", 0.05))

    keys, volume, sentiment, sensational, returns, dates = paired_series(con, topic)
    n = len(returns)

    result: dict[str, Any] = {
        "ran": True,
        "topic": topic,
        "trading_days_paired": n,
        "min_observations": min_obs,
        "sufficient_data": n >= min_obs,
        "alpha": alpha,
        "measures": {},
    }
    if n < min_obs:
        result["reason"] = (
            f"only {n} paired trading days, need {min_obs}; no correlation "
            "is reported"
        )
        return result

    # paired_series already applied one shared mask, so these four are
    # guaranteed the same length. A mismatch here would mean that contract was
    # broken upstream, and a correlation over misaligned arrays is a plausible
    # looking wrong number, so it is checked rather than assumed.
    lengths = {len(volume), len(sentiment), len(sensational), len(returns)}
    if len(lengths) != 1:
        result["reason"] = (
            f"series lengths disagree {sorted(lengths)}; refusing to correlate "
            "misaligned arrays"
        )
        return result

    measures = {
        "headline_volume": volume,
        "mean_sentiment": sentiment,
        "mean_sensational_score": sensational,
    }

    for name, series in measures.items():
        rows = []
        for lag in lags:
            if lag >= n - 3:
                rows.append(
                    {
                        "lag_trading_days": lag,
                        "n": 0,
                        "reason": (
                            f"lag {lag} needs at least 3 remaining points and "
                            f"only {n} are available"
                        ),
                    }
                )
                continue
            x, y = series[: n - lag], returns[lag:]
            r = _pearson(x, y)
            rho = _spearman(x, y)
            p = _p_value(r, len(x))
            rows.append(
                {
                    "lag_trading_days": lag,
                    "n": len(x),
                    "pearson_r": round(r, 5) if np.isfinite(r) else None,
                    "spearman_rho": round(rho, 5) if np.isfinite(rho) else None,
                    "p_value": round(p, 6) if p is not None else None,
                    "significant_at_alpha": (p is not None and p < alpha),
                }
            )
        significant = [r for r in rows if r.get("significant_at_alpha")]
        best = max(
            (r for r in rows if r.get("pearson_r") is not None),
            key=lambda r: abs(r["pearson_r"]),
            default=None,
        )
        result["measures"][name] = {
            "by_lag": rows,
            "strongest_lag": best,
            "any_lag_significant": bool(significant),
            "significant_lags": [r["lag_trading_days"] for r in significant],
        }
        log.info(
            "%s vs return: strongest |r|=%.4f at lag %s",
            name, abs(best["pearson_r"]) if best else 0.0,
            best["lag_trading_days"] if best else "-",
        )

    result["note"] = (
        "Association only. A correlation between a headline measure and a "
        "later return does not establish that the headline moved the market; "
        "both respond to other events on the same day."
    )
    # Fifteen lag tests at alpha 0.05 produce about 0.75 false positives by
    # chance, so a single significant lag is not a discovery. Counting the
    # tests and the expected count is what stops one p-value below 0.05 being
    # read as a finding.
    tests = sum(len(m["by_lag"]) for m in result["measures"].values())
    significant = [
        {"measure": name, "lag": r["lag_trading_days"], "p_value": r["p_value"],
         "pearson_r": r["pearson_r"]}
        for name, m in result["measures"].items()
        for r in m["by_lag"]
        if r.get("significant_at_alpha")
    ]
    result["significance_accounting"] = {
        "tests_run": tests,
        "alpha": alpha,
        "expected_false_positives": round(tests * alpha, 2),
        "significant_results": significant,
        "exceeds_chance": len(significant) > tests * alpha,
        "note": (
            "A significant result among many tests is expected. Count the "
            "significant results against the expected false positives before "
            "treating any of them as a finding."
        ),
    }
    return result


def volatility_association(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """The volatility half of RQ6, same caveats.

    Volatility is null until its 20-session window is full, so this uses fewer
    observations than the return analysis and says so.
    """
    cfg = config.get("market", {})
    topic = str(cfg.get("topic", "Business"))
    min_obs = int(cfg.get("min_observations", 100))
    alpha = float(cfg.get("alpha", 0.05))

    rows = con.execute(
        f"""
        WITH daily AS (
            SELECT
                c.date_key,
                sum(c.headline_count)         AS n,
                sum(c.sum_sentiment_compound) AS sum_sent,
                sum(c.sum_sensational_score)  AS sum_sens
            FROM cube_day_topic c
            JOIN dim_topic t ON t.topic_key = c.topic_key
            WHERE t.topic_name = '{topic.replace(chr(39), chr(39) * 2)}'
            GROUP BY 1
        )
        SELECT
            m.volatility_20d,
            daily.sum_sent  / nullif(daily.n, 0) AS mean_sentiment,
            daily.sum_sens  / nullif(daily.n, 0) AS mean_sensational,
            log(nullif(daily.n, 0))              AS log_volume
        FROM fact_market_daily m
        JOIN daily ON daily.date_key = m.date_key
        WHERE m.volatility_20d IS NOT NULL AND daily.n > 0
        """
    ).fetchall()
    n = len(rows)
    if n < min_obs:
        return {
            "ran": False,
            "reason": (
                f"only {n} trading days have a full 20-session volatility, "
                f"need {min_obs}"
            ),
            "observations": n,
        }

    volatility = np.array([float(r[0]) for r in rows])
    sentiment = np.array([float(r[1]) for r in rows])
    sensational = np.array([float(r[2]) for r in rows])
    log_headline_volume = np.array([float(r[3]) for r in rows])

    out = {}
    for name, series in (
        ("mean_sentiment", sentiment),
        ("mean_sensational_score", sensational),
        ("log_headline_volume", log_headline_volume),
    ):
        r = _pearson(series, volatility)
        p = _p_value(r, n)
        significant = p is not None and p < alpha
        out[name] = {
            "pearson_r": round(r, 5) if np.isfinite(r) else None,
            "p_value": round(p, 6) if p is not None else None,
            "significant_at_alpha": significant,
            "n": n,
            # r-squared is reported because a significant correlation is not
            # the same as a useful one, and the two are easy to conflate when
            # only the coefficient and the p-value are shown.
            "r_squared": round(r * r, 5) if np.isfinite(r) else None,
            "variance_explained_pct": round(r * r * 100, 3) if np.isfinite(r) else None,
        }

    strongest_name = max(
        out,
        key=lambda k: abs(out[k]["pearson_r"]) if out[k]["pearson_r"] is not None else -1,
        default=None,
    )
    strongest = (
        {**out[strongest_name], "name": strongest_name} if strongest_name else None
    )
    return {
        "ran": True,
        "topic": topic,
        "observations": n,
        "measures": out,
        "strongest": strongest,
        "any_significant": any(v["significant_at_alpha"] for v in out.values()),
        "note": (
            "Volatility is null until 20 sessions are available, so this uses "
            f"{n} of the trading days in the window. Association only. A "
            "significant coefficient here is not evidence of an effect: "
            "headline volume and market volatility both respond to the same "
            "underlying events, and nothing here separates their directions."
        ),
    }


def run_market(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    lagged = lagged_correlation(con, config)
    log.info(
        "market association: %s paired trading days", lagged.get("trading_days_paired")
    )
    return {
        "lagged_return_correlation": lagged,
        "volatility_association": volatility_association(con, config),
    }
