from dataclasses import dataclass


@dataclass(frozen=True)
class OutlineEntry:
    title: str
    section: str
    start_page: int  # 1-based
    is_leaf: bool


@dataclass(frozen=True)
class ArticleRange:
    title: str
    section: str
    start_page: int
    end_page: int  # exclusive, 1-based


def compute_article_ranges(
    entries: list[OutlineEntry],
    *,
    total_pages: int,
) -> list[ArticleRange]:
    boundaries = sorted({entry.start_page for entry in entries})
    ranges: list[ArticleRange] = []
    for entry in entries:
        if not entry.is_leaf:
            continue
        end_page = next(
            (boundary for boundary in boundaries if boundary > entry.start_page),
            total_pages + 1,
        )
        ranges.append(
            ArticleRange(
                title=entry.title,
                section=entry.section,
                start_page=entry.start_page,
                end_page=end_page,
            )
        )
    ranges.sort(key=lambda article_range: article_range.start_page)
    return ranges
