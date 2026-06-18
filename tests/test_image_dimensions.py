import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from newspaper_translator.image_dimensions import read_image_size


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

    def test_returns_none_for_missing_file(self) -> None:
        self.assertIsNone(read_image_size("/nonexistent/path/missing.png"))


if __name__ == "__main__":
    unittest.main()
