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
    import newspaper_translator.ingestion as ingestion_module
    from newspaper_translator.ingestion import (
        GmailAttachment,
        GmailMessage,
        import_selected_messages,
        import_gmail_pdf_attachment,
        select_target_messages,
    )
except ImportError:
    run_pending_migrations = None
    ingestion_module = None
    GmailAttachment = None
    GmailMessage = None
    import_selected_messages = None
    import_gmail_pdf_attachment = None
    select_target_messages = None


class IngestionSelectionTests(unittest.TestCase):
    def test_selects_only_messages_from_configured_senders_with_pdf_attachments(self) -> None:
        self.assertIsNotNone(
            GmailAttachment,
            "GmailAttachment should be importable from newspaper_translator.ingestion",
        )
        self.assertIsNotNone(
            GmailMessage,
            "GmailMessage should be importable from newspaper_translator.ingestion",
        )
        self.assertIsNotNone(
            select_target_messages,
            "select_target_messages should be importable from newspaper_translator.ingestion",
        )

        matching_message = GmailMessage(
            message_id="message-1",
            sender="briefing@example.com",
            attachments=[
                GmailAttachment(
                    attachment_id="attachment-1",
                    filename="daily-paper.pdf",
                    mime_type="application/pdf",
                )
            ],
        )
        wrong_sender_message = GmailMessage(
            message_id="message-2",
            sender="other@example.com",
            attachments=[
                GmailAttachment(
                    attachment_id="attachment-2",
                    filename="daily-paper.pdf",
                    mime_type="application/pdf",
                )
            ],
        )
        no_pdf_message = GmailMessage(
            message_id="message-3",
            sender="briefing@example.com",
            attachments=[
                GmailAttachment(
                    attachment_id="attachment-3",
                    filename="daily-paper.txt",
                    mime_type="text/plain",
                )
            ],
        )

        selected = select_target_messages(
            messages=[matching_message, wrong_sender_message, no_pdf_message],
            allowed_senders={"briefing@example.com"},
        )

        self.assertEqual(selected, [matching_message])

    def test_imports_a_pdf_attachment_into_raw_storage_and_document_metadata(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_gmail_pdf_attachment,
            "import_gmail_pdf_attachment should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[],
            )
            attachment = GmailAttachment(
                attachment_id="attachment-1",
                filename="daily-paper.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 sample content",
            )

            result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_document = connection.execute(
                    """
                    SELECT
                        source_name,
                        source_message_id,
                        source_attachment_id,
                        sender,
                        original_filename,
                        content_hash,
                        raw_path,
                        import_status
                    FROM documents
                    WHERE document_key = ?
                    """,
                    (result.document_key,),
                ).fetchone()
                stored_processing_run = connection.execute(
                    """
                    SELECT document_key, status, current_step
                    FROM document_processing_runs
                    WHERE document_key = ?
                    """,
                    (result.document_key,),
                ).fetchone()
            finally:
                connection.close()

            self.assertTrue(result.raw_path.exists())
            self.assertEqual(result.raw_path.read_bytes(), b"%PDF-1.7 sample content")

        self.assertTrue(result.was_created)
        self.assertEqual(
            stored_document,
            (
                "daily-paper",
                "message-1",
                "attachment-1",
                "briefing@example.com",
                "daily-paper.pdf",
                result.content_hash,
                str(result.raw_path),
                "imported",
            ),
        )
        self.assertEqual(
            stored_processing_run,
            (result.document_key, "pending", "parse_persist"),
        )

    def test_skips_duplicate_pdf_imports_for_the_same_attachment_payload(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_gmail_pdf_attachment,
            "import_gmail_pdf_attachment should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[],
            )
            attachment = GmailAttachment(
                attachment_id="attachment-1",
                filename="daily-paper.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 sample content",
            )

            first_result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )
            second_result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
                processing_run_count = connection.execute(
                    "SELECT COUNT(*) FROM document_processing_runs"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertTrue(first_result.was_created)
        self.assertFalse(second_result.was_created)
        self.assertEqual(first_result.document_key, second_result.document_key)
        self.assertEqual(first_result.raw_path, second_result.raw_path)
        self.assertEqual(document_count, 1)
        self.assertEqual(processing_run_count, 1)

    def test_import_stores_filename_prefix_and_message_internal_date(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_gmail_pdf_attachment)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[],
                internal_date="1778083200000",
            )
            attachment = GmailAttachment(
                attachment_id="attachment-1",
                filename="金融时报-5-6.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 ft content",
            )

            result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_row = connection.execute(
                    """
                    SELECT source_name, original_filename, source_message_internal_date
                    FROM documents
                    WHERE document_key = ?
                    """,
                    (result.document_key,),
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(
            stored_row,
            ("金融时报", "金融时报-5-6.pdf", "1778083200000"),
        )

    def test_reuses_existing_document_for_same_pdf_bytes_from_different_messages(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_gmail_pdf_attachment)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            first_result = import_gmail_pdf_attachment(
                message=GmailMessage(
                    message_id="message-1",
                    sender="briefing@example.com",
                    attachments=[],
                    internal_date="1778083200000",
                ),
                attachment=GmailAttachment(
                    attachment_id="attachment-1",
                    filename="金融时报-5-6.pdf",
                    mime_type="application/pdf",
                    content_bytes=b"%PDF-1.7 same content",
                ),
                storage_root=storage_root,
                database_url=database_url,
            )
            second_result = import_gmail_pdf_attachment(
                message=GmailMessage(
                    message_id="message-2",
                    sender="briefing@example.com",
                    attachments=[],
                    internal_date="1778169600000",
                ),
                attachment=GmailAttachment(
                    attachment_id="attachment-9",
                    filename="FT-5-6.pdf",
                    mime_type="application/pdf",
                    content_bytes=b"%PDF-1.7 same content",
                ),
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_rows = connection.execute(
                    """
                    SELECT document_key, source_name, original_filename, source_message_internal_date
                    FROM documents
                    ORDER BY created_at, rowid
                    """
                ).fetchall()
                processing_run_count = connection.execute(
                    "SELECT COUNT(*) FROM document_processing_runs"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertTrue(first_result.was_created)
        self.assertFalse(second_result.was_created)
        self.assertEqual(first_result.document_key, second_result.document_key)
        self.assertEqual(
            document_rows,
            [(first_result.document_key, "金融时报", "金融时报-5-6.pdf", "1778083200000")],
        )
        self.assertEqual(processing_run_count, 1)

    def test_uses_full_filename_stem_when_no_trailing_date_segment_exists(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_gmail_pdf_attachment)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            result = import_gmail_pdf_attachment(
                message=GmailMessage(
                    message_id="message-3",
                    sender="briefing@example.com",
                    attachments=[],
                    internal_date="1778256000000",
                ),
                attachment=GmailAttachment(
                    attachment_id="attachment-3",
                    filename="special-edition.pdf",
                    mime_type="application/pdf",
                    content_bytes=b"%PDF-1.7 no date",
                ),
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_source_name = connection.execute(
                    "SELECT source_name FROM documents WHERE document_key = ?",
                    (result.document_key,),
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(stored_source_name, "special-edition")

    def test_keeps_full_filename_stem_when_trailing_month_day_is_not_a_real_date(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_gmail_pdf_attachment)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            result = import_gmail_pdf_attachment(
                message=GmailMessage(
                    message_id="message-4",
                    sender="briefing@example.com",
                    attachments=[],
                    internal_date="1778342400000",
                ),
                attachment=GmailAttachment(
                    attachment_id="attachment-4",
                    filename="news-24-7.pdf",
                    mime_type="application/pdf",
                    content_bytes=b"%PDF-1.7 invalid month day",
                ),
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_source_name = connection.execute(
                    "SELECT source_name FROM documents WHERE document_key = ?",
                    (result.document_key,),
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(stored_source_name, "news-24-7")

    def test_keeps_full_filename_stem_when_trailing_year_month_day_is_not_a_real_date(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_gmail_pdf_attachment)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            result = import_gmail_pdf_attachment(
                message=GmailMessage(
                    message_id="message-5",
                    sender="briefing@example.com",
                    attachments=[],
                    internal_date="1778428800000",
                ),
                attachment=GmailAttachment(
                    attachment_id="attachment-5",
                    filename="paper-2024-13-40.pdf",
                    mime_type="application/pdf",
                    content_bytes=b"%PDF-1.7 invalid full date",
                ),
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_source_name = connection.execute(
                    "SELECT source_name FROM documents WHERE document_key = ?",
                    (result.document_key,),
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(stored_source_name, "paper-2024-13-40")

    def test_retry_creates_missing_processing_run_after_enqueue_failure(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            ingestion_module,
            "newspaper_translator.ingestion should be importable",
        )
        self.assertIsNotNone(
            import_gmail_pdf_attachment,
            "import_gmail_pdf_attachment should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[],
            )
            attachment = GmailAttachment(
                attachment_id="attachment-1",
                filename="daily-paper.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 sample content",
            )

            original_create_processing_run = ingestion_module.create_document_processing_run

            def fail_processing_run_creation(**_kwargs) -> None:
                raise RuntimeError("enqueue unavailable")

            ingestion_module.create_document_processing_run = fail_processing_run_creation
            try:
                with self.assertRaisesRegex(RuntimeError, "enqueue unavailable"):
                    import_gmail_pdf_attachment(
                        message=message,
                        attachment=attachment,
                        storage_root=storage_root,
                        database_url=database_url,
                    )
            finally:
                ingestion_module.create_document_processing_run = original_create_processing_run

            retry_result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
                stored_processing_run = connection.execute(
                    """
                    SELECT document_key, status, current_step
                    FROM document_processing_runs
                    WHERE document_key = ?
                    """,
                    (retry_result.document_key,),
                ).fetchone()
            finally:
                connection.close()

        self.assertFalse(retry_result.was_created)
        self.assertEqual(document_count, 1)
        self.assertEqual(
            stored_processing_run,
            (retry_result.document_key, "pending", "parse_persist"),
        )

    def test_import_selected_messages_persists_only_matching_pdf_attachments(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_selected_messages,
            "import_selected_messages should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            matching_message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[
                    GmailAttachment(
                        attachment_id="attachment-1",
                        filename="daily-paper.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 first",
                    ),
                    GmailAttachment(
                        attachment_id="attachment-2",
                        filename="notes.txt",
                        mime_type="text/plain",
                        content_bytes=b"not a pdf",
                    ),
                ],
            )
            wrong_sender_message = GmailMessage(
                message_id="message-2",
                sender="other@example.com",
                attachments=[
                    GmailAttachment(
                        attachment_id="attachment-3",
                        filename="other-paper.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 second",
                    )
                ],
            )

            results = import_selected_messages(
                messages=[matching_message, wrong_sender_message],
                allowed_senders={"briefing@example.com"},
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].document_key, "message-1:attachment-1:" + results[0].content_hash)
        self.assertEqual(document_count, 1)

    def test_import_selected_messages_skips_known_translated_pdf_variants(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_selected_messages,
            "import_selected_messages should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            matching_message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[
                    GmailAttachment(
                        attachment_id="attachment-1",
                        filename="wsj-2026-05-03.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 english",
                    ),
                    GmailAttachment(
                        attachment_id="attachment-2",
                        filename="中文-华尔街日报-2026-05-03.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 translated",
                    ),
                    GmailAttachment(
                        attachment_id="attachment-3",
                        filename="【译】金融时报-5-5.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 prefix-translated",
                    ),
                ],
            )

            results = import_selected_messages(
                messages=[matching_message],
                allowed_senders={"briefing@example.com"},
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_filenames = connection.execute(
                    "SELECT original_filename FROM documents ORDER BY original_filename"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].document_key, "message-1:attachment-1:" + results[0].content_hash)
        self.assertEqual(stored_filenames, [("wsj-2026-05-03.pdf",)])

    def test_import_stores_filename_issue_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(message_id="m1", sender="s@example.com", attachments=[])
            attachment = GmailAttachment(
                attachment_id="a1",
                filename="The Economist USA - June 20 2026.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 economist",
            )
            result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )
            connection = sqlite3.connect(database_path)
            try:
                row = connection.execute(
                    "SELECT source_name, issue_date FROM documents WHERE document_key = ?",
                    (result.document_key,),
                ).fetchone()
            finally:
                connection.close()
        self.assertEqual(row, ("经济学人", "2026-06-20"))

    def test_same_issue_different_file_dedupes_to_one_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            def make(att_id, body):
                return GmailAttachment(
                    attachment_id=att_id,
                    filename="wsj-2026-05-06.pdf",
                    mime_type="application/pdf",
                    content_bytes=body,
                )

            msg = GmailMessage(message_id="m1", sender="s@example.com", attachments=[])
            first = import_gmail_pdf_attachment(
                message=msg, attachment=make("a1", b"%PDF first bytes"),
                storage_root=storage_root, database_url=database_url,
            )
            second = import_gmail_pdf_attachment(
                message=msg, attachment=make("a2", b"%PDF different bytes"),
                storage_root=storage_root, database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                doc_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                run_count = connection.execute(
                    "SELECT COUNT(*) FROM document_processing_runs WHERE document_key = ?",
                    (first.document_key,),
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertFalse(second.was_created)
        self.assertEqual(second.document_key, first.document_key)
        self.assertEqual(doc_count, 1)
        self.assertEqual(run_count, 1)

    def test_dateless_files_are_not_issue_deduped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            msg = GmailMessage(message_id="m1", sender="s@example.com", attachments=[])
            for att_id, body in (("a1", b"%PDF one"), ("a2", b"%PDF two")):
                import_gmail_pdf_attachment(
                    message=msg,
                    attachment=GmailAttachment(
                        attachment_id=att_id, filename="daily-paper.pdf",
                        mime_type="application/pdf", content_bytes=body,
                    ),
                    storage_root=storage_root, database_url=database_url,
                )
            connection = sqlite3.connect(database_path)
            try:
                doc_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(doc_count, 2)


class TranslationPrefixFilterTests(unittest.TestCase):
    def _attachment(self, filename: str) -> "GmailAttachment":
        self.assertIsNotNone(
            GmailAttachment,
            "GmailAttachment should be importable from newspaper_translator.ingestion",
        )
        return GmailAttachment(
            attachment_id="attachment-1",
            filename=filename,
            mime_type="application/pdf",
        )

    def test_rejects_pdf_whose_basename_starts_with_translation_prefix(self) -> None:
        for filename in (
            "【译】金融时报-5-5.pdf",
            "【译】华尔街日报-5-2.pdf",
            "【译】纽约时报.pdf",
            "/some/path/【译】xxx.pdf",
        ):
            with self.subTest(filename=filename):
                self.assertFalse(self._attachment(filename).is_pdf)

    def test_accepts_pdf_without_translation_prefix(self) -> None:
        for filename in (
            "金融时报-5-5.pdf",
            "华尔街日报-5-2.pdf",
            "wsj-2026-05-03.pdf",
        ):
            with self.subTest(filename=filename):
                self.assertTrue(self._attachment(filename).is_pdf)

    def test_keeps_legacy_translated_substring_patterns(self) -> None:
        for filename in (
            "中文-华尔街日报-2026-05-03.pdf",
            "中文-金融时报-2026-05-03.pdf",
            "【译】the_economist_(web_edition)_0205.pdf",
        ):
            with self.subTest(filename=filename):
                self.assertFalse(self._attachment(filename).is_pdf)


if __name__ == "__main__":
    unittest.main()
