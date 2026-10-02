"""One deterministic sampler, shared by every mining module.

**Why this exists.** The first attempt used DuckDB's
`USING SAMPLE reservoir(N ROWS) REPEATABLE (seed)`, which looked right and was
not. Measured on the real corpus it returned **709 rows when 2000 were
requested**, and the number moved with the table's physical layout. The
sampling modules compensated by topping the draw up from the first headlines
by id, which converts a random sample into a chronological one — the
oldest slice of the corpus, which is exactly the biased sample that would
have quietly undermined every clustering and rule result.

Two findings pinned down the replacement:

  * `USING SAMPLE 2000 ROWS (bernoulli, seed)` is a parser error in DuckDB
    1.5.6. Bernoulli cannot be combined with a discrete row count, so the
    seedable discrete form is reservoir, and reservoir is what is unreliable.
  * `ORDER BY <hash> LIMIT n` returns exactly n rows and is byte-identical
    across separate processes.

So sampling is done by sorting on a seeded hash and taking the first n.

**Why DuckDB's `hash()` and not a hand-rolled one.** An arithmetic substitute
was tried first — `(id * 2654435761 + seed) % 4294967291` — and it is wrong in
a way that is easy to miss. Adding the salt *after* the multiply leaves the
relative order of two ids unchanged, because both terms shift by the same
constant. Two different seeds then returned byte-identical samples on a
ten-row fixture. A seed that does not change the draw is not a seed, so the
expression has to be genuinely non-linear in the id, which is what a real hash
is and what arithmetic on a prime modulus is not.

`hash()` is only guaranteed stable for a given engine version, and
`requirements.txt` pins that version, so a re-run reproduces exactly. If the
pin is ever moved, the samples move with it, and the results that depend on
sampling (clustering, association rules) would need re-running. The
deterministic unit tests check what actually matters: the same seed gives the
same draw, and different seeds give different draws.
"""

from __future__ import annotations

import duckdb


def hash_expr(seed: int, column: str) -> str:
    """A deterministic, seed-sensitive ordering expression for `column`.

    Returns SQL text rather than a bound parameter so the value is visible in
    the query, which matters when a result has to be traced back to the
    settings that produced it.
    """
    return f"hash({column}, {int(seed)})"


def sample_rows(
    con: duckdb.DuckDBPyConnection,
    select: str,
    *,
    source: str,
    where: str = "",
    size: int,
    seed: int,
    order_by: str = "headline_id",
    group_by: str = "",
) -> list[tuple]:
    """Exactly `size` rows, chosen without bias and reproducibly.

    `size` is honoured to the row. If the source holds fewer rows than that,
    every row is returned and the caller is told by the length.

    `order_by` must name a column with unique values within the result, so the
    tie-break is stable. `headline_id` and `statement_id` both qualify. When
    `group_by` is given, the ordering column must be the grouping key.

    `source` may carry its own JOINs, and may be aliased (`fact_headline f`).
    In that case qualify the column names in `order_by` too.
    """
    available = con.execute(
        f"SELECT count(*) FROM (SELECT 1 FROM {source} {where} {group_by}) t"
    ).fetchone()[0]
    if not available:
        return []
    take = min(int(size), int(available))

    rows = con.execute(
        f"""
        SELECT {select}
        FROM {source}
        {where}
        {group_by}
        ORDER BY {hash_expr(seed, order_by)}, {order_by}
        LIMIT {take}
        """
    ).fetchall()
    if len(rows) != take:
        raise RuntimeError(
            f"sampler returned {len(rows)} of {take} requested rows from {source}"
        )
    return rows
