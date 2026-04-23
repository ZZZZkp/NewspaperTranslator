import argparse
from dataclasses import asdict, is_dataclass
import json
import os
import sys

from newspaper_translator.import_audit import (
    list_import_items,
    list_import_run_items,
    list_import_runs,
)
from newspaper_translator.database import run_pending_migrations
from newspaper_translator.gmail import import_from_gmail, retry_failed_gmail_messages
from newspaper_translator.runtime import build_runtime_report


def run_cli(argv: list[str]) -> tuple[int, str]:
    parser = argparse.ArgumentParser(prog="newspaper_translator.manage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--database-url", required=True)

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--service", required=True)
    check_parser.add_argument("--app-env")
    check_parser.add_argument("--database-url")
    check_parser.add_argument("--storage-root")
    check_parser.add_argument("--gmail-client-id")
    check_parser.add_argument("--gmail-client-secret")
    check_parser.add_argument("--gmail-refresh-token")

    gmail_import_parser = subparsers.add_parser("gmail-import")
    gmail_import_parser.add_argument("--gmail-config", required=True)
    gmail_import_parser.add_argument("--database-url")
    gmail_import_parser.add_argument("--storage-root")

    gmail_retry_parser = subparsers.add_parser("gmail-retry-failures")
    gmail_retry_parser.add_argument("--gmail-config", required=True)
    gmail_retry_parser.add_argument("--database-url")
    gmail_retry_parser.add_argument("--storage-root")

    gmail_import_runs_parser = subparsers.add_parser("gmail-import-runs")
    gmail_import_runs_parser.add_argument("--database-url")
    gmail_import_runs_parser.add_argument("--limit", type=int, default=20)

    gmail_import_run_items_parser = subparsers.add_parser("gmail-import-run-items")
    gmail_import_run_items_parser.add_argument("--database-url")
    gmail_import_run_items_parser.add_argument("--run-id", required=True)
    gmail_import_run_items_parser.add_argument("--status")
    gmail_import_run_items_parser.add_argument("--item-type")

    gmail_import_items_parser = subparsers.add_parser("gmail-import-items")
    gmail_import_items_parser.add_argument("--database-url")
    gmail_import_items_parser.add_argument("--limit", type=int, default=50)
    gmail_import_items_parser.add_argument("--status")
    gmail_import_items_parser.add_argument("--item-type")

    args = parser.parse_args(argv)

    if args.command == "migrate":
        applied_versions = run_pending_migrations(args.database_url)
        if applied_versions:
            return 0, f"Applied migrations: {', '.join(applied_versions)}"
        return 0, "Applied migrations: none"

    if args.command == "check":
        resolved_env = {
            "APP_ENV": _resolve_setting(args.app_env, "APP_ENV"),
            "DATABASE_URL": _resolve_setting(args.database_url, "DATABASE_URL"),
            "STORAGE_ROOT": _resolve_setting(args.storage_root, "STORAGE_ROOT"),
            "GMAIL_CLIENT_ID": _resolve_setting(args.gmail_client_id, "GMAIL_CLIENT_ID"),
            "GMAIL_CLIENT_SECRET": _resolve_setting(
                args.gmail_client_secret,
                "GMAIL_CLIENT_SECRET",
            ),
            "GMAIL_REFRESH_TOKEN": _resolve_setting(
                args.gmail_refresh_token,
                "GMAIL_REFRESH_TOKEN",
            ),
        }
        report = build_runtime_report(
            env=resolved_env,
            service=args.service,
        )
        return 0, json.dumps(report, sort_keys=True)

    if args.command == "gmail-import":
        summary = import_from_gmail(
            config_path=args.gmail_config,
            storage_root=_resolve_setting(args.storage_root, "STORAGE_ROOT"),
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
        )
        return 0, json.dumps(_to_jsonable(summary), sort_keys=True)

    if args.command == "gmail-retry-failures":
        summary = retry_failed_gmail_messages(
            config_path=args.gmail_config,
            storage_root=_resolve_setting(args.storage_root, "STORAGE_ROOT"),
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
        )
        return 0, json.dumps(_to_jsonable(summary), sort_keys=True)

    if args.command == "gmail-import-runs":
        runs = list_import_runs(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            limit=args.limit,
        )
        return 0, json.dumps(_to_jsonable(runs), sort_keys=True)

    if args.command == "gmail-import-run-items":
        items = list_import_run_items(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            run_id=args.run_id,
            status=args.status,
            item_type=args.item_type,
        )
        return 0, json.dumps(_to_jsonable(items), sort_keys=True)

    if args.command == "gmail-import-items":
        items = list_import_items(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            limit=args.limit,
            status=args.status,
            item_type=args.item_type,
        )
        return 0, json.dumps(_to_jsonable(items), sort_keys=True)

    return 1, "Unknown command"


def main() -> None:
    exit_code, output = run_cli(sys.argv[1:])
    print(output)
    raise SystemExit(exit_code)


def _resolve_setting(value: str | None, env_key: str) -> str:
    if value:
        return value
    return os.environ.get(env_key, "")


def _to_jsonable(value):
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return value.__dict__
    return value


if __name__ == "__main__":
    main()
