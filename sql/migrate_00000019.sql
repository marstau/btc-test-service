ALTER TABLE users RENAME COLUMN token_id TO toshi_id;
ALTER TABLE avatars RENAME COLUMN token_id TO toshi_id;
ALTER TABLE reports RENAME COLUMN reporter_token_id TO reporter_toshi_id;
ALTER TABLE reports RENAME COLUMN reportee_token_id TO reportee_toshi_id;
ALTER TABLE app_categories RENAME COLUMN token_id TO toshi_id;
