from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.exceptions import AuthError, PermissionError, ValidationError
from chem_wh.utils.security import hash_password, verify_password
from chem_wh.utils.timeutil import now_iso

ROLE_PERMS = {
    "admin": {
        "user.manage",
        "backup",
        "chem.write",
        "chem.review",
        "stock.write",
        "stock.dual_review",
        "sds.write",
        "sds.review",
        "hazard.review",
        "inventory.count",
        "report.read",
        "audit.read",
    },
    "warehouse": {
        "chem.write",
        "stock.write",
        "stock.dual_review",
        "sds.write",
        "inventory.count",
        "report.read",
    },
    "safety": {
        "chem.review",
        "sds.review",
        "hazard.review",
        "stock.dual_review",
        "report.read",
        "audit.read",
    },
    "viewer": {"report.read"},
}


@dataclass
class UserSession:
    id: int
    username: str
    role: str
    display_name: str

    def has(self, perm: str) -> bool:
        return perm in ROLE_PERMS.get(self.role, set())


class AuthService:
    def __init__(self, db: Database, audit: AuditService):
        self.db = db
        self.audit = audit

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        display_name: str,
        actor: Optional[UserSession] = None,
    ) -> int:
        if role not in ROLE_PERMS:
            raise ValidationError(f"无效角色: {role}")
        if actor is not None and not actor.has("user.manage"):
            raise PermissionError("无权创建用户")
        if len(password) < 6:
            raise ValidationError("密码至少 6 位")
        digest, salt = hash_password(password)
        try:
            cur = self.db.execute(
                """
                INSERT INTO users(username, password_hash, salt, role, display_name, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (username, digest, salt, role, display_name, now_iso()),
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"无法创建用户: {exc}") from exc
        uid = int(cur.lastrowid)
        self.audit.log(
            actor.id if actor else uid,
            "user.create",
            "users",
            uid,
            {"username": username, "role": role},
        )
        return uid

    def authenticate(self, username: str, password: str) -> UserSession:
        row = self.db.fetchone(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        )
        if not row or not verify_password(password, row["password_hash"], row["salt"]):
            self.audit.log(None, "auth.failed", "users", None, {"username": username})
            raise AuthError("用户名或密码错误")
        session = UserSession(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            display_name=row["display_name"],
        )
        self.audit.log(session.id, "auth.login", "users", session.id, None)
        return session

    def require(self, user: UserSession, perm: str) -> None:
        if not user.has(perm):
            raise PermissionError(f"缺少权限: {perm}")

    def get_user(self, user_id: int) -> Optional[UserSession]:
        row = self.db.fetchone(
            "SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)
        )
        if not row:
            return None
        return UserSession(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            display_name=row["display_name"],
        )

    def verify_second_user(
        self,
        operator: UserSession,
        reviewer_username: str,
        reviewer_password: str,
        required_perm: str = "stock.dual_review",
    ) -> UserSession:
        """Dual control: second independent authorized account."""
        reviewer = self.authenticate(reviewer_username, reviewer_password)
        if reviewer.id == operator.id:
            raise PermissionError("双人复核必须使用两个独立账户，不能由同一人确认")
        if reviewer.username == operator.username:
            raise PermissionError("禁止使用共享账户代替双人复核")
        self.require(reviewer, required_perm)
        return reviewer
