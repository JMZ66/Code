from __future__ import annotations

from pathlib import Path
from typing import Optional

import qrcode

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import ValidationError
from chem_wh.utils.codes import next_code
from chem_wh.utils.timeutil import now_iso


class ChemicalService:
    def __init__(self, db: Database, auth: AuthService, audit: AuditService):
        self.db = db
        self.auth = auth
        self.audit = audit

    def add_chemical(
        self,
        operator: UserSession,
        *,
        name: str,
        cas_no: str = "",
        concentration: str = "",
        specification: str = "",
        manufacturer: str = "",
        controlled_flags: str = "",
        notes: str = "",
    ) -> int:
        self.auth.require(operator, "chem.write")
        if not name.strip():
            raise ValidationError("化学品名称不能为空")
        ts = now_iso()
        cur = self.db.execute(
            """
            INSERT INTO chemicals(
                name, cas_no, concentration, specification, manufacturer,
                hazard_review_status, controlled_flags, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (
                name.strip(),
                cas_no.strip(),
                concentration.strip(),
                specification.strip(),
                manufacturer.strip(),
                controlled_flags.strip(),
                notes,
                ts,
                ts,
            ),
        )
        cid = int(cur.lastrowid)
        self.audit.log(operator.id, "chem.create", "chemicals", cid, {"name": name})
        return cid

    def review_hazard(
        self, reviewer: UserSession, chemical_id: int, status: str
    ) -> None:
        self.auth.require(reviewer, "chem.review")
        if status not in {"approved", "rejected", "draft"}:
            raise ValidationError("无效审核状态")
        self.db.execute(
            "UPDATE chemicals SET hazard_review_status=?, updated_at=? WHERE id=?",
            (status, now_iso(), chemical_id),
        )
        self.audit.log(
            reviewer.id, "chem.hazard_review", "chemicals", chemical_id, {"status": status}
        )

    def attach_approved_hazard(
        self,
        operator: UserSession,
        chemical_id: int,
        hazard_class_id: int,
        source_note: str,
    ) -> None:
        self.auth.require(operator, "chem.write")
        hz = self.db.fetchone(
            "SELECT * FROM hazard_classes WHERE id=?", (hazard_class_id,)
        )
        if not hz or hz["review_status"] != "approved":
            raise ValidationError("只能关联已审核的危险类别数据")
        self.db.execute(
            """
            INSERT OR REPLACE INTO chemical_hazards(chemical_id, hazard_class_id, source_note)
            VALUES (?, ?, ?)
            """,
            (chemical_id, hazard_class_id, source_note),
        )
        self.audit.log(
            operator.id,
            "chem.attach_hazard",
            "chemicals",
            chemical_id,
            {"hazard_class_id": hazard_class_id},
        )

    def add_hazard_class(
        self, operator: UserSession, code: str, name: str, description: str = ""
    ) -> int:
        self.auth.require(operator, "hazard.review")
        cur = self.db.execute(
            """
            INSERT INTO hazard_classes(code, name, description, review_status)
            VALUES (?, ?, ?, 'draft')
            """,
            (code, name, description),
        )
        return int(cur.lastrowid)

    def review_hazard_class(
        self, reviewer: UserSession, hazard_id: int, status: str
    ) -> None:
        self.auth.require(reviewer, "hazard.review")
        self.db.execute(
            """
            UPDATE hazard_classes
            SET review_status=?, reviewed_by=?, reviewed_at=?
            WHERE id=?
            """,
            (status, reviewer.id, now_iso(), hazard_id),
        )

    def create_container(
        self,
        operator: UserSession,
        *,
        chemical_id: int,
        batch_no: str,
        expiry_date: str,
        quantity: float,
        unit: str,
        location_id: Optional[int],
        qr_dir: Optional[Path] = None,
    ) -> int:
        self.auth.require(operator, "chem.write")
        chem = self.db.fetchone("SELECT id FROM chemicals WHERE id=?", (chemical_id,))
        if not chem:
            raise ValidationError("化学品不存在")
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM containers")
        code = next_code("CTR", int(row["c"]) + 1)
        qr_payload = f"CHEMWH|{code}"
        ts = now_iso()
        cur = self.db.execute(
            """
            INSERT INTO containers(
                container_code, chemical_id, batch_no, expiry_date,
                quantity, unit, location_id, status, qr_payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'in_stock', ?, ?, ?)
            """,
            (
                code,
                chemical_id,
                batch_no,
                expiry_date,
                quantity,
                unit,
                location_id,
                qr_payload,
                ts,
                ts,
            ),
        )
        cid = int(cur.lastrowid)
        if qr_dir is not None:
            qr_dir.mkdir(parents=True, exist_ok=True)
            img = qrcode.make(qr_payload)
            img.save(str(qr_dir / f"{code}.png"))
        self.audit.log(
            operator.id, "container.create", "containers", cid, {"code": code}
        )
        return cid

    def add_location(
        self,
        operator: UserSession,
        *,
        level: str,
        code: str,
        name: str,
        parent_id: Optional[int] = None,
        storage_condition: str = "",
    ) -> int:
        self.auth.require(operator, "chem.write")
        cur = self.db.execute(
            """
            INSERT INTO locations(parent_id, level, code, name, storage_condition)
            VALUES (?, ?, ?, ?, ?)
            """,
            (parent_id, level, code, name, storage_condition),
        )
        return int(cur.lastrowid)

    def add_sds(
        self,
        operator: UserSession,
        chemical_id: int,
        version: str,
        file_path: str,
    ) -> int:
        self.auth.require(operator, "sds.write")
        path = Path(file_path)
        if not path.exists():
            raise ValidationError("SDS 文件不存在（须为本地路径）")
        cur = self.db.execute(
            """
            INSERT INTO sds_documents(
                chemical_id, version, file_path, review_status, uploaded_at
            ) VALUES (?, ?, ?, 'draft', ?)
            """,
            (chemical_id, version, str(path), now_iso()),
        )
        sid = int(cur.lastrowid)
        self.audit.log(operator.id, "sds.upload", "sds_documents", sid, {"version": version})
        return sid

    def review_sds(self, reviewer: UserSession, sds_id: int, status: str) -> None:
        self.auth.require(reviewer, "sds.review")
        if status not in {"approved", "obsolete", "draft"}:
            raise ValidationError("无效 SDS 状态")
        self.db.execute(
            """
            UPDATE sds_documents
            SET review_status=?, reviewed_by=?, reviewed_at=?
            WHERE id=?
            """,
            (status, reviewer.id, now_iso(), sds_id),
        )

    def set_stock_limit(
        self,
        reviewer: UserSession,
        chemical_id: int,
        min_qty: float,
        approved_max_qty: float,
        unit: str,
        location_id: Optional[int] = None,
    ) -> int:
        self.auth.require(reviewer, "chem.review")
        cur = self.db.execute(
            """
            INSERT INTO stock_limits(
                chemical_id, location_id, min_qty, approved_max_qty, unit,
                reviewed_by, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chemical_id, location_id) DO UPDATE SET
                min_qty=excluded.min_qty,
                approved_max_qty=excluded.approved_max_qty,
                unit=excluded.unit,
                reviewed_by=excluded.reviewed_by,
                reviewed_at=excluded.reviewed_at
            """,
            (
                chemical_id,
                location_id,
                min_qty,
                approved_max_qty,
                unit,
                reviewer.id,
                now_iso(),
            ),
        )
        return int(cur.lastrowid)

    def list_chemicals(self) -> list:
        return self.db.fetchall("SELECT * FROM chemicals ORDER BY name")

    def list_containers(self, status: Optional[str] = None) -> list:
        if status:
            return self.db.fetchall(
                """
                SELECT c.*, ch.name AS chemical_name, ch.cas_no
                FROM containers c
                JOIN chemicals ch ON ch.id = c.chemical_id
                WHERE c.status=?
                ORDER BY c.container_code
                """,
                (status,),
            )
        return self.db.fetchall(
            """
            SELECT c.*, ch.name AS chemical_name, ch.cas_no
            FROM containers c
            JOIN chemicals ch ON ch.id = c.chemical_id
            ORDER BY c.container_code
            """
        )

    def find_container_by_code(self, code: str):
        return self.db.fetchone(
            """
            SELECT c.*, ch.name AS chemical_name, ch.controlled_flags
            FROM containers c
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE c.container_code=? OR c.qr_payload=?
            """,
            (code, code if code.startswith("CHEMWH|") else f"CHEMWH|{code}"),
        )
