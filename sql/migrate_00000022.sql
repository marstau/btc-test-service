ALTER TABLE users DROP COLUMN websocket_connection_count;

CREATE TABLE IF NOT EXISTS websocket_sessions (
    websocket_session_id VARCHAR PRIMARY KEY,
    toshi_id VARCHAR NOT NULL,
    last_seen TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_websocket_sessions_toshi_id ON websocket_sessions (toshi_id);
CREATE INDEX IF NOT EXISTS idx_websocket_sessions_last_seen ON websocket_sessions (last_seen DESC);
