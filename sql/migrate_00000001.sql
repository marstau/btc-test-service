CREATE UNIQUE INDEX IF NOT EXISTS idx_users_lower_username ON users (lower(username));
