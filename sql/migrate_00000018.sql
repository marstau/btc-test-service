ALTER TABLE users ADD COLUMN went_public TIMESTAMP WITHOUT TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_users_went_public ON users (went_public DESC NULLS LAST);
