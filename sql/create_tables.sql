CREATE TABLE IF NOT EXISTS users (
    eth_address VARCHAR PRIMARY KEY,
    payment_address VARCHAR,
    created TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    updated TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    username VARCHAR UNIQUE,
    is_app BOOLEAN DEFAULT FALSE,
    reputation_score DECIMAL,
    review_count INTEGER DEFAULT 0,
    custom JSON
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_lower_username ON users (lower(username));
CREATE INDEX IF NOT EXISTS idx_users_apps ON users (is_app);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token VARCHAR PRIMARY KEY,
    address VARCHAR,
    created TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

UPDATE database_version SET version_number = 5;
