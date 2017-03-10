
ALTER TABLE users ADD COLUMN tsv tsvector;
CREATE INDEX IF NOT EXISTS idx_users_tsv ON users USING gin(tsv);

UPDATE users SET tsv = SETWEIGHT(TO_TSVECTOR(COALESCE(custom->>'name', '')), 'A') || SETWEIGHT(TO_TSVECTOR(COALESCE(username, '')), 'C');

CREATE FUNCTION users_search_trigger() RETURNS TRIGGER AS $$
BEGIN
    NEW.tsv :=
        SETWEIGHT(TO_TSVECTOR(COALESCE(NEW.custom->>'name', '')), 'A') ||
        SETWEIGHT(TO_TSVECTOR(COALESCE(NEW.username, '')), 'C');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
ON users FOR EACH ROW EXECUTE PROCEDURE users_search_trigger();
