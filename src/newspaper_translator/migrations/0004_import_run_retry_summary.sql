ALTER TABLE import_runs ADD COLUMN retry_performed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_runs ADD COLUMN retry_run_id TEXT;
ALTER TABLE import_runs ADD COLUMN retried_message_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_runs ADD COLUMN resolved_message_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_runs ADD COLUMN failed_final_message_count INTEGER NOT NULL DEFAULT 0;
