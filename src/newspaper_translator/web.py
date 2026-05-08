from dataclasses import asdict, is_dataclass
import json
import mimetypes
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from newspaper_translator.api.queries import (
    get_article_detail_view,
    get_article_processing_detail_view,
    get_article_processing_filter_options_view,
    get_document_processing_detail_view,
    get_filter_options_view,
    get_overview_view,
    list_article_card_views,
    list_article_processing_card_views,
    list_focus_tag_article_card_views,
)
from newspaper_translator.document_processing import (
    list_document_processing_runs,
    request_manual_article_retry,
    request_manual_document_retry,
    retry_article_processing_runs,
)
from newspaper_translator.gmail import import_from_gmail
from newspaper_translator.import_audit import (
    get_import_run,
    list_import_items,
    list_import_run_items,
    list_import_runs,
)
from newspaper_translator.runtime import build_runtime_report


def create_app(env: Mapping[str, str]):
    runtime_report = build_runtime_report(env=env, service="web")
    database_url = env["DATABASE_URL"]
    storage_root = env["STORAGE_ROOT"]
    gmail_config_path = env["GMAIL_CONFIG_PATH"]
    focus_tags = _read_csv_setting(env, "FOCUS_TAGS")

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)

        if path == "/healthz":
            payload = runtime_report
            body = json.dumps(payload).encode("utf-8")
            headers = [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
            start_response("200 OK", headers)
            return [body]

        if path == "/api/local-image":
            image_path = _query_value(query, "path")
            if not image_path:
                return _json_response(start_response, "400 Bad Request", {"status": "missing_path"})
            file_path = Path(image_path)
            if not file_path.is_absolute() or not file_path.exists() or not file_path.is_file():
                return _json_response(start_response, "404 Not Found", {"status": "image_not_found"})

            mime_type, _ = mimetypes.guess_type(str(file_path))
            body = file_path.read_bytes()
            headers = [
                ("Content-Type", mime_type or "application/octet-stream"),
                ("Content-Length", str(len(body))),
            ]
            start_response("200 OK", headers)
            return [body]

        if path == "/import-runs":
            payload = {
                "runs": _to_jsonable(
                    list_import_runs(
                        database_url=database_url,
                        limit=_query_int(query, "limit", default=20),
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path == "/import-items":
            payload = {
                "items": _to_jsonable(
                    list_import_items(
                        database_url=database_url,
                        limit=_query_int(query, "limit", default=50),
                        status=_query_value(query, "status"),
                        item_type=_query_value(query, "item_type"),
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path == "/api/gmail/import":
            if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
                return _json_response(
                    start_response,
                    "405 Method Not Allowed",
                    {"status": "method_not_allowed"},
                )
            try:
                import_summary = import_from_gmail(
                    config_path=Path(gmail_config_path),
                    storage_root=Path(storage_root),
                    database_url=database_url,
                )
            except Exception as exc:  # noqa: BLE001
                return _json_response(
                    start_response,
                    "500 Internal Server Error",
                    {
                        "status": "gmail_import_failed",
                        "error": str(exc),
                    },
                )
            return _json_response(
                start_response,
                "200 OK",
                {"import_run": _to_jsonable(import_summary)},
            )

        if path == "/api/articles":
            articles, pagination = list_article_card_views(
                database_url=database_url,
                source=_query_value(query, "source"),
                tag=_query_value(query, "tag"),
                publication_date_from=_query_value(query, "publication_date_from"),
                publication_date_to=_query_value(query, "publication_date_to"),
                reading_status=_query_value(query, "reading_status"),
                processing_status=_query_value(query, "processing_status"),
                page=_query_int(query, "page", default=1),
                page_size=_query_int(query, "page_size", default=20),
                include_pagination=True,
            )
            payload = {
                "articles": _to_jsonable(articles),
                "pagination": _to_jsonable(pagination),
            }
            return _json_response(start_response, "200 OK", payload)

        if path.startswith("/api/articles/"):
            article_id = path.removeprefix("/api/articles/")
            payload = {
                "article": _to_jsonable(
                    get_article_detail_view(
                        database_url=database_url,
                        article_id=article_id,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path == "/api/overview":
            payload = {
                "overview": _to_jsonable(
                    get_overview_view(
                        database_url=database_url,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path == "/api/filters":
            payload = {
                "filters": _to_jsonable(
                    get_filter_options_view(
                        database_url=database_url,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path == "/api/focus-tags/articles":
            payload = {
                "articles": _to_jsonable(
                    list_focus_tag_article_card_views(
                        database_url=database_url,
                        focus_tags=focus_tags,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path in {"/document-processing", "/api/document-processing"}:
            payload = {
                "runs": _to_jsonable(
                    list_document_processing_runs(
                        database_url=database_url,
                        limit=_query_int(query, "limit", default=50),
                        status=_query_value(query, "status"),
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path in {"/article-processing", "/api/article-processing"}:
            runs, pagination = list_article_processing_card_views(
                database_url=database_url,
                limit=None,
                page=_query_int(query, "page", default=1),
                page_size=_query_int(query, "page_size", default=_query_int(query, "limit", default=50)),
                status=_query_value(query, "status"),
                source=_query_value(query, "source"),
                publication_date_from=_query_value(query, "publication_date_from"),
                publication_date_to=_query_value(query, "publication_date_to"),
                step=_query_value(query, "step"),
                error_message=_query_value(query, "error_message"),
                include_pagination=True,
            )
            payload = {
                "runs": _to_jsonable(runs),
                "pagination": _to_jsonable(pagination),
            }
            return _json_response(start_response, "200 OK", payload)

        if path == "/api/article-processing/filter-options":
            payload = _to_jsonable(
                get_article_processing_filter_options_view(
                    database_url=database_url,
                    status=_query_value(query, "status"),
                    source=_query_value(query, "source"),
                    publication_date_from=_query_value(query, "publication_date_from"),
                    publication_date_to=_query_value(query, "publication_date_to"),
                    step=_query_value(query, "step"),
                )
            )
            return _json_response(start_response, "200 OK", payload)

        if path == "/api/article-processing/retry-batch":
            if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
                return _json_response(
                    start_response,
                    "405 Method Not Allowed",
                    {"status": "method_not_allowed"},
                )
            try:
                request = _read_json_request(environ)
            except _JsonRequestError as exc:
                return _json_response(
                    start_response,
                    "400 Bad Request",
                    {"status": exc.status},
                )
            mode = request.get("mode")
            if mode not in {"selection", "filtered"}:
                return _json_response(
                    start_response,
                    "400 Bad Request",
                    {"status": "unsupported_retry_batch_mode"},
                )
            filters = request.get("filters", {})
            article_keys = request.get("article_keys")
            if mode == "filtered":
                if not isinstance(filters, dict):
                    return _json_response(
                        start_response,
                        "400 Bad Request",
                        {"status": "invalid_filtered_filters"},
                    )
                for filter_key in (
                    "status",
                    "source",
                    "publication_date_from",
                    "publication_date_to",
                    "step",
                    "error_message",
                ):
                    filter_value = filters.get(filter_key)
                    if filter_value is not None and not isinstance(filter_value, str):
                        return _json_response(
                            start_response,
                            "400 Bad Request",
                            {"status": "invalid_filtered_filter_value"},
                        )
                summary = retry_article_processing_runs(
                    database_url=database_url,
                    article_keys=None,
                    status=filters.get("status"),
                    source=filters.get("source"),
                    publication_date_from=filters.get("publication_date_from"),
                    publication_date_to=filters.get("publication_date_to"),
                    step=filters.get("step"),
                    error_message=filters.get("error_message"),
                )
            else:
                if (
                    not isinstance(article_keys, list)
                    or any(not isinstance(article_key, str) for article_key in article_keys)
                ):
                    return _json_response(
                        start_response,
                        "400 Bad Request",
                        {"status": "invalid_selection_article_keys"},
                    )
                summary = retry_article_processing_runs(
                    database_url=database_url,
                    article_keys=article_keys,
                )
            return _json_response(start_response, "200 OK", _to_jsonable(summary))

        if path.startswith("/document-processing/") or path.startswith("/api/document-processing/"):
            prefix = "/api/document-processing/" if path.startswith("/api/document-processing/") else "/document-processing/"
            suffix = path.removeprefix(prefix)
            if suffix.endswith("/retry"):
                document_key = suffix.removesuffix("/retry").rstrip("/")
                payload = {
                    "run": _to_jsonable(
                        request_manual_document_retry(
                            database_url=database_url,
                            document_key=document_key,
                        )
                    )
                }
                return _json_response(start_response, "200 OK", payload)

            payload = {
                "run": _to_jsonable(
                    get_document_processing_detail_view(
                        database_url=database_url,
                        document_key=suffix,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path.startswith("/article-processing/") or path.startswith("/api/article-processing/"):
            prefix = "/api/article-processing/" if path.startswith("/api/article-processing/") else "/article-processing/"
            suffix = path.removeprefix(prefix)
            if suffix.endswith("/retry"):
                article_key = suffix.removesuffix("/retry").rstrip("/")
                payload = {
                    "run": _to_jsonable(
                        request_manual_article_retry(
                            database_url=database_url,
                            article_key=article_key,
                        )
                    )
                }
                return _json_response(start_response, "200 OK", payload)

            payload = {
                "run": _to_jsonable(
                    get_article_processing_detail_view(
                        database_url=database_url,
                        article_key=suffix,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        if path.startswith("/import-runs/"):
            suffix = path.removeprefix("/import-runs/")
            if suffix.endswith("/items"):
                run_id = suffix.removesuffix("/items")
                payload = {
                    "items": _to_jsonable(
                        list_import_run_items(
                            database_url=database_url,
                            run_id=run_id,
                            status=_query_value(query, "status"),
                            item_type=_query_value(query, "item_type"),
                        )
                    )
                }
                return _json_response(start_response, "200 OK", payload)

            payload = {
                "run": _to_jsonable(
                    get_import_run(
                        database_url=database_url,
                        run_id=suffix,
                    )
                )
            }
            return _json_response(start_response, "200 OK", payload)

        body = json.dumps({"status": "not_found"}).encode("utf-8")
        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ]
        start_response("404 Not Found", headers)
        return [body]

    return app


def _json_response(start_response, status: str, payload: dict[str, object]):
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status, headers)
    return [body]


class _JsonRequestError(ValueError):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


def _read_json_request(environ) -> dict[str, object]:
    body_stream = environ.get("wsgi.input")
    if body_stream is None:
        return {}
    content_length = environ.get("CONTENT_LENGTH", "")
    try:
        body_size = int(content_length) if content_length else 0
    except ValueError:
        body_size = 0
    raw_body = body_stream.read(body_size) if body_size > 0 else b""
    if not raw_body:
        return {}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _JsonRequestError("invalid_json_request") from exc
    if isinstance(payload, dict):
        return payload
    raise _JsonRequestError("invalid_request_body")


def _query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key, [])
    if not values:
        return None
    return values[0]


def _query_int(query: dict[str, list[str]], key: str, *, default: int) -> int:
    value = _query_value(query, key)
    if value is None:
        return default
    return int(value)


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


def _read_csv_setting(env: Mapping[str, str], key: str) -> list[str]:
    raw_value = env.get(key, "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    app = create_app(os.environ)
    with make_server("0.0.0.0", port, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
