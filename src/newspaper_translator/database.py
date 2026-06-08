from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import sqlite3
from collections.abc import Iterator
from pathlib import Path


class DatabaseConfigurationError(ValueError):
    """Raised when the database URL cannot be handled by the current runtime."""


@contextmanager
def _migration_lock(database_path: Path) -> Iterator[None]:
    """Serialize migrations across processes sharing one SQLite file.

    Several services (web, worker, article-worker) boot at once against the same
    database volume. Without a cross-process lock they each read an empty
    schema_migrations table and re-apply the same migrations, so a second writer
    hits "duplicate column name". An exclusive ``flock`` on a sidecar lock file lets
    exactly one process migrate at a time; the others block, then re-read the (now
    fully applied) version set and skip everything.

    In-memory databases are private to a single connection, so no lock is needed.
    """
    if database_path == Path(":memory:"):
        yield
        return

    lock_path = database_path.with_name(database_path.name + ".migrate.lock")
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class DatabaseStatus:
    driver: str
    status: str
    detail: str
    applied_migration_count: int


def run_pending_migrations(database_url: str) -> list[str]:
    database_path = sqlite_path_from_database_url(database_url)
    if database_path != Path(":memory:"):
        database_path.parent.mkdir(parents=True, exist_ok=True)

    with _migration_lock(database_path):
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )

            applied_versions = {
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                )
            }

            newly_applied_versions: list[str] = []
            for migration_path in sorted(_migration_directory().glob("*.sql")):
                version = migration_path.stem
                if version in applied_versions:
                    continue

                connection.executescript(migration_path.read_text())
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, applied_at)
                    VALUES (?, CURRENT_TIMESTAMP)
                    """,
                    (version,),
                )
                newly_applied_versions.append(version)

            connection.commit()
            return newly_applied_versions
        finally:
            connection.close()


def inspect_database(database_url: str) -> DatabaseStatus:
    database_path = sqlite_path_from_database_url(database_url)
    connection = sqlite3.connect(database_path)
    try:
        migration_table_exists = connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """
        ).fetchone()[0]
        if not migration_table_exists:
            return DatabaseStatus(
                driver="sqlite",
                status="error",
                detail="schema_migrations table is missing",
                applied_migration_count=0,
            )

        applied_migration_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
        return DatabaseStatus(
            driver="sqlite",
            status="ok",
            detail="database reachable",
            applied_migration_count=applied_migration_count,
        )
    finally:
        connection.close()


def sqlite_path_from_database_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise DatabaseConfigurationError(
            f"Unsupported SQLite database URL for current runtime: {database_url}"
        )

    sqlite_path = database_url.removeprefix(prefix)
    if not sqlite_path:
        raise DatabaseConfigurationError("SQLite database URL must include a path")
    return Path(sqlite_path)


def _migration_directory() -> Path:
    return Path(__file__).resolve().parent / "migrations"
