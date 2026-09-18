"""One-shot data extractor: pull real S5 profiles + S6 JD snapshots from a clone DB.

Reads CONN_URL (the per-run clone URL), finds the newest live-extract and
live-jd users, and writes:
    tests/live/chain/profile.json        - S5 json_resume (latest profile)
    tests/live/chain/jd_1.json           - S6 payload (first posting)
    tests/live/chain/jd_2.json           - S6 payload (second posting)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

CHAIN_DIR = Path(__file__).resolve().parent / "chain"


def main() -> None:
    conn_url = os.environ["CONN_URL"]
    with psycopg.connect(conn_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT p.json_resume
                FROM profiles p
                JOIN users u ON u.id = p.user_id
                WHERE u.email LIKE 'live-extract-%'
                ORDER BY p.created_at DESC
                LIMIT 1
                """
        )
        row = cur.fetchone()
        if row is None:
            raise SystemExit("no S5 live-extract profile found")
        profile_payload = row[0]

        cur.execute(
            """
                SELECT s.payload
                FROM job_snapshots s
                JOIN jobs j ON j.current_snapshot_id = s.id
                JOIN users u ON u.id = j.user_id
                WHERE u.email LIKE 'live-jd-%'
                ORDER BY s.captured_at ASC
                """
        )
        jd_payloads = [r[0] for r in cur.fetchall()]
        if not jd_payloads:
            raise SystemExit("no S6 live-jd snapshots found")

    CHAIN_DIR.mkdir(parents=True, exist_ok=True)
    (CHAIN_DIR / "profile.json").write_text(json.dumps(profile_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for i, payload in enumerate(jd_payloads[:2], start=1):
        (CHAIN_DIR / f"jd_{i}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {CHAIN_DIR}/profile.json + {len(jd_payloads[:2])} jd files")


if __name__ == "__main__":
    main()
