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
    translator,
    summarizer_tagger,
    provider_name: str,
    model_name: str,
    prompt_version: str,
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
        translation = translator(article)
        if translation.content_type == "advertisement":
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
                classification_reason=translation.classification_reason,
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="skipped_advertisement",
            )
        else:
            try:
                summary_and_tags = summarizer_tagger(
                    article=article,
                    translated_title_zh=translation.translated_title_zh,
                    translated_body_zh=translation.translated_body_zh,
                )
            except Exception as exc:
                record_article_enrichment_outputs(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    translated_title_zh=translation.translated_title_zh,
                    summary_zh=None,
                    translated_body_zh=translation.translated_body_zh,
                    translation_status="succeeded",
                    summary_status="failed",
                    tagging_status="failed",
                    tags=[],
                    content_type=translation.content_type,
                    classification_reason=translation.classification_reason,
                )
                finalize_article_enrichment_run(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    status="partial",
                    error_message=str(exc),
                )
            else:
                record_article_enrichment_outputs(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    translated_title_zh=translation.translated_title_zh,
                    summary_zh=summary_and_tags.summary_zh,
                    translated_body_zh=translation.translated_body_zh,
                    translation_status="succeeded",
                    summary_status="succeeded",
                    tagging_status="succeeded",
                    tags=summary_and_tags.tags,
                    content_type=translation.content_type,
                    classification_reason=translation.classification_reason,
                )
                finalize_article_enrichment_run(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    status="succeeded",
                )
    except Exception as exc:
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
