import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from app.core.dependencies import get_complaints_repository, get_rate_limiter, get_request_id
from app.core.logging import get_logger
from app.providers.cache import RateLimiterProvider
from app.repositories.complaints import ComplaintsRepository
from app.services.triage import TriageService
from app.services.status_machine import VALID_TRANSITIONS, Status


logger = get_logger(__name__)

router = APIRouter()


class ComplaintCreate(BaseModel):
    text: str = Field(..., min_length=10, max_length=2000)
    location: str = Field(..., min_length=3, max_length=200)
    reporter_contact: Optional[str] = Field(None, max_length=200)

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Complaint text cannot be empty")
        return v.strip()

    @field_validator("location")
    @classmethod
    def location_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Location cannot be empty")
        return v.strip()


from datetime import datetime

class ComplaintResponse(BaseModel):
    id: uuid.UUID
    text: str
    location: str
    reporter_contact: Optional[str]
    category: str
    priority: str
    status: str
    ai_summary: Optional[str]
    triaged_by: str
    triage_latency_ms: int
    created_at: datetime
    updated_at: datetime


class ComplaintListResponse(BaseModel):
    items: list[ComplaintResponse]
    total: int
    page: int
    page_size: int


class StatusUpdate(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    detail: str
    field_errors: Optional[dict[str, str]] = None


@router.post(
    "/complaints",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def create_complaint(
    complaint: ComplaintCreate,
    request: Request,
    response: Response,
    repo: ComplaintsRepository = Depends(get_complaints_repository),
    rate_limiter: RateLimiterProvider = Depends(get_rate_limiter),
    request_id: str = Depends(get_request_id),
):
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = await rate_limiter.check_limit(client_ip)

    if not allowed:
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    triage_service = TriageService()
    triage_result = await triage_service.triage(complaint.text, complaint.location)

    created = await repo.create(
        text=complaint.text,
        location=complaint.location,
        reporter_contact=complaint.reporter_contact,
        category=triage_result.category.value,
        priority=triage_result.priority.value,
        ai_summary=triage_result.summary,
        triaged_by=triage_result.triaged_by,
        triage_latency_ms=triage_result.triage_latency_ms,
    )

    return ComplaintResponse(**created)


@router.get("/complaints/{complaint_id}", response_model=ComplaintResponse, responses={404: {"model": ErrorResponse}})
async def get_complaint(
    complaint_id: uuid.UUID,
    repo: ComplaintsRepository = Depends(get_complaints_repository),
):
    complaint = await repo.get_by_id(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return ComplaintResponse(**complaint)


@router.get("/complaints", response_model=ComplaintListResponse)
async def list_complaints(
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: ComplaintsRepository = Depends(get_complaints_repository),
):
    items, total = await repo.list_complaints(
        category=category,
        priority=priority,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ComplaintListResponse(
        items=[ComplaintResponse(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/complaints/{complaint_id}/status", response_model=ComplaintResponse, responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def update_complaint_status(
    complaint_id: uuid.UUID,
    status_update: StatusUpdate,
    repo: ComplaintsRepository = Depends(get_complaints_repository),
):
    current = await repo.get_by_id(complaint_id)
    if not current:
        raise HTTPException(status_code=404, detail="Complaint not found")

    current_status = Status(current["status"])
    new_status = Status(status_update.status)

    if new_status not in VALID_TRANSITIONS.get(current_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid status transition from {current_status.value} to {new_status.value}",
        )

    updated = await repo.update_status(complaint_id, new_status.value)
    return ComplaintResponse(**updated)