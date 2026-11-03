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
from chem_wh.services.stock import StockService


class AppContext:
    def __init__(self, db_path: Optional[str | Path] = None):
        self.db = Database(db_path or get_default_db_path())
        self.audit = AuditService(self.db)
        self.auth = AuthService(self.db, self.audit)
        self.chemicals = ChemicalService(self.db, self.auth, self.audit)
        self.stock = StockService(self.db, self.auth, self.audit)
        self.alerts = AlertService(self.db)
        self.backup = BackupService(self.db, self.auth, self.audit)
        self.reports = ReportService(self.db, self.auth)
        self.inventory = InventoryCountService(
            self.db, self.auth, self.audit, self.stock
        )
        self.current_user: Optional[UserSession] = None
        self.data_dir = Path(self.db.path).parent
        self.qr_dir = self.data_dir / "qr_codes"
        self.qr_dir.mkdir(parents=True, exist_ok=True)

    def ensure_seed(self) -> dict:
        return seed_demo(self.db, self.qr_dir)

    def login(self, username: str, password: str) -> UserSession:
        self.current_user = self.auth.authenticate(username, password)
        return self.current_user

    def logout(self) -> None:
        if self.current_user:
            self.audit.log(self.current_user.id, "auth.logout", "users", self.current_user.id)
        self.current_user = None

    def close(self) -> None:
        self.db.close()
