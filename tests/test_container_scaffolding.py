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

    def test_project_includes_an_env_example_for_container_runtime(self) -> None:
        env_example_path = PROJECT_ROOT / ".env.example"
        self.assertTrue(env_example_path.exists(), ".env.example should exist at the project root")

        env_text = env_example_path.read_text()

        self.assertIn("APP_ENV=", env_text)
        self.assertIn("DATABASE_URL=", env_text)
        self.assertIn("STORAGE_ROOT=", env_text)
        self.assertIn("GMAIL_CLIENT_ID=", env_text)
        self.assertIn("GMAIL_CLIENT_SECRET=", env_text)
        self.assertIn("GMAIL_REFRESH_TOKEN=", env_text)

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
