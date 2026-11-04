"""SQLite schema. New databases are created in full; older files are migrated in place."""

CURRENT_SCHEMA_VERSION = 3

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'admin','warehouse','safety','viewer','user','auditor'
    )),
    display_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES locations(id),
    level TEXT NOT NULL CHECK(level IN ('warehouse','zone','cabinet','shelf')),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    storage_condition TEXT,
    UNIQUE(parent_id, code)
);

CREATE TABLE IF NOT EXISTS chemicals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cas_no TEXT,
    concentration TEXT,
    specification TEXT,
    manufacturer TEXT,
    hazard_review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK(hazard_review_status IN ('draft','approved','rejected')),
    controlled_flags TEXT NOT NULL DEFAULT '',
    notes TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hazard_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK(review_status IN ('draft','approved','rejected')),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS chemical_hazards (
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    hazard_class_id INTEGER NOT NULL REFERENCES hazard_classes(id),
    source_note TEXT,
    PRIMARY KEY (chemical_id, hazard_class_id)
);

CREATE TABLE IF NOT EXISTS controlled_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chemical_controlled (
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    category_id INTEGER NOT NULL REFERENCES controlled_categories(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (chemical_id, category_id)
);

CREATE TABLE IF NOT EXISTS containers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_code TEXT NOT NULL UNIQUE,
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    batch_no TEXT,
    expiry_date TEXT,
    quantity REAL NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    unit TEXT NOT NULL DEFAULT 'mL',
    location_id INTEGER REFERENCES locations(id),
    status TEXT NOT NULL DEFAULT 'in_stock'
        CHECK(status IN ('in_stock','issued','disposed','empty')),
    qr_payload TEXT NOT NULL,
    qty_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sds_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    version TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_sha256 TEXT,
    review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK(review_status IN ('draft','approved','obsolete')),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    location_id INTEGER REFERENCES locations(id),
    min_qty REAL NOT NULL DEFAULT 0 CHECK(min_qty >= 0),
    approved_max_qty REAL CHECK(approved_max_qty IS NULL OR approved_max_qty >= 0),
    unit TEXT NOT NULL DEFAULT 'mL',
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    UNIQUE(chemical_id, location_id)
);

CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_no TEXT NOT NULL UNIQUE,
    tx_type TEXT NOT NULL CHECK(tx_type IN (
        'inbound','issue','return','transfer','dispose','adjust_pos','adjust_neg','reversal'
    )),
    container_id INTEGER NOT NULL REFERENCES containers(id),
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    qty_delta REAL NOT NULL,
    qty_before REAL NOT NULL,
    qty_after REAL NOT NULL,
    unit TEXT NOT NULL,
    from_location_id INTEGER REFERENCES locations(id),
    to_location_id INTEGER REFERENCES locations(id),
    operator_id INTEGER NOT NULL REFERENCES users(id),
    reviewer_id INTEGER REFERENCES users(id),
    dual_required INTEGER NOT NULL DEFAULT 0,
    related_tx_id INTEGER REFERENCES stock_transactions(id),
    remark TEXT,
    content_hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(qty_after >= 0)
);

CREATE TABLE IF NOT EXISTS inventory_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_no TEXT NOT NULL UNIQUE,
    location_id INTEGER REFERENCES locations(id),
    operator_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','closing','closed','cancelled')),
    adjustments_posted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS inventory_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES inventory_sessions(id),
    container_id INTEGER NOT NULL REFERENCES containers(id),
    book_qty REAL NOT NULL,
    book_qty_version INTEGER NOT NULL DEFAULT 0,
    counted_qty REAL NOT NULL CHECK(counted_qty >= 0),
    difference REAL NOT NULL,
    settle_book_qty REAL,
    settle_difference REAL,
    adjustment_tx_id INTEGER REFERENCES stock_transactions(id),
    remark TEXT,
    UNIQUE(session_id, container_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    detail_json TEXT,
    content_hash TEXT,
    prev_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compatibility_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chemical_a_id INTEGER NOT NULL REFERENCES chemicals(id),
    chemical_b_id INTEGER NOT NULL REFERENCES chemicals(id),
    note TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK(review_status IN ('draft','approved','rejected')),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    CHECK(chemical_a_id < chemical_b_id)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idem_key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    result_id INTEGER,
    result_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_containers_chemical ON containers(chemical_id);
CREATE INDEX IF NOT EXISTS idx_containers_code ON containers(container_code);
CREATE INDEX IF NOT EXISTS idx_containers_status ON containers(status);
CREATE INDEX IF NOT EXISTS idx_tx_created ON stock_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_tx_chemical ON stock_transactions(chemical_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_chem_controlled_cat ON chemical_controlled(category_id);
"""

# Columns added after the earliest V0.1 files. Duplicate-column errors are ignored.
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chemicals ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE containers ADD COLUMN qty_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE sds_documents ADD COLUMN file_sha256 TEXT",
    "ALTER TABLE stock_transactions ADD COLUMN related_tx_id INTEGER",
    "ALTER TABLE stock_transactions ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock_transactions ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE inventory_sessions ADD COLUMN adjustments_posted INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE inventory_lines ADD COLUMN book_qty_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE inventory_lines ADD COLUMN settle_book_qty REAL",
    "ALTER TABLE inventory_lines ADD COLUMN settle_difference REAL",
    "ALTER TABLE inventory_lines ADD COLUMN adjustment_tx_id INTEGER",
    "ALTER TABLE audit_logs ADD COLUMN content_hash TEXT",
    "ALTER TABLE audit_logs ADD COLUMN prev_hash TEXT",
    "ALTER TABLE idempotency_keys ADD COLUMN result_json TEXT",
]
