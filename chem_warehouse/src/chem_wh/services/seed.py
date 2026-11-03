"""模拟化学品数据初始化（演示/测试用，非真实监管数据）。"""

from __future__ import annotations

from pathlib import Path

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService
from chem_wh.services.chemicals import ChemicalService
from chem_wh.services.stock import StockService


DEMO_USERS = [
    ("admin", "Admin@123", "admin", "系统管理员"),
    ("warehouse1", "Wh@12345", "warehouse", "库管员甲"),
    ("warehouse2", "Wh@12345", "warehouse", "库管员乙"),
    ("safety1", "Sf@12345", "safety", "安全员"),
    ("viewer1", "Vw@12345", "viewer", "只读用户"),
]

# 模拟分析化学常用试剂（演示数据）
DEMO_CHEMICALS = [
    {
        "name": "盐酸",
        "cas_no": "7647-01-0",
        "concentration": "36%",
        "specification": "500mL",
        "manufacturer": "演示试剂厂A",
        "controlled_flags": "",
        "batch": "B20250101",
        "expiry": "2028-01-01",
        "qty": 500,
        "unit": "mL",
        "min_qty": 100,
        "max_qty": 2000,
    },
    {
        "name": "硝酸",
        "cas_no": "7697-37-2",
        "concentration": "65%",
        "specification": "500mL",
        "manufacturer": "演示试剂厂A",
        "controlled_flags": "",
        "batch": "B20250201",
        "expiry": "2028-06-01",
        "qty": 500,
        "unit": "mL",
        "min_qty": 100,
        "max_qty": 1500,
    },
    {
        "name": "甲醇",
        "cas_no": "67-56-1",
        "concentration": "HPLC",
        "specification": "4L",
        "manufacturer": "演示试剂厂B",
        "controlled_flags": "",
        "batch": "B20250301",
        "expiry": "2027-12-31",
        "qty": 4000,
        "unit": "mL",
        "min_qty": 500,
        "max_qty": 20000,
    },
    {
        "name": "乙腈",
        "cas_no": "75-05-8",
        "concentration": "HPLC",
        "specification": "4L",
        "manufacturer": "演示试剂厂B",
        "controlled_flags": "",
        "batch": "B20250315",
        "expiry": "2028-03-01",
        "qty": 4000,
        "unit": "mL",
        "min_qty": 500,
        "max_qty": 16000,
    },
    {
        "name": "丙酮",
        "cas_no": "67-64-1",
        "concentration": "AR",
        "specification": "500mL",
        "manufacturer": "演示试剂厂C",
        "controlled_flags": "precursor",  # 演示：按易制毒类标识，需单位审核确认
        "batch": "B20250401",
        "expiry": "2028-08-01",
        "qty": 500,
        "unit": "mL",
        "min_qty": 100,
        "max_qty": 1000,
    },
    {
        "name": "过氧化氢",
        "cas_no": "7722-84-1",
        "concentration": "30%",
        "specification": "500mL",
        "manufacturer": "演示试剂厂C",
        "controlled_flags": "",
        "batch": "B20241101",
        "expiry": "2025-01-01",  # 故意过期，用于演示预警
        "qty": 200,
        "unit": "mL",
        "min_qty": 50,
        "max_qty": 800,
    },
]


