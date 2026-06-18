import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from newspaper_translator.image_dimensions import pick_largest_image, read_image_size


def _png_bytes(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    return signature + ihdr


def _jpeg_bytes(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )


def _write(tmp: pathlib.Path, name: str, data: bytes) -> str:
    path = tmp / name
    path.write_bytes(data)
    return str(path)


class ReadImageSizeTests(unittest.TestCase):
    def test_reads_png_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "a.png", _png_bytes(640, 480))
            self.assertEqual(read_image_size(path), (640, 480))

    def test_reads_jpeg_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "a.jpg", _jpeg_bytes(800, 600))
            self.assertEqual(read_image_size(path), (800, 600))

    def test_returns_none_for_non_image_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "a.txt", b"not an image at all")
            self.assertIsNone(read_image_size(path))

    def test_reads_jpeg_with_sof_at_buffer_tail(self) -> None:
        # SOI + SOF0 with no trailing bytes: the SOF dimensions sit at the very
        # end of the data, guarding against an off-by-one in the scan loop.
        data = (
            b"\xff\xd8"
            + b"\xff\xc0\x00\x11\x08"
            + (240).to_bytes(2, "big")
            + (320).to_bytes(2, "big")
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "tail.jpg", data)
            self.assertEqual(read_image_size(path), (320, 240))

    def test_returns_none_for_missing_file(self) -> None:
        self.assertIsNone(read_image_size("/nonexistent/path/missing.png"))


class PickLargestImageTests(unittest.TestCase):
    def test_picks_largest_by_pixel_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            small = _write(tmp, "small.png", _png_bytes(100, 100))
            large = _write(tmp, "large.jpg", _jpeg_bytes(400, 300))
            self.assertEqual(pick_largest_image([small, large]), large)

    def test_ignores_unparseable_and_picks_largest_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            broken = _write(tmp, "broken.png", b"not an image")
            good = _write(tmp, "good.png", _png_bytes(50, 50))
            self.assertEqual(pick_largest_image([broken, good]), good)

    def test_falls_back_to_first_when_all_unparseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            first = _write(tmp, "first.png", b"nope")
            second = _write(tmp, "second.png", b"nope either")
            self.assertEqual(pick_largest_image([first, second]), first)

    def test_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(pick_largest_image([]))


if __name__ == "__main__":
    unittest.main()
