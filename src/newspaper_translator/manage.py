import argparse
from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import sys

from newspaper_translator.article_enrichment import enrich_article
from newspaper_translator.article_pipeline import persist_document_articles
from newspaper_translator.article_store import (
    get_latest_article_enrichment,
    list_latest_document_articles,
    list_parse_run_continuation_matches,
    list_parse_run_final_articles,
    list_parse_run_fragments,
    list_parse_runs,
)
from newspaper_translator.config import GeminiSettings, MineruSettings
from newspaper_translator.document_processing import (
    get_document_processing_run,
    request_manual_document_retry,
    run_scheduler_tick,
)
from newspaper_translator.gemini import (
    GeminiArticleSummarizerTagger,
    GeminiArticleTranslator,
    GeminiContinuationMatcher,
)
from newspaper_translator.import_audit import (
    list_import_items,
    list_import_run_items,
    list_import_runs,
)
from newspaper_translator.database import run_pending_migrations
from newspaper_translator.gmail import import_from_gmail, retry_failed_gmail_messages
from newspaper_translator.mineru import MineruClient
from newspaper_translator.pdf import extract_articles_from_mineru_markdown, parse_pdf_articles
from newspaper_translator.runtime import build_runtime_report
from newspaper_translator.worker import (
    build_process_one_document_from_env,
    build_run_scheduler_tick_from_env,
)


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
    check_parser.add_argument("--gmail-config-path")

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

    phase3_parse_pdf_parser = subparsers.add_parser("phase3-parse-pdf")
    phase3_parse_pdf_parser.add_argument("--pdf-path", required=True)
    phase3_parse_pdf_parser.add_argument("--output-root", required=True)

    phase3_parse_md_parser = subparsers.add_parser("phase3-parse-md")
    phase3_parse_md_parser.add_argument("--markdown-path", required=True)

    phase3_persist_document_parser = subparsers.add_parser("phase3-persist-document")
    phase3_persist_document_parser.add_argument("--document-key", required=True)
    phase3_persist_document_parser.add_argument("--database-url")
    phase3_persist_document_parser.add_argument("--output-root", required=True)

    phase3_latest_articles_parser = subparsers.add_parser("phase3-latest-articles")
    phase3_latest_articles_parser.add_argument("--database-url")
    phase3_latest_articles_parser.add_argument("--document-key", required=True)

    phase3_enrich_article_parser = subparsers.add_parser("phase3-enrich-article")
    phase3_enrich_article_parser.add_argument("--database-url")
    phase3_enrich_article_parser.add_argument("--article-id", required=True)

    phase3_latest_enrichment_parser = subparsers.add_parser("phase3-latest-enrichment")
    phase3_latest_enrichment_parser.add_argument("--database-url")
    phase3_latest_enrichment_parser.add_argument("--article-id", required=True)

    phase3_parse_runs_parser = subparsers.add_parser("phase3-parse-runs")
    phase3_parse_runs_parser.add_argument("--database-url")
    phase3_parse_runs_parser.add_argument("--document-key", required=True)

    phase3_parse_run_fragments_parser = subparsers.add_parser("phase3-parse-run-fragments")
    phase3_parse_run_fragments_parser.add_argument("--database-url")
    phase3_parse_run_fragments_parser.add_argument("--parse-run-id", required=True)

    phase3_parse_run_matches_parser = subparsers.add_parser("phase3-parse-run-matches")
    phase3_parse_run_matches_parser.add_argument("--database-url")
    phase3_parse_run_matches_parser.add_argument("--parse-run-id", required=True)

    phase3_parse_run_articles_parser = subparsers.add_parser("phase3-parse-run-articles")
    phase3_parse_run_articles_parser.add_argument("--database-url")
    phase3_parse_run_articles_parser.add_argument("--parse-run-id", required=True)

    scheduler_run_once_parser = subparsers.add_parser("scheduler-run-once")
    scheduler_run_once_parser.add_argument("--database-url")

    process_pending_documents_parser = subparsers.add_parser("process-pending-documents")
    process_pending_documents_parser.add_argument("--database-url")

    retry_document_parser = subparsers.add_parser("retry-document")
    retry_document_parser.add_argument("--database-url")
    retry_document_parser.add_argument("--document-key", required=True)

    document_processing_status_parser = subparsers.add_parser("document-processing-status")
    document_processing_status_parser.add_argument("--database-url")
    document_processing_status_parser.add_argument("--document-key", required=True)

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
            "GMAIL_CONFIG_PATH": _resolve_setting(args.gmail_config_path, "GMAIL_CONFIG_PATH"),
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

    if args.command == "phase3-parse-pdf":
        mineru_settings = MineruSettings.from_env(os.environ)
        mineru_client = MineruClient(settings=mineru_settings)
        continuation_matcher = _build_continuation_matcher_from_env(os.environ)
        articles = parse_pdf_articles(
            Path(args.pdf_path),
            output_root=Path(args.output_root),
            mineru_client=mineru_client,
            continuation_matcher=continuation_matcher,
        )
        return 0, json.dumps(_to_jsonable(articles), sort_keys=True)

    if args.command == "phase3-parse-md":
        markdown_text = Path(args.markdown_path).read_text(encoding="utf-8")
        continuation_matcher = _build_continuation_matcher_from_env(os.environ)
        articles = extract_articles_from_mineru_markdown(
            markdown_text,
            continuation_matcher=continuation_matcher,
        )
        return 0, json.dumps(_to_jsonable(articles), sort_keys=True)

    if args.command == "phase3-persist-document":
        mineru_settings = MineruSettings.from_env(os.environ)
        mineru_client = MineruClient(settings=mineru_settings)
        continuation_matcher = _build_continuation_matcher_from_env(os.environ)
        parse_run = persist_document_articles(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            document_key=args.document_key,
            output_root=Path(args.output_root),
            mineru_client=mineru_client,
            continuation_matcher=continuation_matcher,
            parser_name="mineru",
            parser_version=mineru_settings.model_version,
            continuation_matcher_name=_continuation_matcher_name_from_env(os.environ),
            continuation_matcher_version=_continuation_matcher_version_from_env(os.environ),
        )
        return 0, json.dumps(_to_jsonable(parse_run), sort_keys=True)

    if args.command == "phase3-latest-articles":
        articles = list_latest_document_articles(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            document_key=args.document_key,
        )
        return 0, json.dumps(_to_jsonable(articles), sort_keys=True)

    if args.command == "phase3-enrich-article":
        gemini_settings = GeminiSettings.from_env(os.environ)
        enrichment_run = enrich_article(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            article_id=args.article_id,
            translator=GeminiArticleTranslator(settings=gemini_settings),
            summarizer_tagger=GeminiArticleSummarizerTagger(settings=gemini_settings),
            provider_name="gemini",
            model_name=gemini_settings.model,
            prompt_version="article-enrichment-v2",
        )
        return 0, json.dumps(_to_jsonable(enrichment_run), sort_keys=True)

    if args.command == "phase3-latest-enrichment":
        enrichment = get_latest_article_enrichment(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            article_id=args.article_id,
        )
        return 0, json.dumps(_to_jsonable(enrichment), sort_keys=True)

    if args.command == "phase3-parse-runs":
        runs = list_parse_runs(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            document_key=args.document_key,
        )
        return 0, json.dumps(_to_jsonable(runs), sort_keys=True)

    if args.command == "phase3-parse-run-fragments":
        fragments = list_parse_run_fragments(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            parse_run_id=args.parse_run_id,
        )
        return 0, json.dumps(_to_jsonable(fragments), sort_keys=True)

    if args.command == "phase3-parse-run-matches":
        matches = list_parse_run_continuation_matches(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            parse_run_id=args.parse_run_id,
        )
        return 0, json.dumps(_to_jsonable(matches), sort_keys=True)

    if args.command == "phase3-parse-run-articles":
        articles = list_parse_run_final_articles(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            parse_run_id=args.parse_run_id,
        )
        return 0, json.dumps(_to_jsonable(articles), sort_keys=True)

    if args.command == "scheduler-run-once":
        resolved_env = _build_cli_env_overrides(
            database_url=args.database_url,
        )
        run_tick = build_run_scheduler_tick_from_env(resolved_env)
        scheduler_run_id = run_tick(trigger_type="manual")
        return 0, json.dumps(
            {
                "scheduler_run_id": scheduler_run_id,
                "trigger_type": "manual",
            },
            sort_keys=True,
        )

    if args.command == "process-pending-documents":
        resolved_env = _build_cli_env_overrides(
            database_url=args.database_url,
        )
        scheduler_run = run_process_pending_documents_from_env(resolved_env)
        return 0, json.dumps(_to_jsonable(scheduler_run), sort_keys=True)

    if args.command == "retry-document":
        run = request_manual_document_retry(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            document_key=args.document_key,
        )
        return 0, json.dumps(_to_jsonable(run), sort_keys=True)

    if args.command == "document-processing-status":
        run = get_document_processing_run(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            document_key=args.document_key,
        )
        return 0, json.dumps(_to_jsonable(run), sort_keys=True)

    return 1, "Unknown command"


