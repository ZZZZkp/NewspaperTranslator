from pathlib import Path
import re


_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
_LOCAL_IMAGE_SUFFIX = re.compile(r"\.(?:png|jpg|jpeg|webp)$", re.IGNORECASE)


def extract_local_image_paths_and_clean_text(
    text: str,
    *,
    base_dir: Path | None = None,
) -> tuple[list[str], str]:
    image_paths: list[str] = []
    cleaned_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line

        for match in list(_MARKDOWN_IMAGE_PATTERN.finditer(raw_line)):
            candidate = match.group(1).strip()
            resolved = _normalize_local_image_path(candidate, base_dir=base_dir)
            if resolved is not None:
                image_paths.append(resolved)
                line = line.replace(match.group(0), "").strip()

        stripped_line = line.strip()
        resolved_line_path = _normalize_local_image_path(stripped_line, base_dir=base_dir)
        if resolved_line_path is not None and stripped_line == line.strip():
            image_paths.append(resolved_line_path)
            continue

        if stripped_line:
            cleaned_lines.append(stripped_line)

    return _dedupe_preserving_order(image_paths), "\n".join(cleaned_lines).strip()


def _normalize_local_image_path(value: str, *, base_dir: Path | None) -> str | None:
    if not value:
        return None
    if "://" in value:
        return None

    normalized = value.strip().strip("\"'")
    if not normalized or not _LOCAL_IMAGE_SUFFIX.search(normalized):
        return None

    path = Path(normalized)
    if not path.is_absolute():
        if base_dir is None:
            return normalized
        path = (base_dir / path).resolve()

    return str(path)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
