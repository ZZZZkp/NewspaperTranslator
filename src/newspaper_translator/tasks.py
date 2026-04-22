from dataclasses import dataclass


class InvalidTaskTransitionError(ValueError):
    """Raised when a task status transition is not allowed."""


@dataclass(frozen=True)
class ProcessingTask:
    task_name: str
    status: str

    @classmethod
    def create(cls, *, task_name: str) -> "ProcessingTask":
        return cls(task_name=task_name, status="pending")

    def transition_to(self, status: str) -> "ProcessingTask":
        allowed_transitions = {
            "pending": {"running"},
            "running": {"succeeded"},
            "succeeded": set(),
        }
        if status not in allowed_transitions.get(self.status, set()):
            raise InvalidTaskTransitionError(
                f"Cannot transition task from {self.status} to {status}"
            )
        return ProcessingTask(task_name=self.task_name, status=status)
