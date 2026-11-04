from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import qrcode

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import StockError, ValidationError
from chem_wh.utils.codes import next_code
from chem_wh.utils.integrity import sha256_file
from chem_wh.utils.timeutil import now_iso

CONTAINER_LIST_SQL = """
    SELECT c.*, ch.name AS chemical_name, ch.cas_no, ch.controlled_flags,
           l.name AS location_name, l.code AS location_code
    FROM containers c
    JOIN chemicals ch ON ch.id = c.chemical_id
    LEFT JOIN locations l ON l.id = c.location_id
"""


class ChemicalService:
    def __init__(
        self,
        db: Database,
        auth: AuthService,
        audit: AuditService,
        data_dir: Path | None = None,
    ):
        self.db = db
        self.auth = auth
        self.audit = audit
        self.data_dir = Path(data_dir) if data_dir else Path(db.path).parent

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
        is_demo: bool = False,
    ) -> int:
        self.auth.require(operator, "chem.write")
        if not name.strip():
            raise ValidationError("化学品名称不能为空")
        mode = self.db.fetchone("SELECT value FROM app_settings WHERE key='app_mode'")
        if mode and mode["value"] == "production" and is_demo:
            raise ValidationError("正式模式禁止写入模拟危化品数据")
        ts = now_iso()
        cur = self.db.execute(
            """
            INSERT INTO chemicals(
                name, cas_no, concentration, specification, manufacturer,
                hazard_review_status, controlled_flags, notes, is_demo, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                cas_no.strip(),
                concentration.strip(),
                specification.strip(),
                manufacturer.strip(),
                controlled_flags.strip(),
                notes,
                1 if is_demo else 0,
                ts,
                ts,
            ),
        )
        cid = int(cur.lastrowid)
        self.audit.log(operator.id, "chem.create", "chemicals", cid, {"name": name})
        return cid

    def update_chemical(
        self,
        operator: UserSession,
        chemical_id: int,
        *,
        name: str,
        cas_no: str = "",
        concentration: str = "",
        specification: str = "",
        manufacturer: str = "",
        notes: str = "",
    ) -> None:
        self.auth.require(operator, "chem.write")
        if not name.strip():
            raise ValidationError("化学品名称不能为空")
        row = self.db.fetchone("SELECT id FROM chemicals WHERE id=?", (chemical_id,))
        if not row:
            raise ValidationError("化学品不存在")
        self.db.execute(
            """
            UPDATE chemicals
            SET name=?, cas_no=?, concentration=?, specification=?, manufacturer=?,
                notes=?, updated_at=?
            WHERE id=?
            """,
            (
                name.strip(),
                cas_no.strip(),
                concentration.strip(),
                specification.strip(),
                manufacturer.strip(),
                notes,
                now_iso(),
                chemical_id,
            ),
        )
        self.audit.log(operator.id, "chem.update", "chemicals", chemical_id, {"name": name})

    def review_hazard(self, reviewer: UserSession, chemical_id: int, status: str) -> None:
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
        hz = self.db.fetchone("SELECT * FROM hazard_classes WHERE id=?", (hazard_class_id,))
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

    def review_hazard_class(self, reviewer: UserSession, hazard_id: int, status: str) -> None:
        self.auth.require(reviewer, "hazard.review")
        self.db.execute(
            """
            UPDATE hazard_classes
            SET review_status=?, reviewed_by=?, reviewed_at=?
            WHERE id=?
            """,
            (status, reviewer.id, now_iso(), hazard_id),
        )

    def add_controlled_category(
        self, operator: UserSession, code: str, name: str, description: str = ""
    ) -> int:
        self.auth.require(operator, "user.manage")
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise ValidationError("管制类别的编码和名称不能为空")
        try:
            cur = self.db.execute(
                """
                INSERT INTO controlled_categories(code, name, description, is_active, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (code, name, description.strip(), now_iso()),
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"无法新增管制类别: {exc}") from exc
        cid = int(cur.lastrowid)
        self.audit.log(
            operator.id,
            "category.create",
            "controlled_categories",
            cid,
            {"code": code, "name": name},
        )
        return cid

    def set_category_active(
        self,
        operator: UserSession,
        category_id: int,
        active: bool,
        reviewer: UserSession | None = None,
    ) -> None:
        self.auth.require(operator, "user.manage")
        row = self.db.fetchone(
            "SELECT * FROM controlled_categories WHERE id=?", (category_id,)
        )
        if not row:
            raise ValidationError("管制类别不存在")
        if not active:
            if reviewer is None or reviewer.id == operator.id:
                raise StockError("停用管制类别需要另一名授权人员复核")
            self.auth.require(reviewer, "stock.dual_review")
        self.db.execute(
            "UPDATE controlled_categories SET is_active=? WHERE id=?",
            (1 if active else 0, category_id),
        )
        self.audit.log(
            operator.id,
            "category.set_active",
            "controlled_categories",
            category_id,
            {
                "active": bool(active),
                "name": row["name"],
                "reviewer_id": reviewer.id if reviewer else None,
            },
        )

    def list_controlled_categories(self, active_only: bool = False) -> list:
        if active_only:
            return self.db.fetchall(
                "SELECT * FROM controlled_categories WHERE is_active=1 ORDER BY name"
            )
        return self.db.fetchall("SELECT * FROM controlled_categories ORDER BY name")

    def category_ids_for(self, chemical_id: int) -> list[int]:
        rows = self.db.fetchall(
            "SELECT category_id FROM chemical_controlled WHERE chemical_id=?",
            (chemical_id,),
        )
        return [int(r["category_id"]) for r in rows]

    def set_chemical_controlled(
        self,
        operator: UserSession,
        chemical_id: int,
        category_ids: list[int],
        reviewer: UserSession | None = None,
    ) -> None:
        self.auth.require(operator, "user.manage")
        chem = self.db.fetchone("SELECT id FROM chemicals WHERE id=?", (chemical_id,))
        if not chem:
            raise ValidationError("化学品不存在")
        current = set(self.category_ids_for(chemical_id))
        desired = {int(i) for i in category_ids}
        for cid in desired:
            row = self.db.fetchone(
                "SELECT is_active, name FROM controlled_categories WHERE id=?", (cid,)
            )
            if not row or not int(row["is_active"]):
                raise ValidationError("管制类别不存在或已停用")
        if current - desired:
            if reviewer is None or reviewer.id == operator.id:
                raise StockError("取消管制标识需要另一名授权人员复核")
            self.auth.require(reviewer, "stock.dual_review")
        conn = self.db.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "DELETE FROM chemical_controlled WHERE chemical_id=?", (chemical_id,)
            )
            now = now_iso()
            for cid in sorted(desired):
                conn.execute(
                    """
                    INSERT INTO chemical_controlled(chemical_id, category_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (chemical_id, cid, now),
                )
            self.audit.log(
                operator.id,
                "chem.set_controlled",
                "chemicals",
                chemical_id,
                {
                    "category_ids": sorted(desired),
                    "removed": sorted(current - desired),
                    "reviewer_id": reviewer.id if reviewer else None,
                },
                conn=conn,
                commit=False,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

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
        conn=None,
    ) -> int:
        self.auth.require(operator, "chem.write")
        if float(quantity) != 0:
            raise ValidationError("新建容器的初始数量必须为 0，请通过入库事务登记数量")
        own = conn is None
        c = conn or self.db.conn
        if own:
            c.execute("BEGIN IMMEDIATE")
        elif not c.in_transaction:
            raise RuntimeError("外部连接必须已处于事务中")
        try:
            chem = c.execute("SELECT id FROM chemicals WHERE id=?", (chemical_id,)).fetchone()
            if not chem:
                raise ValidationError("化学品不存在")
            if location_id is not None:
                loc = c.execute("SELECT id FROM locations WHERE id=?", (location_id,)).fetchone()
                if not loc:
                    raise ValidationError("库位不存在")
            row = c.execute("SELECT COUNT(*) AS c FROM containers").fetchone()
            code = next_code("CTR", int(row["c"]) + 1)
            qr_payload = f"CHEMWH|{code}"
            ts = now_iso()
            cur = c.execute(
                """
                INSERT INTO containers(
                    container_code, chemical_id, batch_no, expiry_date,
                    quantity, unit, location_id, status, qr_payload, qty_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, 'in_stock', ?, 0, ?, ?)
                """,
                (
                    code,
                    chemical_id,
                    batch_no,
                    expiry_date,
                    unit,
                    location_id,
                    qr_payload,
                    ts,
                    ts,
                ),
            )
            cid = int(cur.lastrowid)
            self.audit.log(
                operator.id,
                "container.create",
                "containers",
                cid,
                {"code": code},
                conn=c,
                commit=False,
            )
            if own:
                c.commit()
        except Exception:
            if own:
                try:
                    c.rollback()
                except Exception:
                    pass
            raise
        if qr_dir is not None and own:
            self.write_qr_file(code, qr_payload, qr_dir)
        return cid

    def write_qr(self, container_id: int, qr_dir: Path) -> Path:
        row = self.db.fetchone(
            "SELECT container_code, qr_payload FROM containers WHERE id=?",
            (container_id,),
        )
        if not row:
            raise ValidationError("容器不存在")
        return self.write_qr_file(row["container_code"], row["qr_payload"], qr_dir)

    @staticmethod
    def write_qr_file(code: str, payload: str, qr_dir: Path) -> Path:
        qr_dir.mkdir(parents=True, exist_ok=True)
        dest = Path(qr_dir) / f"{code}.png"
        img = qrcode.make(payload)
        img.save(str(dest))
        return dest

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
        if level not in {"warehouse", "zone", "cabinet", "shelf"}:
            raise ValidationError("库位层级无效")
        if not code.strip() or not name.strip():
            raise ValidationError("库位编码和名称不能为空")
        if parent_id is not None:
            parent = self.db.fetchone("SELECT id FROM locations WHERE id=?", (parent_id,))
            if not parent:
                raise ValidationError("上级库位不存在")
        try:
            cur = self.db.execute(
                """
                INSERT INTO locations(parent_id, level, code, name, storage_condition)
                VALUES (?, ?, ?, ?, ?)
                """,
                (parent_id, level, code.strip(), name.strip(), storage_condition.strip()),
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"无法新增库位: {exc}") from exc
        loc_id = int(cur.lastrowid)
        self.audit.log(
            operator.id, "location.create", "locations", loc_id, {"code": code, "name": name}
        )
        return loc_id

    def list_locations(self) -> list:
        return self.db.fetchall(
            "SELECT * FROM locations ORDER BY COALESCE(parent_id, 0), code"
        )

    def add_sds(
        self,
        operator: UserSession,
        chemical_id: int,
        version: str,
        file_path: str,
        *,
        require_pdf: bool = False,
        copy_into: Path | None = None,
    ) -> int:
        self.auth.require(operator, "sds.write")
        path = Path(file_path)
        if not path.is_file():
            raise ValidationError("SDS 文件不存在（须为本地路径）")
        if require_pdf:
            if path.suffix.lower() != ".pdf":
                raise ValidationError("SDS 须为 PDF 文件")
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise ValidationError("文件不是有效的 PDF")
        digest = sha256_file(path)
        stored = str(path.resolve())
        if copy_into is not None:
            copy_into.mkdir(parents=True, exist_ok=True)
            suffix = path.suffix.lower() or ".bin"
            dest = copy_into / f"{chemical_id}_{digest[:16]}{suffix}"
            if not dest.exists():
                shutil.copy2(path, dest)
            stored = f"sds/{dest.name}"
        cur = self.db.execute(
            """
            INSERT INTO sds_documents(
                chemical_id, version, file_path, file_sha256, review_status, uploaded_at
            ) VALUES (?, ?, ?, ?, 'draft', ?)
            """,
            (chemical_id, version.strip(), stored, digest, now_iso()),
        )
        sid = int(cur.lastrowid)
        self.audit.log(
            operator.id,
            "sds.upload",
            "sds_documents",
            sid,
            {"version": version, "sha256": digest},
        )
        return sid

    def resolve_sds_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if not path.is_absolute():
            path = self.data_dir / path
        return path

    def search_sds(self, keyword: str = "") -> list:
        keyword = keyword.strip()
        if not keyword:
            return self.db.fetchall(
                """
                SELECT s.*, ch.name AS chemical_name, ch.cas_no
                FROM sds_documents s
                JOIN chemicals ch ON ch.id = s.chemical_id
                ORDER BY s.id DESC
                """
            )
        like = f"%{keyword}%"
        return self.db.fetchall(
            """
            SELECT s.*, ch.name AS chemical_name, ch.cas_no
            FROM sds_documents s
            JOIN chemicals ch ON ch.id = s.chemical_id
            WHERE ch.name LIKE ? OR IFNULL(ch.cas_no, '') LIKE ?
               OR s.version LIKE ? OR s.file_path LIKE ?
            ORDER BY s.id DESC
            """,
            (like, like, like, like),
        )

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
        self.audit.log(
            reviewer.id, "sds.review", "sds_documents", sds_id, {"status": status}
        )

    def set_stock_limit(
        self,
        reviewer: UserSession,
        chemical_id: int,
        min_qty: float,
        approved_max_qty: float | None,
        unit: str,
        location_id: Optional[int] = None,
    ) -> int:
        self.auth.require(reviewer, "chem.review")
        if float(min_qty) < 0:
            raise ValidationError("最低库存不能为负")
        if approved_max_qty is not None and float(approved_max_qty) < 0:
            raise ValidationError("上限不能为负")
        if not unit.strip():
            raise ValidationError("限额单位不能为空")
        if location_id is None:
            self.db.execute(
                "DELETE FROM stock_limits WHERE chemical_id=? AND location_id IS NULL",
                (chemical_id,),
            )
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
                float(min_qty),
                None if approved_max_qty is None else float(approved_max_qty),
                unit.strip(),
                reviewer.id,
                now_iso(),
            ),
        )
        self.audit.log(
            reviewer.id,
            "limit.set",
            "stock_limits",
            chemical_id,
            {
                "location_id": location_id,
                "min_qty": float(min_qty),
                "approved_max_qty": approved_max_qty,
                "unit": unit,
            },
        )
        return int(cur.lastrowid)

    def list_limits(self) -> list:
        return self.db.fetchall(
            """
            SELECT sl.*, ch.name AS chemical_name, l.name AS location_name
            FROM stock_limits sl
            JOIN chemicals ch ON ch.id = sl.chemical_id
            LEFT JOIN locations l ON l.id = sl.location_id
            ORDER BY ch.name
            """
        )

    def add_compatibility_note(
        self,
        operator: UserSession,
        chemical_a_id: int,
        chemical_b_id: int,
        note: str,
    ) -> int:
        """Store a manual note. This does not decide whether chemicals may be stored together."""
        self.auth.require(operator, "user.manage")
        text = note.strip()
        if not text:
            raise ValidationError("请填写相容性备注")
        if chemical_a_id == chemical_b_id:
            raise ValidationError("请选择两种不同的化学品")
        left, right = sorted((int(chemical_a_id), int(chemical_b_id)))
        cur = self.db.execute(
            """
            INSERT INTO compatibility_notes(
                chemical_a_id, chemical_b_id, note, review_status, reviewed_by, reviewed_at
            ) VALUES (?, ?, ?, 'approved', ?, ?)
            """,
            (left, right, text, operator.id, now_iso()),
        )
        nid = int(cur.lastrowid)
        self.audit.log(
            operator.id,
            "compat.add",
            "compatibility_notes",
            nid,
            {"a": left, "b": right},
        )
        return nid

    def list_compatibility_notes(self) -> list:
        return self.db.fetchall(
            """
            SELECT n.*, a.name AS name_a, b.name AS name_b
            FROM compatibility_notes n
            JOIN chemicals a ON a.id = n.chemical_a_id
            JOIN chemicals b ON b.id = n.chemical_b_id
            ORDER BY n.id DESC
            """
        )

    def list_chemicals(self) -> list:
        return self.db.fetchall(
            """
            SELECT ch.*,
                   (
                       SELECT group_concat(cat.name, '、')
                       FROM chemical_controlled cc
                       JOIN controlled_categories cat ON cat.id = cc.category_id
                       WHERE cc.chemical_id = ch.id AND cat.is_active = 1
                   ) AS controlled_names
            FROM chemicals ch
            ORDER BY ch.name
            """
        )

    def list_containers(self, status: Optional[str] = None) -> list:
        if status:
            return self.db.fetchall(
                CONTAINER_LIST_SQL + " WHERE c.status=? ORDER BY c.container_code",
                (status,),
            )
        return self.db.fetchall(CONTAINER_LIST_SQL + " ORDER BY c.container_code")

    def find_container_by_code(self, code: str):
        text = (code or "").strip().replace("\r", "").replace("\n", "")
        if not text:
            return None
        payload = text if text.startswith("CHEMWH|") else f"CHEMWH|{text}"
        return self.db.fetchone(
            CONTAINER_LIST_SQL
            + """
            WHERE c.container_code=? OR c.qr_payload=? OR c.qr_payload=?
            """,
            (text, text, payload),
        )
