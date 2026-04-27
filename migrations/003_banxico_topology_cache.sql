CREATE TABLE IF NOT EXISTS banxico_topology_member_cache (
    unique_name VARCHAR PRIMARY KEY,
    caption VARCHAR,
    parent_unique_name VARCHAR,
    level SMALLINT,
    raw_type VARCHAR,
    raw_parts_json VARCHAR,
    chapter_unique VARCHAR,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_banxico_topology_member_cache_parent
    ON banxico_topology_member_cache(parent_unique_name);
CREATE INDEX IF NOT EXISTS ix_banxico_topology_member_cache_chapter
    ON banxico_topology_member_cache(chapter_unique);

CREATE TABLE IF NOT EXISTS banxico_topology_edge_cache (
    parent_unique_name VARCHAR NOT NULL,
    child_unique_name VARCHAR NOT NULL,
    chapter_unique VARCHAR,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (parent_unique_name, child_unique_name)
);

CREATE INDEX IF NOT EXISTS ix_banxico_topology_edge_cache_chapter
    ON banxico_topology_edge_cache(chapter_unique);

CREATE TABLE IF NOT EXISTS banxico_topology_frontier_cache (
    metric VARCHAR NOT NULL,
    chapter_unique VARCHAR NOT NULL,
    frontier_unique VARCHAR NOT NULL,
    level SMALLINT,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (metric, frontier_unique)
);

CREATE INDEX IF NOT EXISTS ix_banxico_topology_frontier_cache_metric_chapter
    ON banxico_topology_frontier_cache(metric, chapter_unique);

CREATE TABLE IF NOT EXISTS banxico_topology_meta (
    metric VARCHAR PRIMARY KEY,
    members_count BIGINT DEFAULT 0,
    edges_count BIGINT DEFAULT 0,
    frontier_count BIGINT DEFAULT 0,
    chapters_count BIGINT DEFAULT 0,
    last_refreshed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
