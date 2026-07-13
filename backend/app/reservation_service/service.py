"""Mock reservation microservice — a partner-API stand-in with real semantics.

Self-contained FastAPI app. Runs three ways, same code:
  - mounted at /reservation inside the main WanderWise app (HF Spaces prod),
  - standalone via docker-compose (`uvicorn backend.app.reservation_service.service:app`),
  - in-process through httpx ASGITransport (the default mock_provider path).

Endpoints implement the semantics a real booking partner exposes:
idempotent reserve, availability conflict (409), confirm → confirmation ID,
cancel/rollback.
"""

import logging

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from backend.app.reservation_service import semantics
from backend.app.reservation_service.store import ReservationStore

logger = logging.getLogger(__name__)

app = FastAPI(
    title="WanderWise Reservation Service",
    version="0.1.0",
    description="Mock booking partner: idempotent reserve / confirm / cancel.",
)

# Module-level store — single instance per process, reset()-able in tests.
store = ReservationStore()


class ReserveRequest(BaseModel):
    venue_id: str
    slot: str                      # ISO datetime string, e.g. "2026-08-01T19:00"
    party_size: int = Field(default=2, ge=1)
    venue_name: str = ""


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/reservations", status_code=201)
def create_reservation(
    body: ReserveRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    try:
        reservation, created = semantics.reserve(
            store,
            venue_id=body.venue_id,
            slot=body.slot,
            party_size=body.party_size,
            idempotency_key=idempotency_key,
            venue_name=body.venue_name,
        )
    except semantics.SlotConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        response.status_code = 200  # idempotent replay, not a new resource
    return reservation


@app.get("/reservations/{reservation_id}")
def get_reservation(reservation_id: str) -> dict:
    with store.lock:
        reservation = store.get(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail=f"{reservation_id} not found")
    return reservation


@app.post("/reservations/{reservation_id}/confirm")
def confirm_reservation(reservation_id: str) -> dict:
    try:
        return semantics.confirm(store, reservation_id)
    except semantics.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"{exc} not found") from exc
    except semantics.InvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/reservations/{reservation_id}")
def cancel_reservation(reservation_id: str) -> dict:
    try:
        return semantics.cancel(store, reservation_id)
    except semantics.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"{exc} not found") from exc


@app.get("/availability")
def availability(venue_id: str, slot: str) -> dict:
    return {
        "venue_id": venue_id,
        "slot": slot,
        "available": semantics.is_slot_available(store, venue_id, slot),
    }
