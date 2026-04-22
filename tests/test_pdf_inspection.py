import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

SAMPLE_ROOT = PROJECT_ROOT.parent
WSJ_SAMPLE = SAMPLE_ROOT / "华尔街日报-4-20.pdf"
GUARDIAN_SAMPLE = SAMPLE_ROOT / "卫报-4-21.pdf"
FT_SAMPLE = SAMPLE_ROOT / "金融时报-4-20.pdf"

try:
    from newspaper_translator.pdf import (
        build_page_profiles,
        classify_pdf,
        extract_page_text,
        extract_page_text_blocks,
        extract_text_pages,
        extract_title_candidates,
        inspect_pdf,
    )
except ImportError:
    build_page_profiles = None
    classify_pdf = None
    extract_page_text = None
    extract_page_text_blocks = None
    extract_text_pages = None
    extract_title_candidates = None
    inspect_pdf = None


class PdfInspectionTests(unittest.TestCase):
    def test_reports_page_counts_for_real_pdf_samples(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            inspect_pdf,
            "inspect_pdf should be importable from newspaper_translator.pdf",
        )

        wsj = inspect_pdf(WSJ_SAMPLE)
        guardian = inspect_pdf(GUARDIAN_SAMPLE)
        ft = inspect_pdf(FT_SAMPLE)

        self.assertEqual(wsj.page_count, 36)
        self.assertEqual(guardian.page_count, 40)
        self.assertEqual(ft.page_count, 28)

    def test_detects_which_real_pdf_samples_have_extractable_text(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            inspect_pdf,
            "inspect_pdf should be importable from newspaper_translator.pdf",
        )

        wsj = inspect_pdf(WSJ_SAMPLE)
        guardian = inspect_pdf(GUARDIAN_SAMPLE)
        ft = inspect_pdf(FT_SAMPLE)

        self.assertTrue(wsj.has_extractable_text)
        self.assertTrue(guardian.has_extractable_text)
        self.assertFalse(ft.has_extractable_text)
        self.assertGreater(wsj.extractable_page_count, 0)
        self.assertGreater(guardian.extractable_page_count, 0)
        self.assertEqual(ft.extractable_page_count, 0)

    def test_classifies_real_pdf_samples_as_digital_or_scanned(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            classify_pdf,
            "classify_pdf should be importable from newspaper_translator.pdf",
        )

        self.assertEqual(classify_pdf(WSJ_SAMPLE), "digital")
        self.assertEqual(classify_pdf(GUARDIAN_SAMPLE), "digital")
        self.assertEqual(classify_pdf(FT_SAMPLE), "scanned")

    def test_extracts_first_page_text_from_digital_samples(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertIsNotNone(
            extract_page_text,
            "extract_page_text should be importable from newspaper_translator.pdf",
        )

        wsj_page_text = extract_page_text(WSJ_SAMPLE, page_number=1)
        guardian_page_text = extract_page_text(GUARDIAN_SAMPLE, page_number=1)

        self.assertIn("WSJ.com", wsj_page_text)
        self.assertIn("Edition Date:260421", guardian_page_text)
        self.assertGreater(len(wsj_page_text), 1000)
        self.assertGreater(len(guardian_page_text), 1000)

    def test_returns_empty_text_for_scanned_sample_first_page(self) -> None:
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            extract_page_text,
            "extract_page_text should be importable from newspaper_translator.pdf",
        )

        ft_page_text = extract_page_text(FT_SAMPLE, page_number=1)

        self.assertEqual(ft_page_text, "")

    def test_builds_page_profiles_for_real_pdf_samples(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            build_page_profiles,
            "build_page_profiles should be importable from newspaper_translator.pdf",
        )

        wsj_profiles = build_page_profiles(WSJ_SAMPLE)
        ft_profiles = build_page_profiles(FT_SAMPLE)

        self.assertEqual(len(wsj_profiles), 36)
        self.assertEqual(len(ft_profiles), 28)

        self.assertEqual(wsj_profiles[0].page_number, 1)
        self.assertTrue(wsj_profiles[0].has_extractable_text)
        self.assertGreater(wsj_profiles[0].text_length, 1000)
        self.assertEqual(wsj_profiles[0].page_type, "digital")

        self.assertEqual(ft_profiles[0].page_number, 1)
        self.assertFalse(ft_profiles[0].has_extractable_text)
        self.assertEqual(ft_profiles[0].text_length, 0)
        self.assertEqual(ft_profiles[0].page_type, "scanned")

    def test_extracts_only_text_pages_for_digital_and_scanned_samples(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            extract_text_pages,
            "extract_text_pages should be importable from newspaper_translator.pdf",
        )

        wsj_pages = extract_text_pages(WSJ_SAMPLE)
        ft_pages = extract_text_pages(FT_SAMPLE)

        self.assertGreater(len(wsj_pages), 0)
        self.assertEqual(wsj_pages[0].page_number, 1)
        self.assertIn("WSJ.com", wsj_pages[0].text)

        self.assertEqual(ft_pages, [])

    def test_extracts_text_blocks_from_digital_and_scanned_samples(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(FT_SAMPLE.exists(), f"Missing sample PDF: {FT_SAMPLE}")
        self.assertIsNotNone(
            extract_page_text_blocks,
            "extract_page_text_blocks should be importable from newspaper_translator.pdf",
        )

        wsj_blocks = extract_page_text_blocks(WSJ_SAMPLE, page_number=1)
        ft_blocks = extract_page_text_blocks(FT_SAMPLE, page_number=1)

        self.assertGreater(len(wsj_blocks), 100)
        self.assertEqual(wsj_blocks[0].page_number, 1)
        self.assertIn("WSJ.com", wsj_blocks[0].text)
        self.assertEqual(ft_blocks, [])

    def test_extracts_title_candidates_from_real_digital_samples(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertIsNotNone(
            extract_title_candidates,
            "extract_title_candidates should be importable from newspaper_translator.pdf",
        )

        wsj_candidates = extract_title_candidates(WSJ_SAMPLE, page_number=1)
        guardian_candidates = extract_title_candidates(GUARDIAN_SAMPLE, page_number=1)

        self.assertIn("talks to acquire Kelonia", wsj_candidates)
        self.assertIn("AI job scams", guardian_candidates)
        self.assertIn("Starmer on collision course with", guardian_candidates)


if __name__ == "__main__":
    unittest.main()
