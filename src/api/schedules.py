"""REST API for managing scheduled agent jobs.

Lets external agents and tools create, list, inspect, and remove cron
jobs through the same JobScheduler used by the bot. All routes require
the webhook API secret as a Bearer token.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..config.settings import Settings
from ..scheduler.scheduler import JobScheduler
from .auth import verify_shared_secret

logger = structlog.get_logger()


class ScheduleCreate(BaseModel):
    """Payload for creating a scheduled job."""

    job_name: str = Field(..., min_length=1, max_length=200)
    cron_expression: str = Field(..., min_length=1, max_length=100)
    prompt: str = Field(..., min_length=1)
    target_chat_ids: Optional[List[int]] = None
    working_directory: Optional[str] = None
    skill_name: Optional[str] = None
    created_by: int = 0


class ScheduleResponse(BaseModel):
    """A scheduled job as returned to API clients."""

    job_id: str
    job_name: str
    cron_expression: str
    prompt: str
    target_chat_ids: List[int]
    working_directory: str
    skill_name: Optional[str]
    created_by: int = 0
    is_active: bool = True
    created_at: Optional[str] = None


def _parse_chat_ids(raw: Any) -> List[int]:
    """Parse the stored comma-separated chat IDs string into a list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [int(x) for x in raw.split(",") if x.strip()]
    if isinstance(raw, list):
        return [int(x) for x in raw]
    return []


def _to_response(row: Dict[str, Any]) -> ScheduleResponse:
    """Convert a DB row into the API response model."""
    return ScheduleResponse(
        job_id=str(row["job_id"]),
        job_name=row["job_name"],
        cron_expression=row["cron_expression"],
        prompt=row["prompt"],
        target_chat_ids=_parse_chat_ids(row.get("target_chat_ids")),
        working_directory=str(row.get("working_directory") or ""),
        skill_name=row.get("skill_name"),
        created_by=row.get("created_by") or 0,
        is_active=bool(row.get("is_active", True)),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )


def _validate_working_directory(
    working_directory: Optional[str], approved_directory: Path
) -> Path:
    """Resolve a working directory, enforcing the approved-directory boundary."""
    work_dir = (
        Path(working_directory).expanduser().resolve()
        if working_directory
        else approved_directory.resolve()
    )
    approved = approved_directory.resolve()
    try:
        work_dir.relative_to(approved)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="working_directory must be inside the approved directory",
        )
    return work_dir


def _require_auth(authorization: Optional[str], settings: Settings) -> None:
    """Fail-closed on the configured webhook API secret."""
    if not settings.webhook_api_secret:
        raise HTTPException(
            status_code=500,
            detail=(
                "Webhook API secret not configured. "
                "Set WEBHOOK_API_SECRET to use the schedule API."
            ),
        )
    if not verify_shared_secret(authorization, settings.webhook_api_secret):
        raise HTTPException(status_code=401, detail="Invalid authorization")


def create_schedules_router(scheduler: JobScheduler, settings: Settings) -> APIRouter:
    """Create a FastAPI router with schedule management endpoints."""

    router = APIRouter(prefix="/schedules")

    @router.post("", status_code=201)
    async def create_schedule(
        request: ScheduleCreate,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, str]:
        _require_auth(authorization, settings)

        # Validate cron expression up front so clients get a clean 400.
        try:
            CronTrigger.from_crontab(request.cron_expression)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid cron expression: {request.cron_expression}",
            )

        work_dir = _validate_working_directory(
            request.working_directory, settings.approved_directory
        )

        try:
            job_id = await scheduler.add_job(
                job_name=request.job_name,
                cron_expression=request.cron_expression,
                prompt=request.prompt,
                target_chat_ids=request.target_chat_ids,
                working_directory=work_dir,
                skill_name=request.skill_name,
                created_by=request.created_by,
            )
        except Exception:
            logger.exception(
                "Failed to create scheduled job",
                job_name=request.job_name,
                cron=request.cron_expression,
            )
            raise HTTPException(
                status_code=500, detail="Failed to create scheduled job"
            )

        logger.info(
            "Scheduled job created via API",
            job_id=job_id,
            job_name=request.job_name,
        )
        return {"job_id": job_id, "status": "created"}

    @router.get("")
    async def list_schedules(
        authorization: Optional[str] = Header(None),
    ) -> List[ScheduleResponse]:
        _require_auth(authorization, settings)

        rows = await scheduler.list_jobs()
        return [_to_response(row) for row in rows]

    @router.get("/{job_id}")
    async def get_schedule(
        job_id: str,
        authorization: Optional[str] = Header(None),
    ) -> ScheduleResponse:
        _require_auth(authorization, settings)

        for row in await scheduler.list_jobs():
            if str(row["job_id"]) == job_id:
                return _to_response(row)
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    @router.delete("/{job_id}", status_code=204)
    async def delete_schedule(
        job_id: str,
        authorization: Optional[str] = Header(None),
    ) -> None:
        _require_auth(authorization, settings)

        removed = await scheduler.remove_job(job_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        logger.info("Scheduled job removed via API", job_id=job_id)

    return router
