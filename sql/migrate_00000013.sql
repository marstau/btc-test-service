CREATE TABLE IF NOT EXISTS migrations (
    migration_key VARCHAR PRIMARY KEY,
    token_id_orig VARCHAR NOT NULL,
    token_id_new VARCHAR NOT NULL,
    complete BOOLEAN DEFAULT FALSE,

    date TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_migrations_token_id_orig ON migrations (token_id_orig);
