-- Addresses the Manager has handed out. Mail to anything else is rejected.
CREATE TABLE addresses (
  address    TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

-- Received mail. `seq` only ever grows, so the Manager can ask "everything after N".
CREATE TABLE messages (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  id          TEXT NOT NULL UNIQUE,
  address     TEXT NOT NULL,
  from_addr   TEXT,
  from_name   TEXT,
  subject     TEXT,
  text        TEXT,
  html        TEXT,
  received_at TEXT NOT NULL
);
CREATE INDEX idx_messages_address ON messages(address);
CREATE INDEX idx_messages_received ON messages(received_at);
