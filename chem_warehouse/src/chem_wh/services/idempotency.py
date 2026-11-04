"""Idempotency keys so a double click or a retried request cannot post twice."""

from __future__ import annotations

import json
from typing import Any

from chem_wh.services.exceptions import ValidationError
from chem_wh.utils.integrity import canonical_json, sha256_text
from chem_wh.utils.timeutil import now_iso


def normalize_key(key: str | None) -> str | None:
    if key is None:
        return None
    text = str(key).strip()
    if not text:
        return None
    if len(text) < 8 or len(text) > 80:
        raise ValidationError("幂等键长度须为 8 到 80 个字符")
    return text


def payload_hash(payload: dict) -> str:
    return sha256_text(canonical_json(payload))


def lookup(conn, key: str, digest: str):
    row = conn.execute(
        "SELECT * FROM idempotency_keys WHERE idem_key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    if row["payload_hash"] != digest:
        raise ValidationError(
            "该提交标识已用于另一笔不同的操作，已拒绝，以免重复记账或记错账"
        )
    return row


def remember(
    conn,
    key: str,
    digest: str,
    result_id: int | None,
    result: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO idempotency_keys(idem_key, payload_hash, result_id, result_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            key,
            digest,
            result_id,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            now_iso(),
        ),
    )
