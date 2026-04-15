CREATE TABLE IF NOT EXISTS dim_country (
    country_key BIGINT PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    iso3 VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_country_name ON dim_country(canonical_name);

CREATE TABLE IF NOT EXISTS dim_flow (
    flow_key BIGINT PRIMARY KEY,
    flow_code VARCHAR NOT NULL,
    flow_name VARCHAR NOT NULL
);

INSERT OR IGNORE INTO dim_flow VALUES
    (1, 'IMPORT', 'Importación'),
    (2, 'EXPORT', 'Exportación');

CREATE TABLE IF NOT EXISTS dim_source (
    source_key BIGINT PRIMARY KEY,
    source_code VARCHAR NOT NULL,
    source_name VARCHAR NOT NULL,
    source_url VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_source_code ON dim_source(source_code);

CREATE TABLE IF NOT EXISTS load_run (
    load_run_id BIGINT PRIMARY KEY,
    source_code VARCHAR NOT NULL,
    mode VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    records_read BIGINT DEFAULT 0,
    records_loaded BIGINT DEFAULT 0,
    message VARCHAR,
    artifact_path VARCHAR
);

CREATE TABLE IF NOT EXISTS fact_trade_monthly (
    date_month DATE NOT NULL,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    flow_code VARCHAR NOT NULL,
    country_name VARCHAR NOT NULL,
    country_iso3 VARCHAR,
    tariff_code VARCHAR NOT NULL,
    tariff_level SMALLINT NOT NULL,
    hs2 VARCHAR,
    hs4 VARCHAR,
    hs6 VARCHAR,
    fraccion8 VARCHAR,
    nico10 VARCHAR,
    tariff_description VARCHAR,
    unit_name VARCHAR,
    quantity DOUBLE,
    value_usd DOUBLE,
    source_code VARCHAR NOT NULL,
    source_file VARCHAR,
    source_revision VARCHAR,
    load_run_id BIGINT,
    record_hash VARCHAR NOT NULL,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date_month, flow_code, country_name, tariff_code, source_code)
);

CREATE INDEX IF NOT EXISTS ix_fact_trade_monthly_date ON fact_trade_monthly(date_month);
CREATE INDEX IF NOT EXISTS ix_fact_trade_monthly_flow ON fact_trade_monthly(flow_code);
CREATE INDEX IF NOT EXISTS ix_fact_trade_monthly_country ON fact_trade_monthly(country_name);
CREATE INDEX IF NOT EXISTS ix_fact_trade_monthly_nico10 ON fact_trade_monthly(nico10);
CREATE INDEX IF NOT EXISTS ix_fact_trade_monthly_fraccion8 ON fact_trade_monthly(fraccion8);
CREATE INDEX IF NOT EXISTS ix_fact_trade_monthly_hs6 ON fact_trade_monthly(hs6);

CREATE TABLE IF NOT EXISTS fact_trade_monthly_history AS
SELECT * FROM fact_trade_monthly WHERE 1=0;

CREATE TABLE IF NOT EXISTS etl_file_registry (
    file_path VARCHAR PRIMARY KEY,
    parser_name VARCHAR NOT NULL,
    file_hash VARCHAR NOT NULL,
    processed_at TIMESTAMP NOT NULL,
    load_run_id BIGINT
);

CREATE TABLE IF NOT EXISTS etl_error_log (
    error_id BIGINT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context VARCHAR,
    file_path VARCHAR,
    error_message VARCHAR,
    traceback VARCHAR
);

CREATE OR REPLACE VIEW v_trade_monthly_latest AS
SELECT
    date_month,
    year,
    month,
    flow_code,
    country_name,
    country_iso3,
    tariff_code,
    tariff_level,
    hs2,
    hs4,
    hs6,
    fraccion8,
    nico10,
    tariff_description,
    unit_name,
    quantity,
    value_usd,
    source_code,
    source_file,
    source_revision,
    load_run_id,
    inserted_at,
    updated_at
FROM fact_trade_monthly;
