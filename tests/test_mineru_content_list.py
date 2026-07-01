import json
from pathlib import Path

from newspaper_translator.mineru import load_content_list_from_dir


def test_load_content_list_from_dir_reads_the_json(tmp_path: Path):
    (tmp_path / "abc_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "hi", "page_idx": 0}]),
        encoding="utf-8",
    )
    blocks = load_content_list_from_dir(tmp_path)
    assert blocks == ({"type": "text", "text": "hi", "page_idx": 0},)


def test_load_content_list_from_dir_missing_returns_empty(tmp_path: Path):
    assert load_content_list_from_dir(tmp_path) == ()