def seed_demo(db: Database, qr_dir: Path | None = None) -> dict:
    """仅演示模式可调用。正式模式调用将抛错。"""
    from chem_wh.services.settings import SettingsService

    settings = SettingsService(db)
    settings.assert_demo_allowed()
    if settings.get_mode() == "unset":
        settings.set_mode("demo")

    audit = AuditService(db)
    auth = AuthService(db, audit)
    chem = ChemicalService(db, auth, audit)
    stock = StockService(db, auth, audit)

    existing = db.fetchone("SELECT COUNT(*) AS c FROM users")
    if existing and int(existing["c"]) > 0:
        return {"skipped": True, "reason": "already_seeded"}

    for username, password, role, display in DEMO_USERS:
        auth.create_user(username, password, role, display, is_demo=True, production=False)

    admin = auth.authenticate("admin", "Admin@123")
    safety = auth.authenticate("safety1", "Sf@12345")
    wh = auth.authenticate("warehouse1", "Wh@12345")

    # Locations
    wh_id = chem.add_location(
        admin, level="warehouse", code="WH1", name="危化品主库", storage_condition="阴凉通风"
    )
    zone_acid = chem.add_location(
        admin, level="zone", code="Z-ACID", name="酸类分区", parent_id=wh_id, storage_condition="耐腐蚀"
    )
    zone_org = chem.add_location(
        admin, level="zone", code="Z-ORG", name="有机溶剂分区", parent_id=wh_id, storage_condition="防爆"
    )
    cab_a = chem.add_location(
        admin, level="cabinet", code="C-A1", name="酸柜A1", parent_id=zone_acid
    )
    cab_o = chem.add_location(
        admin, level="cabinet", code="C-O1", name="溶剂柜O1", parent_id=zone_org
    )
    shelf_a = chem.add_location(
        admin, level="shelf", code="S1", name="第1层", parent_id=cab_a
    )
    shelf_o = chem.add_location(
        admin, level="shelf", code="S1", name="第1层", parent_id=cab_o
    )

    # Hazard classes (reviewed)
    hz_corr = chem.add_hazard_class(safety, "GHS05", "腐蚀性", "单位制度审核示例分类")
    hz_flam = chem.add_hazard_class(safety, "GHS02", "易燃液体", "单位制度审核示例分类")
    chem.review_hazard_class(safety, hz_corr, "approved")
    chem.review_hazard_class(safety, hz_flam, "approved")

    # Dummy SDS pdf content
    sds_root = Path(db.path).parent / "sds"
    sds_root.mkdir(parents=True, exist_ok=True)

    created_containers = []
    for item in DEMO_CHEMICALS:
        cid = chem.add_chemical(
            admin,
            name=item["name"],
            cas_no=item["cas_no"],
            concentration=item["concentration"],
            specification=item["specification"],
            manufacturer=item["manufacturer"],
            controlled_flags=item["controlled_flags"],
            notes="演示数据，分类与管制标识须单位授权人员复核",
            is_demo=True,
        )
        chem.review_hazard(safety, cid, "approved")
        hz = hz_corr if "酸" in item["name"] or item["name"] == "过氧化氢" else hz_flam
        chem.attach_approved_hazard(admin, cid, hz, "依据单位已审核分类表（演示）")

        loc = shelf_a if hz == hz_corr else shelf_o
        sds_file = sds_root / f"{item['cas_no'].replace('-', '_')}_sds.txt"
        sds_file.write_text(
            f"演示 SDS 占位文件\n化学品: {item['name']}\nCAS: {item['cas_no']}\n",
            encoding="utf-8",
        )
        # 过氧化氢故意不上传已审核 SDS，触发缺失预警；其余审核通过
        if item["name"] != "过氧化氢":
            sid = chem.add_sds(admin, cid, "1.0", str(sds_file))
            chem.review_sds(safety, sid, "approved")
        else:
            chem.add_sds(admin, cid, "0.9-draft", str(sds_file))

        chem.set_stock_limit(
            safety,
            cid,
            min_qty=item["min_qty"],
            approved_max_qty=item["max_qty"],
            unit=item["unit"],
        )

        ctr_id = chem.create_container(
            admin,
            chemical_id=cid,
            batch_no=item["batch"],
            expiry_date=item["expiry"],
            quantity=0,  # inbound via stock tx
            unit=item["unit"],
            location_id=loc,
            qr_dir=qr_dir,
        )
        stock.post_transaction(
            operator=wh,
            tx_type="inbound",
            container_id=ctr_id,
            quantity=item["qty"],
            to_location_id=loc,
            remark="演示初始入库",
        )
        created_containers.append(ctr_id)

    # Extra bottle for acetone to demo dual-control later
    acetone = db.fetchone("SELECT id FROM chemicals WHERE name=?", ("丙酮",))
    ctr2 = chem.create_container(
        admin,
        chemical_id=int(acetone["id"]),
        batch_no="B20250402",
        expiry_date="2028-08-01",
        quantity=0,
        unit="mL",
        location_id=shelf_o,
        qr_dir=qr_dir,
    )
    stock.post_transaction(
        operator=wh,
        tx_type="inbound",
        container_id=ctr2,
        quantity=500,
        to_location_id=shelf_o,
        remark="演示第二瓶丙酮入库",
    )

    return {
        "skipped": False,
        "users": len(DEMO_USERS),
        "chemicals": len(DEMO_CHEMICALS),
        "containers": len(created_containers) + 1,
    }
