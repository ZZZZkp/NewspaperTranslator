import json
import os
from typing import Mapping
from wsgiref.simple_server import make_server

from newspaper_translator.runtime import build_runtime_report


def create_app(env: Mapping[str, str]):
    runtime_report = build_runtime_report(env=env, service="web")

    def app(environ, start_response):
        if environ.get("PATH_INFO") == "/healthz":
            payload = runtime_report
            body = json.dumps(payload).encode("utf-8")
            headers = [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
            start_response("200 OK", headers)
            return [body]

        body = json.dumps({"status": "not_found"}).encode("utf-8")
        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ]
        start_response("404 Not Found", headers)
        return [body]

    return app


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    app = create_app(os.environ)
    with make_server("0.0.0.0", port, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
