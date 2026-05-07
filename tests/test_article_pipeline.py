import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.article_pipeline import (
        persist_document_articles,
        resolve_publication_date,
    )
    from newspaper_translator.article_store import (
        list_latest_document_articles,
        list_parse_runs,
    )
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.mineru import MineruParsedDocument
except ImportError:
    persist_document_articles = None
    resolve_publication_date = None
    list_latest_document_articles = None
    list_parse_runs = None
    run_pending_migrations = None
    MineruParsedDocument = None


class ArticlePipelineTests(unittest.TestCase):
    def test_persists_document_articles_using_publication_date_from_filename(self) -> None:
        self.assertIsNotNone(persist_document_articles)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
                raw_path=str(pathlib.Path(temp_dir) / "wsj-2026-04-20.pdf"),
            )
            pathlib.Path(temp_dir, "wsj-2026-04-20.pdf").write_bytes(b"%PDF-1.4 sample")
            markdown_path = pathlib.Path(temp_dir) / "phase3-output" / "wsj-2026-04-20" / "full.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
                "Please turn to page A7\n\n"
                "# Big Oil Explores Farther Out\n\n"
                "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
                "The oil companies want to maximize their production.\n",
                encoding="utf-8",
            )

            parse_run = persist_document_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=pathlib.Path(temp_dir) / "phase3-output",
                mineru_client=_FakeMineruClient(
                    parsed_document=MineruParsedDocument(
                        batch_id="batch-1",
                        file_id="file-1",
                        file_name="wsj-2026-04-20.pdf",
                        markdown_path=markdown_path,
                        markdown_text=markdown_path.read_text(encoding="utf-8"),
                    )
                ),
                continuation_matcher=_FakeContinuationMatcher(matches=[(1, 2)]),
                parser_name="mineru",
                parser_version="vlm",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )

            latest_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(parse_run.status, "succeeded")
        self.assertEqual(parse_run.publication_date, "2026-04-20")
        self.assertEqual(len(latest_articles), 1)
        self.assertEqual(latest_articles[0].publication_date, "2026-04-20")

    def test_falls_back_to_markdown_date_when_filename_has_no_date(self) -> None:
        self.assertIsNotNone(persist_document_articles)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_key = self._insert_document(
                database_path,
                original_filename="wall-street-journal.pdf",
                raw_path=str(pathlib.Path(temp_dir) / "wall-street-journal.pdf"),
            )
            pathlib.Path(temp_dir, "wall-street-journal.pdf").write_bytes(b"%PDF-1.4 sample")
            markdown_path = pathlib.Path(temp_dir) / "phase3-output" / "wall-street-journal" / "full.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(
                "The Wall Street Journal, April 20, 2026\n\n"
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "U.S. oil futures were trading near $90 a barrel Sunday.\n",
                encoding="utf-8",
            )

            parse_run = persist_document_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=pathlib.Path(temp_dir) / "phase3-output",
                mineru_client=_FakeMineruClient(
                    parsed_document=MineruParsedDocument(
                        batch_id="batch-1",
                        file_id="file-1",
                        file_name="wall-street-journal.pdf",
                        markdown_path=markdown_path,
                        markdown_text=markdown_path.read_text(encoding="utf-8"),
                    )
                ),
                continuation_matcher=None,
                parser_name="mineru",
                parser_version="vlm",
                continuation_matcher_name="",
                continuation_matcher_version="",
            )

        self.assertEqual(parse_run.status, "succeeded")
        self.assertEqual(parse_run.publication_date, "2026-04-20")

    def test_marks_parse_run_failed_when_publication_date_cannot_be_resolved(self) -> None:
        self.assertIsNotNone(persist_document_articles)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_key = self._insert_document(
                database_path,
                original_filename="wall-street-journal.pdf",
                raw_path=str(pathlib.Path(temp_dir) / "wall-street-journal.pdf"),
            )
            pathlib.Path(temp_dir, "wall-street-journal.pdf").write_bytes(b"%PDF-1.4 sample")
            markdown_path = pathlib.Path(temp_dir) / "phase3-output" / "wall-street-journal" / "full.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "U.S. oil futures were trading near $90 a barrel Sunday.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "publication date"):
                persist_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                    output_root=pathlib.Path(temp_dir) / "phase3-output",
                    mineru_client=_FakeMineruClient(
                        parsed_document=MineruParsedDocument(
                            batch_id="batch-1",
                            file_id="file-1",
                            file_name="wall-street-journal.pdf",
                            markdown_path=markdown_path,
                            markdown_text=markdown_path.read_text(encoding="utf-8"),
                        )
                    ),
                    continuation_matcher=None,
                    parser_name="mineru",
                    parser_version="vlm",
                    continuation_matcher_name="",
                    continuation_matcher_version="",
                )

            parse_runs = list_parse_runs(database_url=database_url, document_key=document_key)

        self.assertEqual(len(parse_runs), 1)
        self.assertEqual(parse_runs[0].status, "failed")
        self.assertIn("publication date", parse_runs[0].error_message)

    @patch("builtins.print")
    def test_logs_when_filename_date_and_gmail_date_disagree(self, print_mock) -> None:
        resolved = resolve_publication_date(
            original_filename="金融时报-5-6.pdf",
            markdown_text="",
            source_message_internal_date="1778198400000",
            fallback_year=2026,
        )

        self.assertEqual(resolved, "2026-05-06")
        self.assertIn(
            "publication_date_filename_gmail_mismatch",
            print_mock.call_args[0][0],
        )

    def test_uses_gmail_message_year_for_month_day_filename_dates(self) -> None:
        self.assertIsNotNone(persist_document_articles)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_key = self._insert_document(
                database_path,
                original_filename="金融时报-5-6.pdf",
                raw_path=str(pathlib.Path(temp_dir) / "金融时报-5-6.pdf"),
                source_message_internal_date="1778102400000",
            )
            pathlib.Path(temp_dir, "金融时报-5-6.pdf").write_bytes(b"%PDF-1.4 sample")
            markdown_path = pathlib.Path(temp_dir) / "phase3-output" / "ft" / "full.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(
                "# Lead Story\n\nBody text.\n",
                encoding="utf-8",
            )

            parse_run = persist_document_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=pathlib.Path(temp_dir) / "phase3-output",
                mineru_client=_FakeMineruClient(
                    parsed_document=MineruParsedDocument(
                        batch_id="batch-1",
                        file_id="file-1",
                        file_name="金融时报-5-6.pdf",
                        markdown_path=markdown_path,
                        markdown_text=markdown_path.read_text(encoding="utf-8"),
                    )
                ),
                continuation_matcher=None,
                parser_name="mineru",
                parser_version="vlm",
                continuation_matcher_name="",
                continuation_matcher_version="",
            )

        self.assertEqual(parse_run.publication_date, "2026-05-06")

    def test_falls_back_to_runtime_year_for_month_day_filename_without_gmail_date(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="金融时报-5-6.pdf",
                markdown_text="",
                source_message_internal_date=None,
                fallback_year=2026,
            ),
            "2026-05-06",
        )

    def test_uses_explicit_asia_shanghai_year_for_boundary_gmail_timestamp(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="paper-1-1.pdf",
                markdown_text="",
                source_message_internal_date="1735687800000",
                fallback_year=2024,
            ),
            "2025-01-01",
        )

    def test_uses_fallback_year_for_malformed_gmail_timestamp(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="paper-1-1.pdf",
                markdown_text="",
                source_message_internal_date="not-a-number",
                fallback_year=2024,
            ),
            "2024-01-01",
        )

    def test_rejects_invalid_month_day_filename_dates(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="金融时报-2-30.pdf",
                markdown_text="The Wall Street Journal, April 20, 2026\n\nLead story\n",
                source_message_internal_date="1778102400000",
                fallback_year=2026,
            ),
            "",
        )

    def test_invalid_month_day_filename_still_fails_parse_run_when_markdown_has_date(
        self,
    ) -> None:
        self.assertIsNotNone(persist_document_articles)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_key = self._insert_document(
                database_path,
                original_filename="金融时报-2-30.pdf",
                raw_path=str(pathlib.Path(temp_dir) / "金融时报-2-30.pdf"),
                source_message_internal_date="1778102400000",
            )
            pathlib.Path(temp_dir, "金融时报-2-30.pdf").write_bytes(b"%PDF-1.4 sample")
            markdown_path = pathlib.Path(temp_dir) / "phase3-output" / "ft" / "full.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(
                "The Wall Street Journal, April 20, 2026\n\n# Lead Story\n\nBody text.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "publication date"):
                persist_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                    output_root=pathlib.Path(temp_dir) / "phase3-output",
                    mineru_client=_FakeMineruClient(
                        parsed_document=MineruParsedDocument(
                            batch_id="batch-1",
                            file_id="file-1",
                            file_name="金融时报-2-30.pdf",
                            markdown_path=markdown_path,
                            markdown_text=markdown_path.read_text(encoding="utf-8"),
                        )
                    ),
                    continuation_matcher=None,
                    parser_name="mineru",
                    parser_version="vlm",
                    continuation_matcher_name="",
                    continuation_matcher_version="",
                )

            parse_runs = list_parse_runs(database_url=database_url, document_key=document_key)

        self.assertEqual(len(parse_runs), 1)
        self.assertEqual(parse_runs[0].status, "failed")
        self.assertIn("publication date", parse_runs[0].error_message)

    def _insert_document(
        self,
        database_path: pathlib.Path,
        *,
        original_filename: str,
        raw_path: str,
        source_message_internal_date: str | None = None,
    ) -> str:
        document_key = "message-1:attachment-1:hash-1"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
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
                    import_status,
                    source_message_internal_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_key,
                    "gmail",
                    "message-1",
                    "attachment-1",
                    "news@example.com",
                    original_filename,
                    "hash-1",
                    raw_path,
                    "imported",
                    source_message_internal_date,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key


class _FakeMineruClient:
    def __init__(self, *, parsed_document) -> None:
        self._parsed_document = parsed_document
        self.calls: list[dict[str, object]] = []

    def parse_pdf(self, *, pdf_path: pathlib.Path, output_root: pathlib.Path):
        self.calls.append({"pdf_path": pdf_path, "output_root": output_root})
        return self._parsed_document


class _FakeContinuationMatcher:
    def __init__(self, *, matches: list[tuple[int, int]]) -> None:
        self._matches = matches

    def __call__(self, fragments):
        return list(self._matches)


if __name__ == "__main__":
    unittest.main()
