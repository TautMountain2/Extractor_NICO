CREATE TABLE IF NOT EXISTS dim_nico_catalog (
    nico10 VARCHAR PRIMARY KEY,
    fraccion8 VARCHAR NOT NULL,
    nico VARCHAR NOT NULL,
    description VARCHAR,
    source_file VARCHAR,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_dim_nico_catalog_fraccion8 ON dim_nico_catalog(fraccion8);
