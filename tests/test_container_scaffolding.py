import pathlib
import subprocess
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


class ContainerScaffoldingTests(unittest.TestCase):
    def test_project_includes_a_docker_compose_file_with_web_worker_and_db_services(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn("services:", compose_text)
        self.assertIn("web:", compose_text)
        self.assertIn("worker:", compose_text)
        self.assertIn("db:", compose_text)

    def test_compose_runs_real_web_and_worker_entrypoints(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn('command: ["python", "-m", "newspaper_translator.web"]', compose_text)
        self.assertIn('command: ["python", "-m", "newspaper_translator.worker"]', compose_text)

    def test_compose_declares_runtime_healthchecks_and_dependency_conditions(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn("healthcheck:", compose_text)
        self.assertIn('test: ["CMD", "python", "-m", "newspaper_translator.manage", "check"', compose_text)
        self.assertIn("condition: service_started", compose_text)

    def test_compose_passes_model_and_proxy_settings_to_web_and_worker(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn("MINERU_API_TOKEN:", compose_text)
        self.assertIn("MINERU_MODEL_VERSION:", compose_text)
        self.assertIn("MINERU_LANGUAGE:", compose_text)
        self.assertIn("DEEPSEEK_API_KEY:", compose_text)
        self.assertIn("DEEPSEEK_BASE_URL:", compose_text)
        self.assertIn("DEEPSEEK_MODEL:", compose_text)
        self.assertIn("DEEPSEEK_TIMEOUT_SECONDS:", compose_text)
        self.assertIn("GEMINI_TOKEN:", compose_text)
        self.assertIn("HTTP_PROXY:", compose_text)
        self.assertIn("HTTPS_PROXY:", compose_text)
        self.assertIn("ALL_PROXY:", compose_text)
        self.assertIn("HTTP_PROXY: ${HTTP_PROXY:-http://host.docker.internal:7897}", compose_text)
        self.assertIn("HTTPS_PROXY: ${HTTPS_PROXY:-http://host.docker.internal:7897}", compose_text)
        self.assertIn("ALL_PROXY: ${ALL_PROXY:-socks5://host.docker.internal:7897}", compose_text)

    def test_compose_passes_proxy_settings_into_image_builds(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn("args:", compose_text)
        self.assertIn("HTTP_PROXY: ${HTTP_PROXY:-http://host.docker.internal:7897}", compose_text)
        self.assertIn("HTTPS_PROXY: ${HTTPS_PROXY:-http://host.docker.internal:7897}", compose_text)
        self.assertIn("ALL_PROXY: ${ALL_PROXY:-socks5://host.docker.internal:7897}", compose_text)
        self.assertIn("NO_PROXY: ${NO_PROXY:-localhost,127.0.0.1,db}", compose_text)

    def test_compose_mounts_local_gmail_config_and_writable_secrets_into_web_and_worker(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn("./config:/app/config:ro", compose_text)
        self.assertIn("./secrets:/app/secrets", compose_text)
        self.assertNotIn("./secrets:/app/secrets:ro", compose_text)

    def test_project_includes_an_env_example_for_container_runtime(self) -> None:
        env_example_path = PROJECT_ROOT / ".env.example"
        self.assertTrue(env_example_path.exists(), ".env.example should exist at the project root")

        env_text = env_example_path.read_text()

        self.assertIn("APP_ENV=", env_text)
        self.assertIn("DATABASE_URL=", env_text)
        self.assertIn("STORAGE_ROOT=", env_text)
        self.assertIn("GMAIL_CONFIG_PATH=", env_text)
        self.assertIn("FRONTEND_PORT=", env_text)
        self.assertIn("WEB_PORT=", env_text)
        self.assertIn("DEEPSEEK_API_KEY=", env_text)
        self.assertIn("DEEPSEEK_BASE_URL=", env_text)
        self.assertIn("DEEPSEEK_MODEL=", env_text)
        self.assertIn("DEEPSEEK_TIMEOUT_SECONDS=", env_text)
        self.assertIn("GEMINI_TOKEN=", env_text)
        self.assertIn("HTTP_PROXY=", env_text)
        self.assertIn("HTTPS_PROXY=", env_text)
        self.assertIn("ALL_PROXY=", env_text)

    def test_compose_avoids_default_host_port_conflicts_for_db_and_allows_configurable_web_ports(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist at the project root")

        compose_text = compose_path.read_text()

        self.assertIn('${FRONTEND_PORT:-3000}:3000', compose_text)
        self.assertIn('${WEB_PORT:-8000}:8000', compose_text)
        self.assertNotIn('5432:5432', compose_text)

    def test_project_includes_a_readme_with_local_startup_steps(self) -> None:
        readme_path = PROJECT_ROOT / "README.md"
        self.assertTrue(readme_path.exists(), "README.md should exist at the project root")

        readme_text = readme_path.read_text()

        self.assertIn("docker compose up --build", readme_text)
        self.assertIn("python -m unittest discover -s tests -v", readme_text)
        self.assertIn("python -m newspaper_translator.manage gmail-import", readme_text)

    def test_project_includes_a_gmail_config_template(self) -> None:
        config_template_path = PROJECT_ROOT / "config" / "gmail-config.json"
        self.assertTrue(
            config_template_path.exists(),
            "config/gmail-config.json should exist as a local Gmail integration template",
        )

        config_text = config_template_path.read_text()

        self.assertIn('"oauth_client_secrets_path"', config_text)
        self.assertIn('"oauth_token_path"', config_text)
        self.assertIn('"allowed_senders"', config_text)
        self.assertIn('"query"', config_text)
        self.assertIn('"enable_body_links"', config_text)
        self.assertIn('"allowed_link_domains"', config_text)
        self.assertIn('"download_link_keywords"', config_text)
        self.assertIn('dengtawaikan@dengtazk.xin', config_text)
        self.assertIn('www.dengtazk.xin', config_text)

    def test_requirements_include_gmail_api_dependencies(self) -> None:
        requirements_path = PROJECT_ROOT / "requirements.txt"
        self.assertTrue(requirements_path.exists(), "requirements.txt should exist at the project root")

        requirements_text = requirements_path.read_text()

        self.assertIn("google-api-python-client", requirements_text)
        self.assertIn("google-auth-oauthlib", requirements_text)
        self.assertIn("google-auth-httplib2", requirements_text)

    def test_dockerfiles_accept_proxy_build_arguments(self) -> None:
        backend_dockerfile_path = PROJECT_ROOT / "Dockerfile"
        frontend_dockerfile_path = PROJECT_ROOT / "frontend" / "Dockerfile"
        self.assertTrue(backend_dockerfile_path.exists(), "Dockerfile should exist at the project root")
        self.assertTrue(frontend_dockerfile_path.exists(), "frontend/Dockerfile should exist")

        backend_text = backend_dockerfile_path.read_text()
        frontend_text = frontend_dockerfile_path.read_text()

        for dockerfile_text in (backend_text, frontend_text):
            self.assertIn("ARG HTTP_PROXY", dockerfile_text)
            self.assertIn("ARG HTTPS_PROXY", dockerfile_text)
            self.assertIn("ARG ALL_PROXY", dockerfile_text)
            self.assertIn("ARG NO_PROXY", dockerfile_text)

    def test_project_includes_compose_file_with_web_worker_article_worker_and_db_services(self) -> None:
        compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text()
        self.assertIn("web:", compose_text)
        self.assertIn("worker:", compose_text)
        self.assertIn("article-worker:", compose_text)
        self.assertIn("db:", compose_text)

    def test_env_example_includes_article_idle_poll_setting(self) -> None:
        env_text = (PROJECT_ROOT / ".env.example").read_text()
        self.assertIn("ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS=", env_text)
        self.assertNotIn("ARTICLE_WORKER_BATCH_SIZE=", env_text)
        self.assertNotIn("PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS=", env_text)
        self.assertNotIn("PROCESSING_IDLE_POLL_INTERVAL_SECONDS=", env_text)

    def test_docker_compose_configuration_is_valid(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist before compose validation")

        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "config"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            f"docker compose config should succeed, stderr was: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
