from dataclasses import dataclass
import sqlite3

from newspaper_translator.database import sqlite_path_from_database_url


@dataclass(frozen=True)
class PageParseState:
    page_number: int
    batch_id: str | None
    file_name: str | None
    state: str
    full_zip_url: str | None
    markdown_path: str | None


class MineruPageParseStateStore:
    def __init__(self, *, database_url: str) -> None:
        self._database_url = database_url

    def load(self, *, document_key: str) -> dict[int, PageParseState]:
        connection = sqlite3.connect(sqlite_path_from_database_url(self._database_url))
        try:
            rows = connection.execute(
                """
                SELECT page_number, batch_id, file_name, state, full_zip_url, markdown_path
                FROM mineru_page_parse_state
                WHERE document_key = ?
                """,
                (document_key,),
            ).fetchall()
        finally:
            connection.close()
        return {
            row[0]: PageParseState(
                page_number=row[0],
                batch_id=row[1],
                file_name=row[2],
                state=row[3],
                full_zip_url=row[4],
                markdown_path=row[5],
            )
            for row in rows
        }

    def mark_submitted(
        self, *, document_key: str, page_number: int, batch_id: str, file_name: str
    ) -> None:
        self._upsert(
            document_key=document_key,
            page_number=page_number,
            batch_id=batch_id,
            file_name=file_name,
            state="submitted",
            full_zip_url=None,
            markdown_path=None,
        )

    def mark_done(
        self,
        *,
        document_key: str,
        page_number: int,
        batch_id: str,
        file_name: str,
        full_zip_url: str,
        markdown_path: str,
    ) -> None:
        self._upsert(
            document_key=document_key,
            page_number=page_number,
            batch_id=batch_id,
            file_name=file_name,
            state="done",
            full_zip_url=full_zip_url,
            markdown_path=markdown_path,
        )

    def _upsert(
        self,
        *,
        document_key: str,
        page_number: int,
        batch_id: str | None,
        file_name: str | None,
        state: str,
        full_zip_url: str | None,
        markdown_path: str | None,
    ) -> None:
        connection = sqlite3.connect(sqlite_path_from_database_url(self._database_url))
        try:
            connection.execute(
                """
                INSERT INTO mineru_page_parse_state (
                    document_key, page_number, batch_id, file_name,
                    state, full_zip_url, markdown_path, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(document_key, page_number) DO UPDATE SET
                    batch_id = excluded.batch_id,
                    file_name = excluded.file_name,
                    state = excluded.state,
                    full_zip_url = excluded.full_zip_url,
                    markdown_path = excluded.markdown_path,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    document_key, page_number, batch_id, file_name,
                    state, full_zip_url, markdown_path,
                ),
            )
            connection.commit()
        finally:
            connection.close()
