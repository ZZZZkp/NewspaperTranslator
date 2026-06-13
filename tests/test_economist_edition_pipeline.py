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
    from newspaper_translator.article_pipeline import persist_economist_edition_articles
    from newspaper_translator.article_store import (
        list_latest_document_articles,
        list_parse_runs,
    )
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.economist_edition import (
        EditionArticle,
        ParsedEdition,
        build_economist_parse_result,
    )
except ImportError:
    persist_economist_edition_articles = None
    list_latest_document_articles = None
    list_parse_runs = None
    run_pending_migrations = None
    EditionArticle = None
    ParsedEdition = None
    build_economist_parse_result = None


def _insert_document(database_path, *, original_filename, raw_path):
    document_key = "message-1:attachment-1:hash-1"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            INSERT INTO documents (
                document_key, source_name, source_message_id, source_attachment_id,
                sender, original_filename, content_hash, raw_path, import_status,
                source_message_internal_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_key, "gmail", "message-1", "attachment-1", "news@example.com",
                original_filename, "hash-1", raw_path, "imported", None,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return document_key


class PersistEconomistEditionTests(unittest.TestCase):
    def test_persists_one_final_article_per_edition_article(self) -> None:
        self.assertIsNotNone(persist_economist_edition_articles)
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = _insert_document(
                database_path,
                original_filename="TE-2026-06-13-PDF_WEB.pdf",
                raw_path=str(pathlib.Path(temp_dir) / "TE-2026-06-13-PDF_WEB.pdf"),
            )

            fake_articles = [
                EditionArticle(
                    title="The World Cup paradox", section="Leaders",
                    start_page=17, end_page=23, body_text="Body paradox.",
                    url="https://www.economist.com/leaders/2026/06/10/paradox",
                ),
                EditionArticle(
                    title="Least bad option in Iran", section="Leaders",
                    start_page=23, end_page=27, body_text="Body iran.",
                    url="https://www.economist.com/leaders/2026/06/10/iran",
                ),
            ]
            edition = ParsedEdition(
                parse_result=build_economist_parse_result(fake_articles),
                debug_text="debug",
            )

            parse_run = persist_economist_edition_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=pathlib.Path(temp_dir) / "phase3-output",
                parser_name="economist-edition",
                parser_version="economist-edition-v1",
                parse_edition=lambda _pdf_path: edition,
            )

            self.assertEqual(parse_run.status, "succeeded")
            self.assertEqual(parse_run.parser_name, "economist-edition")

            runs = list_parse_runs(database_url=database_url, document_key=document_key)
            self.assertEqual(len(runs), 1)

            articles = list_latest_document_articles(
                database_url=database_url, document_key=document_key,
            )
            self.assertEqual([a.title_en for a in articles], ["The World Cup paradox", "Least bad option in Iran"])
            self.assertEqual([a.publication_date for a in articles], ["2026-06-13", "2026-06-13"])
            self.assertEqual(articles[0].source_page_numbers, [17])


if __name__ == "__main__":
    unittest.main()
