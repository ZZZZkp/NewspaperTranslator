import pathlib
import sqlite3
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
except ImportError:
    run_pending_migrations = None


class DatabaseMigrationTests(unittest.TestCase):
    def test_backfills_document_processing_runs_before_dropping_legacy_queue(
        self,
    ) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                for migration_path in sorted(
                    (SRC_ROOT / "newspaper_translator" / "migrations").glob("*.sql")
                ):
                    if migration_path.stem > "0010_article_processing_runs":
                        continue
                    connection.executescript(migration_path.read_text())
                    connection.execute(
                        """
                        INSERT INTO schema_migrations (version, applied_at)
                        VALUES (?, CURRENT_TIMESTAMP)
                        """,
                        (migration_path.stem,),
                    )

                connection.executemany(
                    """
                    INSERT INTO documents (
                        document_key,
                        source_name,
                        source_message_id,
                        source_attachment_id,
                        sender,
                        original_filename,
                        content_hash,
                        raw_path,
                        import_status
                    )
                    VALUES (?, 'gmail', ?, ?, 'briefing@example.com', ?, ?, ?, 'imported')
                    """,
                    [
                        (
                            "doc-existing",
                            "message-existing",
                            "attachment-existing",
                            "existing.pdf",
                            "hash-existing",
                            "/tmp/existing.pdf",
                        ),
                        (
                            "doc-missing",
                            "message-missing",
                            "attachment-missing",
                            "missing.pdf",
                            "hash-missing",
                            "/tmp/missing.pdf",
                        ),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO processing_tasks (task_name, status)
                    VALUES (?, 'pending')
                    """,
                    [
                        ("process-document:doc-existing",),
                        ("process-document:doc-missing",),
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO document_processing_runs (
                        processing_run_id,
                        document_key,
                        status,
                        current_step,
                        automatic_failure_count,
                        last_error_message
                    )
                    VALUES (
                        'existing-run:doc-existing',
                        'doc-existing',
                        'failed',
                        'extract_articles',
                        2,
                        'keep me'
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                processing_tasks_exists = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'processing_tasks'
                    """
                ).fetchone()[0]
                run_rows = {
                    row[0]: row[1:]
                    for row in connection.execute(
                        """
                        SELECT
                            document_key,
                            processing_run_id,
                            status,
                            current_step,
                            automatic_failure_count,
                            last_error_message
                        FROM document_processing_runs
                        ORDER BY document_key
                        """
                    )
                }
            finally:
                connection.close()

        self.assertEqual(processing_tasks_exists, 0)
        self.assertEqual(set(run_rows), {"doc-existing", "doc-missing"})
        self.assertEqual(
            run_rows["doc-missing"][:3],
            ("legacy-processing-task:doc-missing", "pending", "parse_persist"),
        )
        self.assertEqual(
            run_rows["doc-existing"],
            (
                "existing-run:doc-existing",
                "failed",
                "extract_articles",
                2,
                "keep me",
            ),
        )

    def test_applies_initial_schema_migration_to_sqlite_database(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0001_initial", applied_versions)
        self.assertIn("schema_migrations", table_names)
        self.assertIn("documents", table_names)
        self.assertNotIn("processing_tasks", table_names)
        self.assertIn("0001_initial", recorded_versions)

    def test_applies_import_audit_schema_migration_to_sqlite_database(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0002_import_audit", applied_versions)
        self.assertIn("import_runs", table_names)
        self.assertIn("import_run_items", table_names)
        self.assertIn("0002_import_audit", recorded_versions)

    def test_applies_checkpoint_and_retry_schema_migration_to_sqlite_database(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                import_runs_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(import_runs)")
                }
                import_run_items_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(import_run_items)")
                }
                failed_messages_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(failed_messages)")
                }
                import_checkpoints_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(import_checkpoints)")
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0003_checkpointing_retry", applied_versions)
        self.assertIn("failed_messages", table_names)
        self.assertIn("import_checkpoints", table_names)
        self.assertIn("checkpoint_before", import_runs_columns)
        self.assertIn("checkpoint_after", import_runs_columns)
        self.assertIn("retry_performed", import_runs_columns)
        self.assertIn("retry_run_id", import_runs_columns)
        self.assertIn("retried_message_count", import_runs_columns)
        self.assertIn("resolved_message_count", import_runs_columns)
        self.assertIn("failed_final_message_count", import_runs_columns)
        self.assertIn("message_internal_date", import_run_items_columns)
        self.assertIn("retry_state", failed_messages_columns)
        self.assertIn("retry_attempt_count", failed_messages_columns)
        self.assertIn("checkpoint_value", import_checkpoints_columns)
        self.assertEqual(
            recorded_versions,
            [
                "0001_initial",
                "0002_import_audit",
                "0003_checkpointing_retry",
                "0004_import_run_retry_summary",
                "0005_article_persistence_enrichment",
                "0006_scheduled_automatic_document_processing",
                "0007_article_images",
                "0008_article_fragment_page_numbers",
                "0009_final_articles_article_key",
                "0010_article_processing_runs",
                "0011_drop_processing_tasks",
            ],
        )

    def test_applies_scheduled_automatic_processing_schema_migration(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                scheduler_runs_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(scheduler_runs)")
                }
                document_processing_runs_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(document_processing_runs)"
                    )
                }
                article_processing_runs_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(article_processing_runs)"
                    )
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0006_scheduled_automatic_document_processing", applied_versions)
        self.assertIn("scheduler_runs", table_names)
        self.assertIn("document_processing_runs", table_names)
        self.assertIn("article_processing_runs", table_names)
        self.assertIn("scheduler_run_id", scheduler_runs_columns)
        self.assertIn("trigger_type", scheduler_runs_columns)
        self.assertIn("document_key", document_processing_runs_columns)
        self.assertIn("automatic_failure_count", document_processing_runs_columns)
        self.assertIn("locked_by", document_processing_runs_columns)
        self.assertIn("article_key", article_processing_runs_columns)
        self.assertIn("article_id", article_processing_runs_columns)
        self.assertIn("current_step", article_processing_runs_columns)
        self.assertIn("0006_scheduled_automatic_document_processing", recorded_versions)

    def test_applies_article_persistence_and_enrichment_schema_migration(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                parse_runs_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(parse_runs)")
                }
                article_fragments_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(article_fragments)")
                }
                final_articles_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(final_articles)")
                }
                enrichment_runs_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(article_enrichment_runs)"
                    )
                }
                index_names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(parse_runs)")
                }
                final_articles_index_names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(final_articles)")
                }
                enrichment_index_names = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA index_list(article_enrichment_runs)"
                    )
                }
                article_tags_index_names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(article_tags)")
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0009_final_articles_article_key", applied_versions)
        self.assertIn("parse_runs", table_names)
        self.assertIn("article_fragments", table_names)
        self.assertIn("continuation_matches", table_names)
        self.assertIn("final_articles", table_names)
        self.assertIn("final_article_fragments", table_names)
        self.assertIn("article_enrichment_runs", table_names)
        self.assertIn("article_enrichment_outputs", table_names)
        self.assertIn("article_tags", table_names)
        self.assertIn("publication_date", parse_runs_columns)
        self.assertIn("document_key", parse_runs_columns)
        self.assertIn("page_number", article_fragments_columns)
        self.assertIn("article_key", final_articles_columns)
        self.assertIn("title_en", final_articles_columns)
        self.assertIn("body_text_en", final_articles_columns)
        self.assertIn("input_hash", enrichment_runs_columns)
        self.assertIn("idx_parse_runs_document_key_status_finished_at", index_names)
        self.assertIn("idx_final_articles_parse_run_id_article_order", final_articles_index_names)
        self.assertIn("idx_final_articles_publication_date_article_order", final_articles_index_names)
        self.assertIn("idx_article_enrichment_runs_article_id_status_finished_at", enrichment_index_names)
        self.assertIn("idx_article_tags_enrichment_run_id_tag_order", article_tags_index_names)
        self.assertIn("idx_article_tags_tag_text", article_tags_index_names)
        self.assertEqual(
            recorded_versions,
            [
                "0001_initial",
                "0002_import_audit",
                "0003_checkpointing_retry",
                "0004_import_run_retry_summary",
                "0005_article_persistence_enrichment",
                "0006_scheduled_automatic_document_processing",
                "0007_article_images",
                "0008_article_fragment_page_numbers",
                "0009_final_articles_article_key",
                "0010_article_processing_runs",
                "0011_drop_processing_tasks",
            ],
        )


if __name__ == "__main__":
    unittest.main()
