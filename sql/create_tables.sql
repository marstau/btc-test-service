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
    went_public TIMESTAMP WITHOUT TIME ZONE,
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
CREATE INDEX IF NOT EXISTS idx_users_tsv ON users USING gin(tsv);

CREATE INDEX IF NOT EXISTS idx_users_went_public ON users (went_public DESC NULLS LAST);

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

CREATE TABLE IF NOT EXISTS categories (
    category_id SERIAL PRIMARY KEY,
    tag VARCHAR NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS category_names (
    category_id SERIAL REFERENCES categories ON DELETE CASCADE,
    language VARCHAR DEFAULT 'en',
    name VARCHAR NOT NULL,

    PRIMARY KEY(category_id, language)
);

CREATE TABLE IF NOT EXISTS app_categories (
    category_id SERIAL REFERENCES categories ON DELETE CASCADE,
    token_id VARCHAR REFERENCES users ON DELETE CASCADE,

    PRIMARY KEY (category_id, token_id)
);

UPDATE database_version SET version_number = 18;
