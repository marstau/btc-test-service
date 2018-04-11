ALTER TABLE users RENAME COLUMN is_app TO is_bot;
ALTER TABLE users ADD COLUMN is_groupchatbot BOOLEAN DEFAULT FALSE;
ALTER TABLE users RENAME COLUMN about TO description;

ALTER TABLE app_categories RENAME TO bot_categories;

CREATE INDEX IF NOT EXISTS idx_users_groupchatbots ON users (is_groupchatbot);
