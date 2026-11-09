"""Local SQLite record of generated reports and their review state.

One row per client per month. The row holds the full report context as JSON,
so the dashboard can re-render a report without the client's source files.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vat_id        TEXT NOT NULL,
    business_name TEXT NOT NULL,
    month         TEXT NOT NULL,
    status        TEXT NOT NULL,
    context_json  TEXT NOT NULL,
    generated_at  TEXT NOT NULL,
    reviewed_at   TEXT,
    UNIQUE (vat_id, month)
)
"""


class ReportStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def upsert(self, context: dict) -> int:
        """Store a report. Regenerating a client's month replaces the row and
        clears its review: the accountant approved the previous numbers."""
        client = context["client"]
        with closing(self._connect()) as db, db:
            db.execute(
                """
                INSERT INTO reports (vat_id, business_name, month, status, context_json, generated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (vat_id, month) DO UPDATE SET
                    business_name = excluded.business_name,
                    status = excluded.status,
                    context_json = excluded.context_json,
                    generated_at = excluded.generated_at,
                    reviewed_at = NULL
                """,
                (
                    client["vat_id"], client["business_name"], context["month"], context["status"],
                    json.dumps(context, ensure_ascii=False), context["generated_at"],
                ),
            )
            row = db.execute(
                "SELECT id FROM reports WHERE vat_id = ? AND month = ?", (client["vat_id"], context["month"])
            ).fetchone()
            return row["id"]

    def list(self) -> list[dict]:
        """Newest month first, then by business name."""
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM reports ORDER BY month DESC, business_name, id").fetchall()
        return [self._summary(r) for r in rows]

    def get(self, report_id: int) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            return None
        record = self._summary(row)
        record["context"] = json.loads(row["context_json"])
        return record

    def mark_reviewed(self, report_id: int, when: datetime) -> bool:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE reports SET reviewed_at = ? WHERE id = ?",
                (when.strftime("%Y-%m-%dT%H:%M"), report_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict:
        context = json.loads(row["context_json"])
        return {
            "id": row["id"],
            "vat_id": row["vat_id"],
            "business_name": row["business_name"],
            "month": row["month"],
            "month_label": context["month_label"],
            "status": row["status"],
            "generated_at": row["generated_at"],
            "reviewed_at": row["reviewed_at"],
            "severity_counts": context["severity_counts"],
            "warning_count": len(context["warnings"]),
        }
