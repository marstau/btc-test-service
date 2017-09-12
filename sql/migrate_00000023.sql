-- clean out super legacy avatars
DELETE FROM avatars WHERE hash IS NULL;

ALTER TABLE avatars DROP CONSTRAINT avatars_pkey;
ALTER TABLE avatars ADD PRIMARY KEY (toshi_id, hash);

CREATE INDEX IF NOT EXISTS idx_avatars_toshi_id_hash_substr ON avatars (toshi_id, substring(hash for 6));
CREATE INDEX IF NOT EXISTS idx_avatars_toshi_id_format_hash_substr ON avatars (toshi_id, format, substring(hash for 6));
CREATE INDEX IF NOT EXISTS idx_avatars_toshi_id_last_modified ON avatars (toshi_id, last_modified DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_avatars_toshi_id_format_last_modified ON avatars (toshi_id, format, last_modified DESC NULLS LAST);
