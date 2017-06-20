CREATE TABLE IF NOT EXISTS users (
    token_id VARCHAR PRIMARY KEY,
    payment_address VARCHAR,
    created TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    updated TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    username VARCHAR UNIQUE,
    name VARCHAR,
    avatar VARCHAR,
    about VARCHAR,
    location VARCHAR,
    reputation_score DECIMAL,
    review_count INTEGER DEFAULT 0,
    is_public BOOLEAN DEFAULT FALSE,
    tsv TSVECTOR,
    -- APP specific details
    is_app BOOLEAN DEFAULT FALSE,
    featured BOOLEAN DEFAULT FALSE,
    -- whether or not the app has been blocked from
    -- showing up on the app store page
    blocked BOOLEAN DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_lower_username ON users (lower(username));
CREATE INDEX IF NOT EXISTS idx_users_apps ON users (is_app);
CREATE INDEX IF NOT EXISTS  idx_users_tsv ON users USING gin(tsv);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token VARCHAR PRIMARY KEY,
    address VARCHAR,
    created TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE FUNCTION users_search_trigger() RETURNS TRIGGER AS $$
BEGIN
    NEW.tsv :=
        SETWEIGHT(TO_TSVECTOR(COALESCE(NEW.name, '')), 'A') ||
        SETWEIGHT(TO_TSVECTOR(COALESCE(NEW.username, '')), 'C');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
ON users FOR EACH ROW EXECUTE PROCEDURE users_search_trigger();

CREATE TABLE IF NOT EXISTS avatars (
    token_id VARCHAR PRIMARY KEY,
    img BYTEA,
    hash VARCHAR,
    format VARCHAR NOT NULL,
    last_modified TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE TABLE IF NOT EXISTS reports (
    report_id SERIAL PRIMARY KEY,
    reporter_token_id VARCHAR,
    reportee_token_id VARCHAR,
    details VARCHAR,
    date TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

-- used for keeping track of user token_id migrations
CREATE TABLE IF NOT EXISTS migrations (
    migration_key VARCHAR PRIMARY KEY,
    token_id_orig VARCHAR NOT NULL,
    token_id_new VARCHAR NOT NULL,
    complete BOOLEAN DEFAULT FALSE,

    date TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_migrations_token_id_orig ON migrations (token_id_orig);
CREATE INDEX IF NOT EXISTS idx_migrations_token_id_new ON migrations (token_id_new);

UPDATE database_version SET version_number = 15;
