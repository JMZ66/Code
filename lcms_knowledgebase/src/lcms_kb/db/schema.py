"""SQLite 表结构。检索字段都建了索引，避免历史数据一多就卡住。"""

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    format_name TEXT NOT NULL,
    sample_name TEXT,
    sample_type TEXT NOT NULL DEFAULT 'unknown',
    replicate_group TEXT,
    inject_order INTEGER,
    instrument_text TEXT,
    vendors_inferred TEXT,
    acquisition_text TEXT,
    test_only_synthetic INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    imported_by TEXT NOT NULL,
    software_version TEXT NOT NULL,
    n_spectra INTEGER NOT NULL,
    rt_start REAL,
    rt_end REAL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_datasets_type ON datasets(sample_type);
CREATE INDEX IF NOT EXISTS idx_datasets_sha ON datasets(sha256);
CREATE INDEX IF NOT EXISTS idx_datasets_sample ON datasets(sample_name);
CREATE INDEX IF NOT EXISTS idx_datasets_rep ON datasets(replicate_group);
CREATE INDEX IF NOT EXISTS idx_datasets_inject ON datasets(inject_order);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    scan_number INTEGER NOT NULL,
    index_in_file INTEGER NOT NULL,
    ms_level INTEGER,
    polarity TEXT,
    rt_min REAL,
    scan_mode TEXT,
    scan_mode_basis TEXT,
    precursor_mz REAL,
    precursor_charge INTEGER,
    isolation_width REAL,
    collision_energy REAL,
    activation TEXT,
    tic REAL,
    bpc REAL,
    bpc_mz REAL,
    filter_string TEXT,
    UNIQUE(dataset_id, index_in_file)
);

CREATE INDEX IF NOT EXISTS idx_scans_dataset_rt ON scans(dataset_id, rt_min);
CREATE INDEX IF NOT EXISTS idx_scans_level_pol ON scans(dataset_id, ms_level, polarity);
CREATE INDEX IF NOT EXISTS idx_scans_precursor ON scans(precursor_mz);
CREATE INDEX IF NOT EXISTS idx_scans_mode ON scans(scan_mode);
CREATE INDEX IF NOT EXISTS idx_scans_ce ON scans(collision_energy);

CREATE TABLE IF NOT EXISTS archive_ions (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    scan_number INTEGER NOT NULL,
    ms_level INTEGER,
    polarity TEXT,
    rt_min REAL,
    mz REAL NOT NULL,
    intensity REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ions_mz ON archive_ions(mz);
CREATE INDEX IF NOT EXISTS idx_ions_dataset ON archive_ions(dataset_id);

CREATE TABLE IF NOT EXISTS library_entries (
    id INTEGER PRIMARY KEY,
    entry_type TEXT NOT NULL,
    compound_name TEXT,
    formula TEXT,
    adduct TEXT,
    polarity TEXT,
    rt_min REAL,
    precursor_mz REAL,
    collision_energy REAL,
    activation TEXT,
    scan_mode TEXT,
    source_dataset_id INTEGER,
    source_scan_number INTEGER,
    source_sha256 TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    notes TEXT,
    peaks_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lib_name ON library_entries(compound_name);
CREATE INDEX IF NOT EXISTS idx_lib_formula ON library_entries(formula);
CREATE INDEX IF NOT EXISTS idx_lib_prec ON library_entries(precursor_mz);
CREATE INDEX IF NOT EXISTS idx_lib_rt ON library_entries(rt_min);
CREATE INDEX IF NOT EXISTS idx_lib_pol_ce ON library_entries(polarity, collision_energy);
CREATE INDEX IF NOT EXISTS idx_lib_type ON library_entries(entry_type);

CREATE TABLE IF NOT EXISTS library_fragments (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES library_entries(id) ON DELETE CASCADE,
    mz REAL NOT NULL,
    intensity REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_frag_mz ON library_fragments(mz);
CREATE INDEX IF NOT EXISTS idx_frag_entry ON library_fragments(entry_id);

CREATE TABLE IF NOT EXISTS conclusions (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER,
    scan_number INTEGER,
    library_entry_id INTEGER,
    layer TEXT NOT NULL CHECK (layer IN ('algorithm_result', 'library_candidate', 'human_conclusion')),
    status TEXT NOT NULL CHECK (status IN ('algorithm_only', 'candidate_unconfirmed', 'confirmed', 'rejected')),
    label_zh TEXT NOT NULL,
    similarity REAL,
    ppm_error REAL,
    detail_json TEXT,
    basis TEXT,
    operator TEXT NOT NULL,
    created_at TEXT NOT NULL,
    software_version TEXT NOT NULL,
    source_sha256 TEXT
);

CREATE INDEX IF NOT EXISTS idx_conc_dataset ON conclusions(dataset_id);
CREATE INDEX IF NOT EXISTS idx_conc_status ON conclusions(status);
CREATE INDEX IF NOT EXISTS idx_conc_layer ON conclusions(layer);

CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    detail_json TEXT,
    operator TEXT,
    created_at TEXT NOT NULL,
    software_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prov_action ON provenance(action);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
