from datetime import datetime, timedelta
import os
from pathlib import Path
import time

from newspaper_translator.config import AppSettings, GeminiSettings, MineruSettings
from newspaper_translator.document_processing import (
    get_latest_scheduler_run,
    process_article_processing_run,
    process_document,
    recover_stale_article_runs,
    recover_stale_document_runs,
    run_scheduler_tick,
)
from newspaper_translator.gemini import (
    GeminiArticleSummarizerTagger,
    GeminiArticleTranslator,
    GeminiContinuationMatcher,
)
from newspaper_translator.gmail import import_from_gmail
from newspaper_translator.logging_utils import format_log_event
from newspaper_translator.mineru import MineruClient
from newspaper_translator.runtime import build_runtime_report


def build_startup_report(env: dict[str, str]) -> dict[str, object]:
    return build_runtime_report(env=env, service="worker")


def build_startup_log_line(
    env: dict[str, str],
    *,
    timestamp: str | None = None,
) -> str:
    report = build_startup_report(env)
    return format_log_event(
        level="INFO" if report["status"] == "ok" else "ERROR",
        event="worker.startup",
        service="worker",
        details=report,
        timestamp=timestamp,
    )


def should_run_catch_up_tick(
    *,
    last_scheduler_run_started_at: str | None,
    now: str,
    interval_seconds: int,
) -> bool:
    if not last_scheduler_run_started_at:
        return True
    last_started_at = _parse_timestamp(last_scheduler_run_started_at)
    now_dt = _parse_timestamp(now)
    return now_dt - last_started_at >= timedelta(seconds=interval_seconds)


def run_startup_maintenance(
    *,
    last_scheduler_run_started_at: str | None,
    now: str,
    interval_seconds: int,
    recover_stale_document_runs,
    recover_stale_article_runs=lambda: [],
    run_scheduler_tick,
) -> dict[str, object]:
    recovered_document_runs = recover_stale_document_runs()
    recovered_article_runs = recover_stale_article_runs()
    catch_up_triggered = should_run_catch_up_tick(
        last_scheduler_run_started_at=last_scheduler_run_started_at,
        now=now,
        interval_seconds=interval_seconds,
    )
    scheduler_run_id = None
    if catch_up_triggered:
        scheduler_run_id = run_scheduler_tick(trigger_type="interval")

    return {
        "recovered_document_keys": [
            getattr(run, "document_key", run)
            for run in recovered_document_runs
        ],
        "recovered_article_keys": [
            getattr(run, "article_key", run)
            for run in recovered_article_runs
        ],
        "catch_up_triggered": catch_up_triggered,
        "scheduler_run_id": scheduler_run_id,
    }


def get_last_scheduler_run_started_at(*, database_url: str) -> str | None:
    latest_scheduler_run = get_latest_scheduler_run(database_url=database_url)
    if latest_scheduler_run is None:
        return None
    return latest_scheduler_run.started_at


def build_run_scheduler_tick_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)
    document_limit = _read_int_setting(
        env,
        "DOCUMENT_WORKER_CONCURRENCY",
        default=2,
    )
    article_limit = _read_int_setting(
        env,
        "ARTICLE_WORKER_CONCURRENCY",
        default=document_limit,
    )
    process_one_document = build_process_one_document_from_env(env)
    process_one_article = build_process_one_article_from_env(env)

    def import_documents():
        return import_from_gmail(
            config_path=Path(app_settings.gmail_config_path),
            storage_root=Path(app_settings.storage_root),
            database_url=app_settings.database_url,
        )

    def run_tick(*, trigger_type: str) -> str:
        scheduler_run = run_scheduler_tick(
            database_url=app_settings.database_url,
            trigger_type=trigger_type,
            import_documents=import_documents,
            process_one_document=process_one_document,
            document_limit=document_limit,
            process_one_article=process_one_article,
            article_limit=article_limit,
        )
        return scheduler_run.scheduler_run_id

    return run_tick


def build_process_one_document_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)
    mineru_settings = MineruSettings.from_env(env)
    gemini_settings = GeminiSettings.from_env(env)
    output_root = Path(app_settings.storage_root) / "phase3-output"
    step_retry_limit = _read_int_setting(
        env,
        "STEP_RETRY_LIMIT",
        default=2,
    )
    lock_timeout_seconds = _read_int_setting(
        env,
        "DOCUMENT_LOCK_TIMEOUT_SECONDS",
        default=600,
    )
    prompt_version = (
        env.get("ARTICLE_ENRICHMENT_PROMPT_VERSION", "article-enrichment-v2").strip()
        or "article-enrichment-v2"
    )

    mineru_client = MineruClient(settings=mineru_settings)
    continuation_matcher = _build_continuation_matcher_from_env(env)
    translator = GeminiArticleTranslator(settings=gemini_settings)
    summarizer_tagger = GeminiArticleSummarizerTagger(settings=gemini_settings)

    def process_one_document_callback(*, document_key: str, scheduler_run_id: str, locked_by: str):
        return process_document(
            database_url=app_settings.database_url,
            document_key=document_key,
            locked_by=locked_by,
            output_root=output_root,
            mineru_client=mineru_client,
            continuation_matcher=continuation_matcher,
            parser_name="mineru",
            parser_version=mineru_settings.model_version,
            continuation_matcher_name=_continuation_matcher_name_from_env(env),
            continuation_matcher_version=_continuation_matcher_version_from_env(env),
            translator=translator,
            summarizer_tagger=summarizer_tagger,
            provider_name="gemini",
            model_name=gemini_settings.model,
            prompt_version=prompt_version,
            step_retry_limit=step_retry_limit,
            lock_timeout_seconds=lock_timeout_seconds,
            scheduler_run_id=scheduler_run_id,
        )

    return process_one_document_callback


