import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.tasks import InvalidTaskTransitionError, ProcessingTask
except ImportError:
    InvalidTaskTransitionError = None
    ProcessingTask = None


class ProcessingTaskTests(unittest.TestCase):
    def test_transitions_a_task_from_pending_to_running_to_succeeded(self) -> None:
        self.assertIsNotNone(
            ProcessingTask,
            "ProcessingTask should be importable from newspaper_translator.tasks",
        )

        task = ProcessingTask.create(task_name="import-document")
        running_task = task.transition_to("running")
        succeeded_task = running_task.transition_to("succeeded")

        self.assertEqual(task.status, "pending")
        self.assertEqual(running_task.status, "running")
        self.assertEqual(succeeded_task.status, "succeeded")

    def test_rejects_transition_from_succeeded_back_to_running(self) -> None:
        self.assertIsNotNone(
            ProcessingTask,
            "ProcessingTask should be importable from newspaper_translator.tasks",
        )
        self.assertIsNotNone(
            InvalidTaskTransitionError,
            "InvalidTaskTransitionError should be importable from newspaper_translator.tasks",
        )

        task = ProcessingTask.create(task_name="import-document").transition_to("running").transition_to("succeeded")

        with self.assertRaises(InvalidTaskTransitionError) as context:
            task.transition_to("running")

        self.assertIn("succeeded", str(context.exception))
        self.assertIn("running", str(context.exception))


if __name__ == "__main__":
    unittest.main()
