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
