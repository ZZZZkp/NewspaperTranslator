from dataclasses import asdict
from typing import Mapping

from newspaper_translator.config import AppSettings
from newspaper_translator.database import inspect_database, run_pending_migrations


def build_runtime_report(*, env: Mapping[str, str], service: str) -> dict[str, object]:
    settings = AppSettings.from_env(env)
    run_pending_migrations(settings.database_url)
    database_status = inspect_database(settings.database_url)

    return {
        "status": "ok" if database_status.status == "ok" else "error",
        "service": service,
        "app_env": settings.app_env,
        "storage_root": settings.storage_root,
        "database": asdict(database_status),
    }
