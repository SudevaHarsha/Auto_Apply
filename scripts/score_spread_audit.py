"""Score-spread / calibration audit (upgrade 4).

Reads the rubric_evidence rows already stored by the scorer and prints, per
category, the distribution of score/max so operators can spot:

- central-tendency collapse (everything at exactly 0.5 -> coarse anchors / hedging)
- band range never used (scores clustered at {mid, max})
- evidence_strength sanity (3s only when the JD wording was actually matched)

Usage (must run as the DB admin / owner role - RLS hides other users' rows
from app_user; MIGRATE_DATABASE_URL or --admin-url must point at the superuser):

    python scripts/score_spread_audit.py [--admin-url postgresql://autoapply:autoapply@localhost:5435/autoapply]

Output is tabulated per category_key with count, mean ratio, ratio std-dev,
and the bucket population for {0, 0-0.5, 0.5, 0.5-1, 1}.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import selectors
from collections import defaultdict

import psycopg


def _url(argv: argparse.Namespace) -> str:
    return argv.admin_url or os.getenv("MIGRATE_DATABASE_URL") or os.getenv("DATABASE_URL", "")


async def _run(admin_url: str) -> None:
    if not admin_url:
        raise SystemExit("no admin/owner DB url provided (--admin-url or MIGRATE_DATABASE_URL/DATABASE_URL)")
    conn = await psycopg.AsyncConnection.connect(admin_url)
    try:
        rows = await (
            await conn.execute(
                """SELECT metadata->>'category_key' AS key,
                          metadata->>'label'       AS label,
                          metadata->>'max'         AS max,
                          metadata->>'score'       AS score,
                          metadata->>'evidence_strength' AS strength,
                          metadata->>'model'       AS model,
                          metadata->>'job_id'      AS job_id,
                          updated_at,
                          created_at
                   FROM evidence
                   WHERE type = 'rubric_evidence'
                   ORDER BY created_at DESC"""
            )
        ).fetchall()
    finally:
        await conn.close()

    if not rows:
        print("no rubric_evidence rows found")
        return

    buckets = defaultdict(lambda: {"n": 0, "ratios": [], "strengths": defaultdict(int), "models": defaultdict(int)})
    for row in rows:
        key = row[0]
        max_v = row[2]
        score = row[3]
        strength = row[5]
        model = row[6]
        stat = buckets[key]
        try:
            ratio = float(score) / float(max_v) if float(max_v) else 0.0
        except (TypeError, ValueError):
            ratio = 0.0
        stat["n"] += 1
        stat["ratios"].append(ratio)
        stat["strengths"][strength if strength is not None else "?"] += 1
        stat["models"][model or "?"] += 1

    header = f"{'category_key':24} {'n':>4} {'mean':>6} {'std':>6}   bucket population (0 | <0.5 | =0.5 | >0.5 | 1)"
    print(header)
    print("-" * len(header))
    for key in sorted(buckets):
        stat = buckets[key]
        ratios = stat["ratios"]
        mean = sum(ratios) / len(ratios)
        variance = sum((r - mean) ** 2 for r in ratios) / len(ratios)
        pop = [
            sum(1 for r in ratios if r == 0.0),
            sum(1 for r in ratios if 0.0 < r < 0.5),
            sum(1 for r in ratios if r == 0.5),
            sum(1 for r in ratios if 0.5 < r < 1.0),
            sum(1 for r in ratios if r == 1.0),
        ]
        flags = []
        if all(r == 0.5 for r in ratios):
            flags.append("PURE-0.5 (central-tendency collapse)")
        flags.append(f"strengths={dict(stat['strengths'])}")
        flags.append(f"models={dict(stat['models'])}")
        print(f"{key:24} {stat['n']:>4} {mean:6.2f} {variance**0.5:6.2f}   {pop}  {' '.join(flags)}")

    print("-" * len(header))
    print("Buckets: [0.0, (0,0.5), =0.5, (0.5,1), 1.0]  — a category at all-0.5 is central-tendency collapse.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-url", default=None, help="owner/superuser DB url (bypasses RLS)")
    args = parser.parse_args()
    asyncio.run(_run(_url(args)), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))


if __name__ == "__main__":
    main()
