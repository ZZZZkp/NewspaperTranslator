from dataclasses import asdict, is_dataclass
import json
import os
from typing import Mapping
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from newspaper_translator.document_processing import (
    get_document_processing_run,
    list_document_processing_runs,
    request_manual_document_retry,
)
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

        if path == "/document-processing":
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

        if path.startswith("/document-processing/"):
            suffix = path.removeprefix("/document-processing/")
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
                    get_document_processing_run(
                        database_url=database_url,
                        document_key=suffix,
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


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    app = create_app(os.environ)
    with make_server("0.0.0.0", port, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
