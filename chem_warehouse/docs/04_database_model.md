# 数据库模型 V0.1

引擎：SQLite（WAL）。字符集：UTF-8。

## ER 概要

```
users ──┬── audit_logs
        ├── stock_transactions (operator / reviewer)
        └── dual_approvals

chemicals ──┬── containers ── stock_transactions
            ├── chemical_hazards ── hazard_classes
            ├── sds_documents
            └── stock_limits

locations (warehouse/zone/cabinet/shelf 树)
inventory_sessions ── inventory_lines
```

## 核心表

### users
id, username, password_hash, salt, role, display_name, is_active, created_at

### chemicals
id, name, cas_no, concentration, specification, manufacturer,
hazard_review_status (draft/approved/rejected), notes, created_at, updated_at

### containers（瓶级）
id, container_code (UNIQUE), chemical_id, batch_no, expiry_date,
quantity, unit, location_id, status (in_stock/issued/disposed/empty),
qr_payload, created_at, updated_at

### locations
id, parent_id, level (warehouse/zone/cabinet/shelf), code, name, storage_condition

### hazard_classes
id, code, name, description, review_status, reviewed_by, reviewed_at

### chemical_hazards
chemical_id, hazard_class_id, source_note（制度/审核依据说明）

### sds_documents
id, chemical_id, version, file_path, review_status, reviewed_by, reviewed_at, uploaded_at

### stock_limits
chemical_id, location_id(nullable), min_qty, approved_max_qty, unit, reviewed_by, reviewed_at

### stock_transactions（只增不删）
id, tx_no, tx_type (inbound/issue/return/transfer/dispose/adjust_pos/adjust_neg),
container_id, chemical_id, qty_delta, qty_before, qty_after, unit,
from_location_id, to_location_id, operator_id, reviewer_id, dual_required,
remark, created_at
UNIQUE(tx_no)；无 DELETE 业务接口

### inventory_sessions / inventory_lines
盘点会话与账面/实盘差异

### audit_logs
id, user_id, action, entity_type, entity_id, detail_json, created_at

### compatibility_notes（人工维护，非自动判定）
id, chemical_a_id, chemical_b_id, note, review_status, reviewed_by
说明：仅存储已审核文字说明；应用层禁止据此输出“可安全混储”自动结论。
