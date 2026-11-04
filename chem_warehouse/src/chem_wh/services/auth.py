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
    "user": {"report.read"},
    "auditor": {"report.read", "audit.read"},
}

ROLE_LABELS = {
    "admin": "管理员",
    "warehouse": "库管员",
    "safety": "安全员",
    "viewer": "只读用户",
    "user": "普通用户",
    "auditor": "审计员",
}


@dataclass
class UserSession:
    id: int
    username: str
    role: str
    display_name: str

    def has(self, perm: str) -> bool:
        return perm in ROLE_PERMS.get(self.role, set())

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


class AuthService:
    def __init__(self, db: Database, audit: AuditService):
        self.db = db
        self.audit = audit

    @staticmethod
    def validate_password(password: str, *, production: bool = False) -> None:
        if len(password) < 6:
            raise ValidationError("密码至少 6 位")
        if production:
            if len(password) < 10:
                raise ValidationError("正式模式密码至少 10 位")
            classes = sum(
                [
                    any(c.islower() for c in password),
                    any(c.isupper() for c in password),
                    any(c.isdigit() for c in password),
                    any(not c.isalnum() for c in password),
                ]
            )
            if classes < 3:
                raise ValidationError(
                    "正式模式密码须包含大小写字母、数字、符号中至少三类"
                )
            banned = {
                "Admin@123",
                "Wh@12345",
                "Sf@12345",
                "Vw@12345",
                "password",
                "123456",
            }
            if password in banned:
                raise ValidationError("正式模式禁止使用演示/常见弱密码")

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        display_name: str,
        actor: Optional[UserSession] = None,
        *,
        is_demo: bool = False,
        production: bool = False,
    ) -> int:
        if role not in ROLE_PERMS:
            raise ValidationError(f"无效角色: {role}")
        if actor is not None and not actor.has("user.manage"):
            raise PermissionError("无权创建用户")
        username = username.strip()
        display_name = display_name.strip()
        if len(username) < 2 or len(username) > 32 or any(ch.isspace() for ch in username):
            raise ValidationError("用户名长度为 2 到 32，且不能包含空格")
        if not display_name:
            raise ValidationError("姓名不能为空")
        if production and is_demo:
            raise ValidationError("正式模式禁止创建演示账户")
        self.validate_password(password, production=production)
        digest, salt = hash_password(password)
        try:
            cur = self.db.execute(
                """
                INSERT INTO users(
                    username, password_hash, salt, role, display_name,
                    is_active, is_demo, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    username,
                    digest,
                    salt,
                    role,
                    display_name,
                    1 if is_demo else 0,
                    now_iso(),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"无法创建用户: {exc}") from exc
        uid = int(cur.lastrowid)
        self.audit.log(
            actor.id if actor else uid,
            "user.create",
            "users",
            uid,
            {"username": username, "role": role, "is_demo": is_demo},
        )
        return uid

    def authenticate(
        self,
        username: str,
        password: str,
        *,
        audit_success: bool = True,
        purpose: str = "login",
    ) -> UserSession:
        row = self.db.fetchone(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        )
        if not row or not verify_password(password, row["password_hash"], row["salt"]):
            self.audit.log(None, "auth.failed", "users", None, {"username": username})
            raise AuthError("用户名或密码错误")
        mode_row = self.db.fetchone("SELECT value FROM app_settings WHERE key='app_mode'")
        if mode_row and mode_row["value"] == "production" and int(row["is_demo"] or 0) == 1:
            self.audit.log(
                None, "auth.demo_blocked", "users", row["id"], {"username": username}
            )
            raise AuthError("正式模式禁止使用演示账户登录")
        session = UserSession(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            display_name=row["display_name"],
        )
        if audit_success:
            self.audit.log(session.id, f"auth.{purpose}", "users", session.id, None)
        return session

    def require(self, user: UserSession, perm: str) -> None:
        if not user.has(perm):
            raise PermissionError(f"缺少权限: {perm}")

    def get_user(self, user_id: int) -> Optional[UserSession]:
        row = self.db.fetchone("SELECT * FROM users WHERE id=? AND is_active=1", (user_id,))
        if not row:
            return None
        return UserSession(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            display_name=row["display_name"],
        )

    def list_users(self, actor: UserSession) -> list:
        if not (actor.has("user.manage") or actor.has("audit.read")):
            raise PermissionError("无权查看用户列表")
        return self.db.fetchall(
            """
            SELECT id, username, role, display_name, is_active, is_demo, created_at
            FROM users ORDER BY id
            """
        )

    def set_active(self, actor: UserSession, user_id: int, active: bool) -> None:
        self.require(actor, "user.manage")
        if user_id == actor.id and not active:
            raise ValidationError("不能停用当前登录账户")
        row = self.db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
        if not row:
            raise ValidationError("用户不存在")
        if not active and row["role"] == "admin":
            count = self.db.fetchone(
                "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND is_active=1"
            )
            if int(count["c"]) <= 1:
                raise ValidationError("不能停用唯一的管理员")
        self.db.execute(
            "UPDATE users SET is_active=? WHERE id=?",
            (1 if active else 0, user_id),
        )
        self.audit.log(
            actor.id,
            "user.set_active",
            "users",
            user_id,
            {"active": bool(active), "username": row["username"]},
        )

    def reset_password(
        self,
        actor: UserSession,
        user_id: int,
        new_password: str,
        *,
        production: bool,
    ) -> None:
        self.require(actor, "user.manage")
        row = self.db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
        if not row:
            raise ValidationError("用户不存在")
        self.validate_password(new_password, production=production)
        digest, salt = hash_password(new_password)
        self.db.execute(
            "UPDATE users SET password_hash=?, salt=? WHERE id=?",
            (digest, salt, user_id),
        )
        self.audit.log(
            actor.id,
            "user.reset_password",
            "users",
            user_id,
            {"username": row["username"]},
        )

    def verify_second_user(
        self,
        operator: UserSession,
        reviewer_username: str,
        reviewer_password: str,
        required_perm: str = "stock.dual_review",
    ) -> UserSession:
        """A different, authorized person must type their own password."""
        reviewer = self.authenticate(
            reviewer_username,
            reviewer_password,
            audit_success=False,
            purpose="dual_review",
        )
        if reviewer.id == operator.id or reviewer.username == operator.username:
            self.audit.log(
                operator.id,
                "auth.dual_self_rejected",
                "users",
                reviewer.id,
                {"reviewer": reviewer.username},
            )
            raise PermissionError("双人复核必须使用两个独立账户，不能由同一人确认")
        try:
            self.require(reviewer, required_perm)
        except PermissionError:
            self.audit.log(
                operator.id,
                "auth.dual_unauthorized",
                "users",
                reviewer.id,
                {"reviewer": reviewer.username, "role": reviewer.role},
            )
            raise
        self.audit.log(
            reviewer.id,
            "auth.dual_review",
            "users",
            reviewer.id,
            {"operator_id": operator.id, "operator": operator.username},
        )
        return reviewer
