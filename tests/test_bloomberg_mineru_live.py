# tests/test_bloomberg_mineru_live.py
import os
from pathlib import Path

import pytest

RUN_LIVE = os.environ.get("BLOOMBERG_LIVE_PDF")


@pytest.mark.skipif(not RUN_LIVE, reason="set BLOOMBERG_LIVE_PDF to run")
def test_live_full_magazine(tmp_path):
    from newspaper_translator.config import MineruSettings
    from newspaper_translator.mineru import MineruClient
    from newspaper_translator.bloomberg_mineru import parse_bloomberg_edition

    client = MineruClient(settings=MineruSettings.from_env(os.environ))
    parsed = parse_bloomberg_edition(
        Path(RUN_LIVE), images_dir=tmp_path / "images",
        mineru_client=client, output_root=tmp_path / "out",
    )
    assert len(parsed.parse_result.articles) >= 10
    for article in parsed.parse_result.articles:
        assert "Learn more at" not in article.body_text  # no ad leakage
