INSERT OR IGNORE INTO document_processing_runs (
    processing_run_id,
    document_key,
    status,
    current_step
)
SELECT
    'legacy-processing-task:' || document_key,
    document_key,
    'pending',
    'parse_persist'
FROM documents;

DROP TABLE IF EXISTS processing_tasks;
