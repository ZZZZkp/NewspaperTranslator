import pathlib
import sys
import tempfile
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.database import run_pending_migrations
from newspaper_translator.mineru_page_state import MineruPageParseStateStore


class MineruPageParseStateStoreTests(unittest.TestCase):
    def test_mark_submitted_then_done_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_url = f"sqlite:///{pathlib.Path(temp_dir) / 'state.db'}"
            run_pending_migrations(database_url)
            store = MineruPageParseStateStore(database_url=database_url)

            store.mark_submitted(
                document_key="doc-1", page_number=1, batch_id="b1", file_name="page-0001.pdf"
            )
            store.mark_done(
                document_key="doc-1", page_number=1, batch_id="b1", file_name="page-0001.pdf",
                full_zip_url="https://z/1.zip", markdown_path="/out/page-0001/full.md",
            )
            store.mark_submitted(
                document_key="doc-1", page_number=2, batch_id="b1", file_name="page-0002.pdf"
            )

            states = store.load(document_key="doc-1")
            self.assertEqual(states[1].state, "done")
            self.assertEqual(states[1].markdown_path, "/out/page-0001/full.md")
            self.assertEqual(states[2].state, "submitted")
            self.assertEqual(states[2].batch_id, "b1")
            self.assertEqual(store.load(document_key="other"), {})


if __name__ == "__main__":
    unittest.main()
