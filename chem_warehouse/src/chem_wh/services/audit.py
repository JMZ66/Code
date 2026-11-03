from __future__ import annotations

import json
from typing import Any, Optional

from chem_wh.db.database import Database
from chem_wh.utils.timeutil import now_iso


class AuditService:
    def __init__(self, db: Database):
        self.db = db

    def log(
        self,
        user_id: Optional[int],
        action: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        detail: Any = None,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO audit_logs(user_id, action, entity_type, entity_id, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                action,
                entity_type,
                entity_id,
                json.dumps(detail, ensure_ascii=False) if detail is not None else None,
                now_iso(),
            ),
        )
        return int(cur.lastrowid)

    def list_recent(self, limit: int = 100) -> list:
        return self.db.fetchall(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        )
