import hashlib
import json

from newspaper_translator.article_store import (
    ArticleEnrichmentRun,
    create_article_enrichment_run,
    find_successful_article_enrichment_by_article_key_and_input_hash,
    finalize_article_enrichment_run,
    get_article_enrichment_run,
    get_final_article,
    record_article_enrichment_outputs,
)


def enrich_article(
    *,
    database_url: str,
    article_id: str,
    enricher,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    on_step_advance=None,
    force_reenrich: bool = False,
) -> ArticleEnrichmentRun:
    article = get_final_article(
        database_url=database_url,
        article_id=article_id,
    )
    input_hash = build_article_input_hash(article)
    if not force_reenrich:
        reusable_run = find_successful_article_enrichment_by_article_key_and_input_hash(
            database_url=database_url,
            article_key=article.article_key,
            input_hash=input_hash,
        )
        if reusable_run is not None:
            return reusable_run
    enrichment_run = create_article_enrichment_run(
        database_url=database_url,
        article_id=article.article_id,
        parse_run_id=article.parse_run_id,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        input_hash=input_hash,
    )

    try:
        result = enricher(article, on_step_advance=on_step_advance)
    except Exception as exc:  # noqa: BLE001
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="failed",
            error_message=str(exc),
        )
        return get_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
        )

    if result.content_type == "advertisement":
        record_article_enrichment_outputs(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            translated_title_zh=None,
            summary_zh=None,
            translated_body_zh=None,
            translation_status="skipped",
            summary_status="skipped",
            tagging_status="skipped",
            tags=[],
            content_type="advertisement",
            classification_reason=result.classification_reason or "",
        )
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="skipped_advertisement",
        )
    elif result.translation_status != "succeeded":
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="failed",
            error_message=result.error_message
            or "article enrichment failed before translation",
        )
    else:
        record_article_enrichment_outputs(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            translated_title_zh=result.translated_title_zh,
            summary_zh=result.summary_zh if result.summary_status == "succeeded" else None,
            translated_body_zh=result.translated_body_zh,
            translation_status="succeeded",
            summary_status=result.summary_status,
            tagging_status=result.tagging_status,
            tags=result.tags if result.tagging_status == "succeeded" else [],
            content_type=result.content_type,
            classification_reason=result.classification_reason or "",
        )
        if result.summary_status == "succeeded" and result.tagging_status == "succeeded":
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="succeeded",
            )
        else:
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="partial",
                error_message=result.error_message,
            )

    return get_article_enrichment_run(
        database_url=database_url,
        enrichment_run_id=enrichment_run.enrichment_run_id,
    )


def build_article_input_hash(article) -> str:
    payload = {
        "article_key": article.article_key,
        "publication_date": article.publication_date,
        "title_en": article.title_en,
        "body_text_en": article.body_text_en,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
