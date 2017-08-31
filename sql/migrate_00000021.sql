ALTER TABLE users ADD COLUMN websocket_connection_count INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_users_apps_websocket_connection_count ON users (is_app, websocket_connection_count);
