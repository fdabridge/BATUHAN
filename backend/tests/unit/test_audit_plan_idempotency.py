"""Regression coverage for safe audit-plan submission retries."""

import sys
import types
from unittest.mock import patch

# The production image installs redis-py. Keep this small unit test runnable in
# lightweight local environments that intentionally omit service clients.
try:
    import redis  # noqa: F401
except ModuleNotFoundError:
    redis_stub = types.ModuleType("redis")
    redis_stub.Redis = object
    redis_stub.from_url = lambda *args, **kwargs: None
    sys.modules["redis"] = redis_stub

from storage.file_store import (
    claim_job_execution,
    idempotent_job_id,
    save_text_artifact_if_absent,
)


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, object] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def expire(self, key, ttl):
        return key in self.values


def test_idempotent_job_id_is_stable_and_user_scoped():
    first = idempotent_job_id("audit-plan", "user-a", "request-1")
    assert first == idempotent_job_id("audit-plan", "user-a", "request-1")
    assert first != idempotent_job_id("audit-plan", "user-b", "request-1")
    assert first != idempotent_job_id("audit-plan", "user-a", "request-2")


def test_status_claim_is_created_only_once():
    redis = _FakeRedis()
    with patch("storage.file_store._redis", return_value=redis):
        assert save_text_artifact_if_absent("job-1", "status.json", "queued") is True
        assert save_text_artifact_if_absent("job-1", "status.json", "duplicate") is False

    assert redis.values["batuhan:job:job-1:text:status.json"] == b"queued"


def test_worker_execution_claim_blocks_duplicate_delivery():
    redis = _FakeRedis()
    with patch("storage.file_store._redis", return_value=redis):
        assert claim_job_execution("job-1") is True
        assert claim_job_execution("job-1") is False
