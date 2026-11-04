"""Application mode and settings. Demo vs production isolation."""

from __future__ import annotations

from typing import Literal

from chem_wh.db.database import Database
from chem_wh.services.auth import UserSession
from chem_wh.services.exceptions import PermissionError, ValidationError
from chem_wh.utils.timeutil import now_iso

AppMode = Literal["demo", "production", "unset"]

MODE_KEY = "app_mode"
MODE_LOCKED_KEY = "app_mode_locked"


class SettingsService:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.fetchone("SELECT value FROM app_settings WHERE key=?", (key,))
        if not row:
            return default
        return row["value"]

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            """
            INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now_iso()),
        )

    def get_mode(self) -> AppMode:
        value = self.get(MODE_KEY)
        if value in ("demo", "production"):
            return value  # type: ignore[return-value]
        return "unset"

    def is_mode_locked(self) -> bool:
        return self.get(MODE_LOCKED_KEY, "0") == "1"

    def set_mode(self, mode: AppMode, *, force: bool = False) -> None:
        if mode not in ("demo", "production"):
            raise ValidationError("模式仅可为 demo 或 production")
        current = self.get_mode()
        if self.is_mode_locked() and current != "unset" and current != mode and not force:
            raise ValidationError(
                f"应用模式已锁定为 {current}，禁止切换到 {mode}。"
                "正式环境不得启用演示数据。"
            )
        self.set(MODE_KEY, mode)
        self.set(MODE_LOCKED_KEY, "1")

    def assert_demo_allowed(self) -> None:
        mode = self.get_mode()
        if mode == "production":
            raise ValidationError("正式模式禁止加载演示账户、固定密码或模拟危化品数据")

    def get_expiry_warn_days(self) -> int:
        raw = self.get("expiry_warn_days", "30") or "30"
        try:
            days = int(raw)
        except ValueError:
            return 30
        return min(max(days, 1), 3650)

    def set_expiry_warn_days(self, actor: UserSession, days: int) -> None:
        if not (actor.has("user.manage") or actor.has("chem.review")):
            raise PermissionError("无权设置效期预警天数")
        days = int(days)
        if days < 1 or days > 3650:
            raise ValidationError("预警天数须在 1 到 3650 之间")
        self.set("expiry_warn_days", str(days))
