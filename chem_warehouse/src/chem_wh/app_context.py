from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from chem_wh.db.database import Database, get_default_db_path
from chem_wh.services.alerts import AlertService
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.backup import BackupService
from chem_wh.services.chemicals import ChemicalService
from chem_wh.services.idempotency import lookup, normalize_key, payload_hash, remember
from chem_wh.services.inventory_count import InventoryCountService
from chem_wh.services.reports import ReportService
from chem_wh.services.seed import seed_demo
from chem_wh.services.settings import AppMode, SettingsService
from chem_wh.services.stock import StockService, _r


@dataclass
class ReceiveResult:
    container_id: int
    tx_id: int
    qr_path: str | None = None
    replay: bool = False


class AppContext:
    def __init__(self, db_path: Optional[str | Path] = None):
        self.db = Database(db_path or get_default_db_path())
        self.data_dir = Path(self.db.path).parent
        self.qr_dir = self.data_dir / "qr_codes"
        self.sds_dir = self.data_dir / "sds"
        self.reports_dir = self.data_dir / "reports"
        for folder in (self.qr_dir, self.sds_dir, self.reports_dir):
            folder.mkdir(parents=True, exist_ok=True)
        self.settings = SettingsService(self.db)
        self.audit = AuditService(self.db)
        self.auth = AuthService(self.db, self.audit)
        self.chemicals = ChemicalService(self.db, self.auth, self.audit, self.data_dir)
        self.stock = StockService(self.db, self.auth, self.audit)
        self.alerts = AlertService(self.db)
        self.backup = BackupService(self.db, self.auth, self.audit, self.data_dir)
        self.reports = ReportService(self.db, self.auth)
        self.inventory = InventoryCountService(self.db, self.auth, self.audit, self.stock)
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
        """Demo-only seed. Production must bootstrap a real admin separately."""
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
        """Create the first real admin. No demo chemicals and no demo accounts."""
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

    def receive_new_container(
        self,
        operator: UserSession,
        *,
        chemical_id: int,
        batch_no: str,
        expiry_date: str,
        quantity: float,
        unit: str,
        location_id: int | None,
        remark: str = "",
        reviewer: UserSession | None = None,
        idempotency_key: str | None = None,
    ) -> ReceiveResult:
        """Create one bottle and its inbound transaction in a single commit."""
        key = normalize_key(idempotency_key)
        body = {
            "op": "receive",
            "chemical_id": int(chemical_id),
            "batch_no": (batch_no or "").strip(),
            "expiry_date": (expiry_date or "").strip(),
            "quantity": _r(quantity),
            "unit": (unit or "").strip(),
            "location_id": location_id,
            "operator_id": operator.id,
            "remark": (remark or "").strip(),
        }
        digest = payload_hash(body)
        conn = self.db.conn
        conn.execute("BEGIN IMMEDIATE")
        cid = None
        tx_id = None
        try:
            if key:
                existing = lookup(conn, key, digest)
                if existing is not None:
                    conn.rollback()
                    saved = json.loads(existing["result_json"] or "{}")
                    return ReceiveResult(
                        int(saved["container_id"]),
                        int(saved["tx_id"]),
                        None,
                        replay=True,
                    )
            cid = self.chemicals.create_container(
                operator,
                chemical_id=chemical_id,
                batch_no=body["batch_no"],
                expiry_date=body["expiry_date"],
                quantity=0,
                unit=body["unit"] or "mL",
                location_id=location_id,
                conn=conn,
            )
            tx_id = self.stock.post_transaction(
                operator=operator,
                tx_type="inbound",
                container_id=cid,
                quantity=quantity,
                to_location_id=location_id,
                remark=body["remark"] or "入库",
                reviewer=reviewer,
                conn=conn,
            )
            if key:
                remember(
                    conn,
                    key,
                    digest,
                    tx_id,
                    {"container_id": cid, "tx_id": tx_id},
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        qr_path = None
        try:
            qr_path = str(self.chemicals.write_qr(cid, self.qr_dir))
        except Exception:
            qr_path = None
        return ReceiveResult(cid, tx_id, qr_path, replay=False)

    def login(self, username: str, password: str) -> UserSession:
        self.current_user = self.auth.authenticate(username, password)
        return self.current_user

    def logout(self) -> None:
        if self.current_user:
            self.audit.log(self.current_user.id, "auth.logout", "users", self.current_user.id)
        self.current_user = None

    def close(self) -> None:
        self.db.close()
