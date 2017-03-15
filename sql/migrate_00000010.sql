DROP TRIGGER tsvectorupdate ON users;
DROP FUNCTION users_search_trigger();

ALTER TABLE users ADD COLUMN name VARCHAR;
ALTER TABLE users ADD COLUMN avatar VARCHAR;
ALTER TABLE users ADD COLUMN about VARCHAR;
ALTER TABLE users ADD COLUMN location VARCHAR;

UPDATE users SET name = custom->>'name';
UPDATE users SET avatar = custom->>'avatar';
UPDATE users SET about = custom->>'about';
UPDATE users SET location = custom->>'location';

ALTER TABLE users DROP COLUMN custom;

UPDATE users SET tsv = SETWEIGHT(TO_TSVECTOR(COALESCE(name, '')), 'A') || SETWEIGHT(TO_TSVECTOR(COALESCE(username, '')), 'C');

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
