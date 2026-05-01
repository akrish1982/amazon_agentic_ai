-- CRM: commercial lending borrowers
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,
    business_name   TEXT NOT NULL,
    ein             TEXT,
    naics_code      TEXT,
    years_in_business INTEGER,
    annual_revenue  REAL,
    credit_score    INTEGER,
    duns_number     TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    state           TEXT,
    relationship_mgr TEXT,
    kyc_status      TEXT CHECK(kyc_status IN ('pending','approved','flagged','expired')),
    aml_flag        INTEGER DEFAULT 0,
    ofac_checked_at TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Loan applications linked to customers
CREATE TABLE IF NOT EXISTS loan_applications (
    app_id          TEXT PRIMARY KEY,
    customer_id     TEXT REFERENCES customers(customer_id),
    loan_type       TEXT CHECK(loan_type IN ('SBA','CRE','C&I','construction','USDA')),
    requested_amount REAL,
    purpose         TEXT,
    collateral_value REAL,
    noi             REAL,
    annual_debt_service REAL,
    status          TEXT CHECK(status IN ('draft','submitted','underwriting','approved','denied','withdrawn')),
    submitted_at    TEXT,
    decided_at      TEXT
);

-- Compliance rules by regulation
CREATE TABLE IF NOT EXISTS compliance_rules (
    rule_id         TEXT PRIMARY KEY,
    regulation      TEXT NOT NULL,
    category        TEXT,
    rule_text       TEXT NOT NULL,
    loan_type       TEXT,          -- NULL means applies to all
    min_loan_amount REAL,
    max_loan_amount REAL,
    borrower_type   TEXT,          -- NULL means applies to all
    severity        TEXT CHECK(severity IN ('mandatory','advisory','informational')),
    effective_date  TEXT,
    source_doc_ref  TEXT
);

-- Ingested policy documents
CREATE TABLE IF NOT EXISTS policy_documents (
    doc_id          TEXT PRIMARY KEY,
    source_key      TEXT NOT NULL UNIQUE,
    filename        TEXT,
    doc_type        TEXT,
    file_size_bytes INTEGER,
    ingested_at     TEXT DEFAULT (datetime('now')),
    s3_key          TEXT,
    checksum        TEXT
);

-- Document metadata tags
CREATE TABLE IF NOT EXISTS document_tags (
    doc_id          TEXT REFERENCES policy_documents(doc_id),
    regulation_refs TEXT,   -- JSON array as string
    loan_types      TEXT,   -- JSON array as string
    effective_date  TEXT,
    expiry_date     TEXT,
    jurisdiction    TEXT,
    risk_tier       TEXT,
    version         TEXT,
    keywords        TEXT,   -- JSON array as string
    tagged_at       TEXT DEFAULT (datetime('now')),
    tag_method      TEXT,   -- 'regex','tfidf','claude'
    PRIMARY KEY (doc_id)
);

-- Vector chunks for RAG
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id        TEXT PRIMARY KEY,
    doc_id          TEXT REFERENCES policy_documents(doc_id),
    chunk_index     INTEGER,
    text            TEXT NOT NULL,
    token_count     INTEGER,
    section_header  TEXT,
    embedding       TEXT,   -- JSON-serialized float list
    indexed_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_tags_risk ON document_tags(risk_tier);
CREATE INDEX IF NOT EXISTS idx_apps_customer ON loan_applications(customer_id);
