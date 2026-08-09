"""Tests for the schedule management API routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_api_app
from src.events.bus import EventBus


class FakeScheduler:
    """In-memory stand-in for JobScheduler."""

    def __init__(self) -> None:
        self.jobs: list = []
        self._next_id = 1

    async def add_job(self, **kwargs):  # type: ignore[no-untyped-def]
        job_id = f"job-{self._next_id}"
        self._next_id += 1
        self.jobs.append({"job_id": job_id, "is_active": 1, **kwargs})
        return job_id

    async def remove_job(self, job_id: str) -> bool:  # type: ignore[no-untyped-def]
        for job in self.jobs:
            if job["job_id"] == job_id:
                job["is_active"] = 0
                return True
        return False

    async def list_jobs(self):  # type: ignore[no-untyped-def]
        return [job for job in self.jobs if job.get("is_active")]


def make_settings(secret: str = "api-secret") -> object:
    """Create a minimal settings object."""
    from unittest.mock import MagicMock

    settings = MagicMock()
    settings.development_mode = True
    settings.webhook_api_secret = secret
    settings.approved_directory = Path("/tmp/approved")
    return settings


@pytest.fixture
def scheduler() -> FakeScheduler:
    return FakeScheduler()


def make_client(secret: str = "api-secret", scheduler: object = None) -> TestClient:
    bus = EventBus()
    settings = make_settings(secret)
    app = create_api_app(bus, settings, scheduler=scheduler)
    return TestClient(app)


def auth_headers(secret: str = "api-secret") -> dict:
    return {"Authorization": f"Bearer {secret}"}


class TestScheduleAPI:
    def test_create_schedule_requires_auth(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)

        response = client.post(
            "/schedules",
            json={"job_name": "x", "cron_expression": "0 9 * * *", "prompt": "hi"},
        )

        assert response.status_code == 401

    def test_create_schedule(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)

        response = client.post(
            "/schedules",
            json={
                "job_name": "daily",
                "cron_expression": "0 9 * * 1-5",
                "prompt": "summary",
                "target_chat_ids": [123, 456],
                "skill_name": "standup",
            },
            headers=auth_headers(),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "created"
        assert data["job_id"].startswith("job-")

    def test_create_schedule_invalid_cron(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)

        response = client.post(
            "/schedules",
            json={"job_name": "x", "cron_expression": "not a cron", "prompt": "hi"},
            headers=auth_headers(),
        )

        assert response.status_code == 400

    def test_create_schedule_rejects_path_outside_approved(
        self, scheduler
    ) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)

        response = client.post(
            "/schedules",
            json={
                "job_name": "x",
                "cron_expression": "0 9 * * *",
                "prompt": "hi",
                "working_directory": "/etc",
            },
            headers=auth_headers(),
        )

        assert response.status_code == 400

    def test_create_schedule_no_secret_configured(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(secret=None, scheduler=scheduler)

        response = client.post(
            "/schedules",
            json={"job_name": "x", "cron_expression": "0 9 * * *", "prompt": "hi"},
            headers={"Authorization": "Bearer whatever"},
        )

        assert response.status_code == 500

    def test_list_schedules(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)
        client.post(
            "/schedules",
            json={"job_name": "daily", "cron_expression": "0 9 * * *", "prompt": "hi"},
            headers=auth_headers(),
        )

        response = client.get("/schedules", headers=auth_headers())

        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["job_name"] == "daily"
        assert jobs[0]["cron_expression"] == "0 9 * * *"

    def test_get_schedule_found_and_missing(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)
        created = client.post(
            "/schedules",
            json={"job_name": "daily", "cron_expression": "0 9 * * *", "prompt": "hi"},
            headers=auth_headers(),
        ).json()

        found = client.get(f"/schedules/{created['job_id']}", headers=auth_headers())
        assert found.status_code == 200
        assert found.json()["job_name"] == "daily"

        missing = client.get("/schedules/nope", headers=auth_headers())
        assert missing.status_code == 404

    def test_delete_schedule(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)
        created = client.post(
            "/schedules",
            json={"job_name": "daily", "cron_expression": "0 9 * * *", "prompt": "hi"},
            headers=auth_headers(),
        ).json()

        response = client.delete(
            f"/schedules/{created['job_id']}", headers=auth_headers()
        )
        assert response.status_code == 204

        jobs = client.get("/schedules", headers=auth_headers()).json()
        assert jobs == []

    def test_delete_missing_schedule_returns_404(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)

        response = client.delete("/schedules/nope", headers=auth_headers())
        assert response.status_code == 404

    def test_routes_not_mounted_without_scheduler(self) -> None:
        """Schedule routes are absent when no scheduler is wired in."""
        client = make_client(scheduler=None)

        response = client.get("/schedules", headers=auth_headers())
        assert response.status_code == 404


class TestScheduleAPIAuth:
    def test_wrong_token_rejected(self, scheduler) -> None:  # type: ignore[no-untyped-def]
        client = make_client(scheduler=scheduler)

        response = client.get(
            "/schedules", headers={"Authorization": "Bearer wrong-secret"}
        )

        assert response.status_code == 401