def main() -> None:
    exit_code, output = run_cli(sys.argv[1:])
    print(output)
    raise SystemExit(exit_code)


def _resolve_setting(value: str | None, env_key: str) -> str:
    if value:
        return value
    return os.environ.get(env_key, "")


def run_process_pending_documents_from_env(env: dict[str, str]):
    resolved_env = dict(os.environ)
    resolved_env.update(env)
    database_url = resolved_env["DATABASE_URL"]
    process_one_document = build_process_one_document_from_env(resolved_env)
    document_limit = _read_int_setting(
        resolved_env,
        "DOCUMENT_WORKER_CONCURRENCY",
        default=2,
    )

    return run_scheduler_tick(
        database_url=database_url,
        trigger_type="manual",
        import_documents=lambda: {},
        process_one_document=process_one_document,
        document_limit=document_limit,
    )


def _build_cli_env_overrides(*, database_url: str | None = None) -> dict[str, str]:
    resolved_env = dict(os.environ)
    if database_url:
        resolved_env["DATABASE_URL"] = database_url
    return resolved_env


def _build_continuation_matcher_from_env(env) -> GeminiContinuationMatcher | None:
    if not env.get("GEMINI_TOKEN", "").strip():
        return None
    settings = GeminiSettings.from_env(env)
    return GeminiContinuationMatcher(settings=settings)


def _continuation_matcher_name_from_env(env) -> str:
    if not env.get("GEMINI_TOKEN", "").strip():
        return ""
    return "gemini"


def _continuation_matcher_version_from_env(env) -> str:
    if not env.get("GEMINI_TOKEN", "").strip():
        return ""
    return env.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def _read_int_setting(env, key: str, *, default: int) -> int:
    value = env.get(key)
    if value is None or not value.strip():
        return default
    return int(value.strip())


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
