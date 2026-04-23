import json
import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.import_audit import (
        claim_failed_message_for_retry,
        create_import_run,
        finalize_import_run,
        get_import_run,
        get_import_checkpoint,
        list_failed_messages_for_retry,
        list_import_run_items,
        list_import_runs,
        mark_failed_message_failed_final,
        mark_failed_message_pending,
        mark_failed_message_resolved,
        record_import_run_item,
        record_import_run_retry_summary,
        set_import_checkpoint,
    )
except ImportError:
    claim_failed_message_for_retry = None
    create_import_run = None
    finalize_import_run = None
    get_import_run = None
    get_import_checkpoint = None
    list_failed_messages_for_retry = None
    list_import_run_items = None
    list_import_runs = None
    mark_failed_message_failed_final = None
    mark_failed_message_pending = None
    mark_failed_message_resolved = None
    record_import_run_item = None
    record_import_run_retry_summary = None
    set_import_checkpoint = None
    run_pending_migrations = None


class ImportAuditRepositoryTests(unittest.TestCase):
    def test_creates_import_run_with_config_snapshot(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            create_import_run,
            "create_import_run should be importable from newspaper_translator.import_audit",
        )
        self.assertIsNotNone(
            get_import_run,
            "get_import_run should be importable from newspaper_translator.import_audit",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            created_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            stored_run = get_import_run(
                database_url=database_url,
                run_id=created_run.run_id,
            )

        self.assertEqual(stored_run.run_id, created_run.run_id)
        self.assertEqual(stored_run.source_name, "gmail")
        self.assertEqual(stored_run.status, "running")
        self.assertEqual(stored_run.query, "newer_than:7d")
        self.assertEqual(stored_run.allowed_senders, ["briefing@example.com"])
        self.assertEqual(stored_run.max_results, 25)
        self.assertEqual(stored_run.fetched_message_count, 0)
        self.assertEqual(stored_run.imported_attachment_count, 0)
        self.assertEqual(stored_run.created_document_count, 0)
        self.assertEqual(stored_run.skipped_document_count, 0)
        self.assertEqual(stored_run.failed_item_count, 0)
        self.assertEqual(stored_run.skipped_item_count, 0)
        self.assertIsNotNone(stored_run.started_at)
        self.assertIsNone(stored_run.finished_at)

    def test_records_import_items_and_finalizes_partial_run_counts(self) -> None:
        self.assertIsNotNone(record_import_run_item)
        self.assertIsNotNone(finalize_import_run)
        self.assertIsNotNone(list_import_run_items)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            created_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )

            record_import_run_item(
                database_url=database_url,
                run_id=created_run.run_id,
                item_type="message",
                item_key="message:1",
                message_id="message-1",
                attachment_id=None,
                link_url=None,
                status="succeeded",
                detail_code="message_processed",
                detail_message="Message processed successfully.",
                document_key=None,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=created_run.run_id,
                item_type="attachment",
                item_key="message:1:attachment:1",
                message_id="message-1",
                attachment_id="attachment-1",
                link_url=None,
                status="succeeded",
                detail_code="document_created",
                detail_message="Attachment imported into documents.",
                document_key="message-1:attachment-1:abc",
            )
            record_import_run_item(
                database_url=database_url,
                run_id=created_run.run_id,
                item_type="body_link",
                item_key="message:1:link:1",
                message_id="message-1",
                attachment_id=None,
                link_url="https://example.com/paper",
                status="failed",
                detail_code="link_download_failed",
                detail_message="Timed out while downloading link.",
                document_key=None,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=created_run.run_id,
                item_type="attachment",
                item_key="message:1:attachment:2",
                message_id="message-1",
                attachment_id="attachment-2",
                link_url=None,
                status="skipped",
                detail_code="duplicate_document",
                detail_message="Attachment matched an existing document.",
                document_key="message-1:attachment-2:def",
            )

            finalize_import_run(
                database_url=database_url,
                run_id=created_run.run_id,
                fetched_message_count=1,
                imported_attachment_count=2,
                created_document_count=1,
                skipped_document_count=1,
            )

            stored_run = get_import_run(
                database_url=database_url,
                run_id=created_run.run_id,
            )
            stored_items = list_import_run_items(
                database_url=database_url,
                run_id=created_run.run_id,
            )

        self.assertEqual(stored_run.status, "partial")
        self.assertEqual(stored_run.fetched_message_count, 1)
        self.assertEqual(stored_run.imported_attachment_count, 2)
        self.assertEqual(stored_run.created_document_count, 1)
        self.assertEqual(stored_run.skipped_document_count, 1)
        self.assertEqual(stored_run.failed_item_count, 1)
        self.assertEqual(stored_run.skipped_item_count, 1)
        self.assertIsNotNone(stored_run.finished_at)
        self.assertEqual([item.status for item in stored_items], ["succeeded", "succeeded", "failed", "skipped"])

    def test_lists_recent_runs_and_filters_items(self) -> None:
        self.assertIsNotNone(list_import_runs)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            first_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=first_run.run_id,
                item_type="body_link",
                item_key="first:link",
                message_id="message-1",
                attachment_id=None,
                link_url="https://example.com/first",
                status="failed",
                detail_code="link_download_failed",
                detail_message="Download timed out.",
                document_key=None,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=first_run.run_id,
                fetched_message_count=1,
                imported_attachment_count=0,
                created_document_count=0,
                skipped_document_count=0,
            )

            second_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:1d",
                allowed_senders=["briefing@example.com"],
                max_results=10,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=second_run.run_id,
                item_type="attachment",
                item_key="second:attachment",
                message_id="message-2",
                attachment_id="attachment-1",
                link_url=None,
                status="succeeded",
                detail_code="document_created",
                detail_message="Attachment imported.",
                document_key="message-2:attachment-1:abc",
            )
            record_import_run_item(
                database_url=database_url,
                run_id=second_run.run_id,
                item_type="body_link",
                item_key="second:link",
                message_id="message-2",
                attachment_id=None,
                link_url="https://example.com/second",
                status="failed",
                detail_code="link_download_failed",
                detail_message="Link returned 504.",
                document_key=None,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=second_run.run_id,
                fetched_message_count=1,
                imported_attachment_count=1,
                created_document_count=1,
                skipped_document_count=0,
            )

            runs = list_import_runs(database_url=database_url, limit=10)
            failed_items = list_import_run_items(
                database_url=database_url,
                run_id=second_run.run_id,
                status="failed",
            )

        self.assertEqual([run.run_id for run in runs], [second_run.run_id, first_run.run_id])
        self.assertEqual([item.item_key for item in failed_items], ["second:link"])

    def test_sets_and_reads_import_checkpoint(self) -> None:
        self.assertIsNotNone(get_import_checkpoint)
        self.assertIsNotNone(set_import_checkpoint)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            self.assertIsNone(
                get_import_checkpoint(
                    database_url=database_url,
                    source_name="gmail",
                    checkpoint_type="message_internal_date",
                )
            )

            set_import_checkpoint(
                database_url=database_url,
                source_name="gmail",
                checkpoint_type="message_internal_date",
                checkpoint_value="1713820800000",
            )

            checkpoint_value = get_import_checkpoint(
                database_url=database_url,
                source_name="gmail",
                checkpoint_type="message_internal_date",
            )

        self.assertEqual(checkpoint_value, "1713820800000")

    def test_tracks_failed_messages_for_single_retry_resolution_flow(self) -> None:
        self.assertIsNotNone(mark_failed_message_pending)
        self.assertIsNotNone(mark_failed_message_resolved)
        self.assertIsNotNone(mark_failed_message_failed_final)
        self.assertIsNotNone(list_failed_messages_for_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            mark_failed_message_pending(
                database_url=database_url,
                message_id="message-1",
                source_name="gmail",
                message_internal_date="1713820800000",
                run_id="run-1",
            )
            mark_failed_message_pending(
                database_url=database_url,
                message_id="message-2",
                source_name="gmail",
                message_internal_date="1713820900000",
                run_id="run-1",
            )
            mark_failed_message_pending(
                database_url=database_url,
                message_id="message-1",
                source_name="gmail",
                message_internal_date="1713820800000",
                run_id="run-2",
            )

            retryable_before = list_failed_messages_for_retry(
                database_url=database_url,
                source_name="gmail",
            )

            mark_failed_message_resolved(
                database_url=database_url,
                message_id="message-1",
                run_id="run-3",
            )
            mark_failed_message_failed_final(
                database_url=database_url,
                message_id="message-2",
                run_id="run-4",
            )

            retryable_after = list_failed_messages_for_retry(
                database_url=database_url,
                source_name="gmail",
            )

        self.assertEqual(
            [(item.message_id, item.retry_attempt_count) for item in retryable_before],
            [("message-2", 0), ("message-1", 0)],
        )
        self.assertEqual(retryable_after, [])

    def test_claims_failed_message_for_single_retry_attempt(self) -> None:
        self.assertIsNotNone(claim_failed_message_for_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            mark_failed_message_pending(
                database_url=database_url,
                message_id="message-1",
                source_name="gmail",
                message_internal_date="1713820800000",
                run_id="run-1",
            )

            first_claim = claim_failed_message_for_retry(
                database_url=database_url,
                message_id="message-1",
                run_id="run-2",
            )
            retryable_after_first_claim = list_failed_messages_for_retry(
                database_url=database_url,
                source_name="gmail",
            )
            second_claim = claim_failed_message_for_retry(
                database_url=database_url,
                message_id="message-1",
                run_id="run-3",
            )

        self.assertTrue(first_claim)
        self.assertEqual(retryable_after_first_claim, [])
        self.assertFalse(second_claim)

    def test_records_retry_summary_on_parent_import_run(self) -> None:
        self.assertIsNotNone(record_import_run_retry_summary)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            parent_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
                checkpoint_before="1713820800000",
            )
            finalize_import_run(
                database_url=database_url,
                run_id=parent_run.run_id,
                fetched_message_count=2,
                imported_attachment_count=1,
                created_document_count=1,
                skipped_document_count=0,
                checkpoint_after="1713907200000",
            )

            record_import_run_retry_summary(
                database_url=database_url,
                run_id=parent_run.run_id,
                retry_run_id="retry-run-1",
                retried_message_count=2,
                resolved_message_count=1,
                failed_final_message_count=1,
            )
            stored_run = get_import_run(
                database_url=database_url,
                run_id=parent_run.run_id,
            )

        self.assertTrue(stored_run.retry_performed)
        self.assertEqual(stored_run.retry_run_id, "retry-run-1")
        self.assertEqual(stored_run.retried_message_count, 2)
        self.assertEqual(stored_run.resolved_message_count, 1)
        self.assertEqual(stored_run.failed_final_message_count, 1)
        self.assertEqual(stored_run.checkpoint_before, "1713820800000")
        self.assertEqual(stored_run.checkpoint_after, "1713907200000")


if __name__ == "__main__":
    unittest.main()
