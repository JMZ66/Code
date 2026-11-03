"""SQLite schema for V0.1."""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','warehouse','safety','viewer')),
    display_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
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
    controlled_flags TEXT NOT NULL DEFAULT '', -- comma: toxic,precursor,explosive,monitored
    notes TEXT,
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

CREATE TABLE IF NOT EXISTS containers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_code TEXT NOT NULL UNIQUE,
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    batch_no TEXT,
    expiry_date TEXT,
    quantity REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT 'mL',
    location_id INTEGER REFERENCES locations(id),
    status TEXT NOT NULL DEFAULT 'in_stock'
        CHECK(status IN ('in_stock','issued','disposed','empty')),
    qr_payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sds_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chemical_id INTEGER NOT NULL REFERENCES chemicals(id),
    version TEXT NOT NULL,
    file_path TEXT NOT NULL,
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
    min_qty REAL NOT NULL DEFAULT 0,
    approved_max_qty REAL,
    unit TEXT NOT NULL DEFAULT 'mL',
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    UNIQUE(chemical_id, location_id)
);

CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_no TEXT NOT NULL UNIQUE,
    tx_type TEXT NOT NULL CHECK(tx_type IN (
        'inbound','issue','return','transfer','dispose','adjust_pos','adjust_neg'
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
    remark TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_no TEXT NOT NULL UNIQUE,
    location_id INTEGER REFERENCES locations(id),
    operator_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS inventory_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES inventory_sessions(id),
    container_id INTEGER NOT NULL REFERENCES containers(id),
    book_qty REAL NOT NULL,
    counted_qty REAL NOT NULL,
    difference REAL NOT NULL,
    remark TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    detail_json TEXT,
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

CREATE INDEX IF NOT EXISTS idx_containers_chemical ON containers(chemical_id);
CREATE INDEX IF NOT EXISTS idx_containers_status ON containers(status);
CREATE INDEX IF NOT EXISTS idx_tx_created ON stock_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_tx_chemical ON stock_transactions(chemical_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
"""
