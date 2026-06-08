import multiprocessing
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
except ImportError:
    run_pending_migrations = None


def _concurrent_migration_worker(
    database_url: str, ready_dir: str, worker_count: int, index: int
) -> str | None:
    """Run migrations in a separate process, started near-simultaneously with peers
    via a filesystem barrier. Returns the error repr if migration raised, else None.

    Defined at module level so it is importable by the ``spawn`` start method.
    """
    ready = pathlib.Path(ready_dir)
    (ready / f"ready-{index}").write_text("1")
    deadline = time.time() + 30
    while len(list(ready.glob("ready-*"))) < worker_count and time.time() < deadline:
        time.sleep(0.005)

    from newspaper_translator.database import run_pending_migrations as _run

    try:
        _run(database_url)
        return None
    except Exception as exc:  # noqa: BLE001 - reported back for assertion
        return repr(exc)


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
                "0012_article_enrichment_classification",
                "0013_documents_source_metadata",
                "0014_mineru_page_parse_state",
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

    def test_applies_documents_source_metadata_schema_migration(self) -> None:
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
                document_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(documents)")
                }
                document_index_names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(documents)")
                }
            finally:
                connection.close()

        self.assertIn("0013_documents_source_metadata", applied_versions)
        self.assertIn("source_message_internal_date", document_columns)
        self.assertIn("idx_documents_content_hash", document_index_names)

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
                "0012_article_enrichment_classification",
                "0013_documents_source_metadata",
                "0014_mineru_page_parse_state",
            ],
        )

    def test_article_enrichment_outputs_has_classification_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            connection = sqlite3.connect(database_path)
            try:
                columns = [
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(article_enrichment_outputs)"
                    ).fetchall()
                ]
            finally:
                connection.close()

        self.assertIn("content_type", columns)
        self.assertIn("classification_reason", columns)


class ConcurrentMigrationTests(unittest.TestCase):
    def test_concurrent_first_boot_migrations_do_not_collide(self) -> None:
        """Multiple services starting at once against a fresh shared SQLite DB must
        not double-apply migrations (which raised 'duplicate column name')."""
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        worker_count = 8
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            ready_dir = pathlib.Path(temp_dir) / "ready"
            ready_dir.mkdir()

            arguments = [
                (database_url, str(ready_dir), worker_count, index)
                for index in range(worker_count)
            ]
            with context.Pool(worker_count) as pool:
                results = pool.starmap(_concurrent_migration_worker, arguments)
            errors = [result for result in results if result is not None]

            connection = sqlite3.connect(database_path)
            try:
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertEqual(errors, [], f"concurrent migrations raised: {errors}")
        self.assertEqual(
            len(recorded_versions),
            len(set(recorded_versions)),
            f"a migration was recorded more than once: {recorded_versions}",
        )
        self.assertIn("0001_initial", recorded_versions)
        self.assertIn("0003_checkpointing_retry", recorded_versions)

    def test_rerunning_migrations_on_existing_database_is_noop(self) -> None:
        """A normal restart (DB already migrated) applies nothing new and never errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            first_applied = run_pending_migrations(database_url)
            second_applied = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0001_initial", first_applied)
        self.assertEqual(second_applied, [])
        self.assertEqual(len(recorded_versions), len(set(recorded_versions)))


if __name__ == "__main__":
    unittest.main()
