from __future__ import annotations

import json
from typing import Any, Optional

from chem_wh.db.database import Database
from chem_wh.services.exceptions import PermissionError
from chem_wh.utils.integrity import GENESIS_HASH, chain_hash
from chem_wh.utils.timeutil import now_iso


class AuditService:
    def __init__(self, db: Database):
        self.db = db

    def _last_hash(self, conn=None) -> str:
        c = conn or self.db.conn
        row = c.execute(
            "SELECT content_hash FROM audit_logs WHERE content_hash IS NOT NULL "
            "AND content_hash <> '' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return GENESIS_HASH
        return row[0]

    def log(
        self,
        user_id: Optional[int],
        action: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        detail: Any = None,
        *,
        conn=None,
        commit: bool = True,
    ) -> int:
        """Write audit row. If conn provided, use caller's transaction (no auto-commit)."""
        created_at = now_iso()
        detail_json = (
            json.dumps(detail, ensure_ascii=False) if detail is not None else None
        )
        own = conn is None
        c = conn or self.db.conn
        if own:
            c.execute("BEGIN")
        try:
            prev = self._last_hash(c)
            payload = {
                "user_id": user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "detail_json": detail_json,
                "created_at": created_at,
            }
            content_hash = chain_hash(prev, payload)
            cur = c.execute(
                """
                INSERT INTO audit_logs(
                    user_id, action, entity_type, entity_id, detail_json,
                    content_hash, prev_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    action,
                    entity_type,
                    entity_id,
                    detail_json,
                    content_hash,
                    prev,
                    created_at,
                ),
            )
            if own and commit:
                c.commit()
            return int(cur.lastrowid)
        except Exception:
            if own:
                c.rollback()
            raise

    def delete_log(self, *_args, **_kwargs) -> None:
        raise PermissionError("审计日志只允许追加，界面和接口都不能删除或修改")

    def list_recent(self, limit: int = 100) -> list:
        return self.db.fetchall(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        )

    def verify_chain(self, limit: int = 10_000) -> tuple[bool, str]:
        rows = self.db.fetchall(
            "SELECT * FROM audit_logs ORDER BY id ASC LIMIT ?", (limit,)
        )
        prev = GENESIS_HASH
        for row in rows:
            if not row["content_hash"]:
                continue
            payload = {
                "user_id": row["user_id"],
                "action": row["action"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "detail_json": row["detail_json"],
                "created_at": row["created_at"],
            }
            expected = chain_hash(prev, payload)
            if row["prev_hash"] and row["prev_hash"] != prev:
                return False, f"audit id={row['id']} prev_hash mismatch"
            if row["content_hash"] != expected:
                return False, f"audit id={row['id']} content_hash mismatch"
            prev = row["content_hash"]
        return True, "ok"
