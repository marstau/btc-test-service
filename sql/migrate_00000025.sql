CREATE TABLE IF NOT EXISTS dapps (
    dapp_id BIGINT PRIMARY KEY,
    name VARCHAR,
    url VARCHAR,
    description VARCHAR,
    avatar VARCHAR,
    created TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    updated TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);
