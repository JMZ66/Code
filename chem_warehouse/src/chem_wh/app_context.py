from __future__ import annotations

from pathlib import Path
from typing import Optional

from chem_wh.db.database import Database, get_default_db_path
from chem_wh.services.alerts import AlertService
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.backup import BackupService
from chem_wh.services.chemicals import ChemicalService
from chem_wh.services.inventory_count import InventoryCountService
from chem_wh.services.reports import ReportService
from chem_wh.services.seed import seed_demo
from chem_wh.services.settings import AppMode, SettingsService
from chem_wh.services.stock import StockService


class AppContext:
    def __init__(self, db_path: Optional[str | Path] = None):
        self.db = Database(db_path or get_default_db_path())
        self.settings = SettingsService(self.db)
        self.audit = AuditService(self.db)
        self.auth = AuthService(self.db, self.audit)
        self.chemicals = ChemicalService(self.db, self.auth, self.audit)
        self.stock = StockService(self.db, self.auth, self.audit)
        self.alerts = AlertService(self.db)
        self.data_dir = Path(self.db.path).parent
        self.qr_dir = self.data_dir / "qr_codes"
        self.sds_dir = self.data_dir / "sds"
        self.qr_dir.mkdir(parents=True, exist_ok=True)
        self.sds_dir.mkdir(parents=True, exist_ok=True)
        self.backup = BackupService(self.db, self.auth, self.audit, self.data_dir)
        self.reports = ReportService(self.db, self.auth)
        self.inventory = InventoryCountService(
            self.db, self.auth, self.audit, self.stock
        )
        self.current_user: Optional[UserSession] = None

    @property
    def mode(self) -> AppMode:
        return self.settings.get_mode()

    def initialize_mode(self, mode: AppMode) -> None:
        if mode not in ("demo", "production"):
            raise ValueError("mode must be demo or production")
        current = self.settings.get_mode()
        if current == "unset":
            self.settings.set_mode(mode)
        elif current != mode:
            raise ValueError(f"数据库已锁定为 {current} 模式，与请求的 {mode} 不一致")

    def ensure_seed(self) -> dict:
        """Demo-only seed. Production must bootstrap real admin separately."""
        self.settings.assert_demo_allowed()
        if self.settings.get_mode() == "unset":
            self.settings.set_mode("demo")
        return seed_demo(self.db, self.qr_dir)

    def bootstrap_production_admin(
        self,
        username: str,
        password: str,
        display_name: str = "系统管理员",
    ) -> int:
        """Create the first real admin in production mode (no demo data)."""
        from chem_wh.services.exceptions import ValidationError

        if self.settings.get_mode() == "unset":
            self.settings.set_mode("production")
        if self.settings.get_mode() != "production":
            raise ValidationError("仅正式模式可执行生产管理员初始化")
        existing = self.db.fetchone("SELECT COUNT(*) AS c FROM users")
        if existing and int(existing["c"]) > 0:
            raise ValidationError("已存在用户，禁止重复生产初始化")
        return self.auth.create_user(
            username,
            password,
            "admin",
            display_name,
            is_demo=False,
            production=True,
        )

    def login(self, username: str, password: str) -> UserSession:
        self.current_user = self.auth.authenticate(username, password)
        return self.current_user

    def logout(self) -> None:
        if self.current_user:
            self.audit.log(
                self.current_user.id, "auth.logout", "users", self.current_user.id
            )
        self.current_user = None

    def close(self) -> None:
        self.db.close()
