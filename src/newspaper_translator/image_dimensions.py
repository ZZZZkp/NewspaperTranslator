"""Lightweight image header parsing (no third-party dependency).

Reads only the file header to obtain pixel dimensions for PNG and JPEG.
"""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_HEADER_READ_BYTES = 65536
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def read_image_size(path: str) -> tuple[int, int] | None:
    """Return (width, height) for a PNG/JPEG file, or None if unparseable."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_HEADER_READ_BYTES)
    except OSError:
        return None

    if data[:8] == _PNG_SIGNATURE:
        return _read_png_size(data)
    if data[:2] == b"\xff\xd8":
        return _read_jpeg_size(data)
    return None


def _read_png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _read_jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            if width <= 0 or height <= 0:
                return None
            return width, height
        if marker == 0xD8 or marker == 0xD9 or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        segment_length = int.from_bytes(data[index + 2 : index + 4], "big")
        if segment_length <= 0:
            return None
        index += 2 + segment_length
    return None
