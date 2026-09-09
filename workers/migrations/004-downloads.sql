CREATE TABLE IF NOT EXISTS download_tasks (
    task_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS download_status (
    task_id TEXT NOT NULL REFERENCES download_tasks(task_id),
    client_id TEXT NOT NULL,
    download_state TEXT NOT NULL DEFAULT 'pending',
    execution_state TEXT NOT NULL DEFAULT 'not_requested',
    report TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (task_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_download_client ON download_status(client_id, download_state);