def build_recover_stale_document_runs_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)
    running_timeout_seconds = _read_int_setting(
        env,
        "RUNNING_TIMEOUT_SECONDS",
        default=14400,
    )

    def recover():
        return recover_stale_document_runs(
            database_url=app_settings.database_url,
            running_timeout_seconds=running_timeout_seconds,
        )

    return recover


def build_process_one_article_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)
    gemini_settings = GeminiSettings.from_env(env)
    automatic_failure_limit = _read_int_setting(
        env,
        "STEP_RETRY_LIMIT",
        default=2,
    )
    lock_timeout_seconds = _read_int_setting(
        env,
        "ARTICLE_LOCK_TIMEOUT_SECONDS",
        default=600,
    )
    prompt_version = (
        env.get("ARTICLE_ENRICHMENT_PROMPT_VERSION", "article-enrichment-v2").strip()
        or "article-enrichment-v2"
    )
    translator = GeminiArticleTranslator(settings=gemini_settings)
    summarizer_tagger = GeminiArticleSummarizerTagger(settings=gemini_settings)

    def process_one_article_callback(*, article_key: str, locked_by: str):
        return process_article_processing_run(
            database_url=app_settings.database_url,
            article_key=article_key,
            locked_by=locked_by,
            translator=translator,
            summarizer_tagger=summarizer_tagger,
            provider_name="gemini",
            model_name=gemini_settings.model,
            prompt_version=prompt_version,
            lock_timeout_seconds=lock_timeout_seconds,
            automatic_failure_limit=automatic_failure_limit,
        )

    return process_one_article_callback


def build_recover_stale_article_runs_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)
    running_timeout_seconds = _read_int_setting(
        env,
        "RUNNING_TIMEOUT_SECONDS",
        default=14400,
    )
    automatic_failure_limit = _read_int_setting(
        env,
        "STEP_RETRY_LIMIT",
        default=2,
    )

    def recover():
        return recover_stale_article_runs(
            database_url=app_settings.database_url,
            running_timeout_seconds=running_timeout_seconds,
            automatic_failure_limit=automatic_failure_limit,
        )

    return recover


def run_worker_loop(
    *,
    env: dict[str, str],
    now_fn=None,
    sleep_fn=None,
    max_loops: int | None = None,
    run_startup_maintenance_fn=run_startup_maintenance,
    get_last_scheduler_run_started_at_fn=get_last_scheduler_run_started_at,
    recover_stale_document_runs_fn=None,
    recover_stale_article_runs_fn=None,
    run_scheduler_tick_fn=None,
) -> None:
    app_settings = AppSettings.from_env(env)
    now = now_fn or _current_timestamp
    sleep = sleep_fn or time.sleep
    scheduler_interval_seconds = _read_int_setting(
        env,
        "SCHEDULER_INTERVAL_SECONDS",
        default=7200,
    )
    poll_interval_seconds = _read_int_setting(
        env,
        "WORKER_POLL_INTERVAL_SECONDS",
        default=60,
    )
    recover = recover_stale_document_runs_fn or build_recover_stale_document_runs_from_env(env)
    recover_articles = recover_stale_article_runs_fn or build_recover_stale_article_runs_from_env(env)
    run_tick = run_scheduler_tick_fn or build_run_scheduler_tick_from_env(env)

    run_startup_maintenance_fn(
        last_scheduler_run_started_at=get_last_scheduler_run_started_at_fn(
            database_url=app_settings.database_url,
        ),
        now=now(),
        interval_seconds=scheduler_interval_seconds,
        recover_stale_document_runs=recover,
        recover_stale_article_runs=recover_articles,
        run_scheduler_tick=run_tick,
    )

    loop_count = 0
    while max_loops is None or loop_count < max_loops:
        sleep(poll_interval_seconds)
        if should_run_catch_up_tick(
            last_scheduler_run_started_at=get_last_scheduler_run_started_at_fn(
                database_url=app_settings.database_url,
            ),
            now=now(),
            interval_seconds=scheduler_interval_seconds,
        ):
            run_tick(trigger_type="interval")
        loop_count += 1


def main() -> None:
    env = dict(os.environ)
    print(build_startup_log_line(env), flush=True)
    run_worker_loop(env=env)


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")


def _current_timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _build_continuation_matcher_from_env(env: dict[str, str]) -> GeminiContinuationMatcher | None:
    if not _gemini_is_configured(env):
        return None
    return GeminiContinuationMatcher(settings=GeminiSettings.from_env(env))


def _continuation_matcher_name_from_env(env: dict[str, str]) -> str:
    if not _gemini_is_configured(env):
        return ""
    return "gemini"


def _continuation_matcher_version_from_env(env: dict[str, str]) -> str:
    if not _gemini_is_configured(env):
        return ""
    return env.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def _gemini_is_configured(env: dict[str, str]) -> bool:
    api_compat_mode = env.get("GEMINI_API_COMPAT_MODE", "standard").strip() or "standard"
    if api_compat_mode == "openai_compatible":
        return bool(env.get("GEMINI_API_KEY", "").strip())
    return bool(env.get("GEMINI_TOKEN", "").strip())


def _read_int_setting(env: dict[str, str], key: str, *, default: int) -> int:
    value = env.get(key)
    if value is None or not value.strip():
        return default
    return int(value.strip())


if __name__ == "__main__":
    main()
