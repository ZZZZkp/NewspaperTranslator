import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.mineru_throttle import MineruSubmissionThrottle


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TokenBucketTests(unittest.TestCase):
    def test_acquire_within_capacity_does_not_sleep(self) -> None:
        clock = _FakeClock()
        throttle = MineruSubmissionThrottle(
            rate_per_min=45,
            pause_seconds=120,
            max_pauses=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        throttle.acquire(30)
        self.assertEqual(clock.sleeps, [])

    def test_acquire_beyond_capacity_sleeps_until_refilled(self) -> None:
        clock = _FakeClock()
        throttle = MineruSubmissionThrottle(
            rate_per_min=60,  # 1 token/second
            pause_seconds=120,
            max_pauses=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        throttle.acquire(60)  # drains the bucket, no sleep
        throttle.acquire(10)  # needs 10 more tokens -> ~10 seconds
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 10.0, places=3)

    def test_acquire_more_than_capacity_still_terminates(self) -> None:
        clock = _FakeClock()
        throttle = MineruSubmissionThrottle(
            rate_per_min=60,  # capacity 60, 1 token/sec
            pause_seconds=120,
            max_pauses=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        throttle.acquire(60)   # drain to empty
        throttle.acquire(100)  # exceeds capacity -> must still return, not loop forever
        # it should have waited at most until the bucket refilled to full (~60s), then proceeded
        self.assertLessEqual(sum(clock.sleeps), 60.0 + 1e-6)

    def test_non_positive_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MineruSubmissionThrottle(
                rate_per_min=0, pause_seconds=120, max_pauses=2,
            )
