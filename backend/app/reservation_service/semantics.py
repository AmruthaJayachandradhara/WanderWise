"""Reservation semantics — the behaviors that make the mock credible.

Idempotency: a retried reserve with the same Idempotency-Key returns the
same reservation, never a double-booking. Conflicts: a slot held by another
live reservation is rejected. Cancellation: rolls back and frees the slot.
Confirmation: only a confirm call mints a confirmation ID — the same
contract a real partner API (OpenTable, Duffel) exposes.
"""

import logging
import uuid

from backend.app.reservation_service.store import ReservationStore

logger = logging.getLogger(__name__)

RESERVED = "reserved"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"


class SlotConflictError(Exception):
    """The requested (venue, slot) is already held by another reservation."""


class NotFoundError(Exception):
    """No reservation with that ID."""


class InvalidStateError(Exception):
    """The reservation is in a state that does not allow this transition."""


def reserve(
    store: ReservationStore,
    *,
    venue_id: str,
    slot: str,
    party_size: int,
    idempotency_key: str,
    venue_name: str = "",
) -> tuple[dict, bool]:
    """Create a reservation. Returns (reservation, created).

    created=False means the idempotency key was already used and the
    existing reservation is returned unchanged.
    """
    with store.lock:
        existing = store.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            logger.info(
                "Idempotent replay for key %s → %s",
                idempotency_key,
                existing["reservation_id"],
            )
            return existing, False

        holder = store.slot_holder(venue_id, slot)
        if holder is not None:
            raise SlotConflictError(
                f"Slot {slot!r} at venue {venue_id!r} is already reserved"
            )

        reservation = {
            "reservation_id": f"res_{uuid.uuid4().hex[:12]}",
            "venue_id": venue_id,
            "venue_name": venue_name,
            "slot": slot,
            "party_size": party_size,
            "status": RESERVED,
            "confirmation_id": None,
        }
        store.add(reservation, idempotency_key)
        logger.info(
            "Reserved %s: venue=%s slot=%s party=%d",
            reservation["reservation_id"],
            venue_id,
            slot,
            party_size,
        )
        return reservation, True


def confirm(store: ReservationStore, reservation_id: str) -> dict:
    """Confirm a reservation — mints the confirmation ID (idempotent)."""
    with store.lock:
        reservation = store.get(reservation_id)
        if reservation is None:
            raise NotFoundError(reservation_id)
        if reservation["status"] == CANCELLED:
            raise InvalidStateError(f"{reservation_id} is cancelled")
        if reservation["status"] != CONFIRMED:
            reservation["status"] = CONFIRMED
            reservation["confirmation_id"] = f"WW-{uuid.uuid4().hex[:8].upper()}"
            logger.info(
                "Confirmed %s → %s", reservation_id, reservation["confirmation_id"]
            )
        return reservation


def cancel(store: ReservationStore, reservation_id: str) -> dict:
    """Cancel a reservation and free its slot (idempotent)."""
    with store.lock:
        reservation = store.get(reservation_id)
        if reservation is None:
            raise NotFoundError(reservation_id)
        if reservation["status"] != CANCELLED:
            reservation["status"] = CANCELLED
            store.release_slot(reservation["venue_id"], reservation["slot"])
            logger.info("Cancelled %s, slot freed", reservation_id)
        return reservation


def is_slot_available(store: ReservationStore, venue_id: str, slot: str) -> bool:
    with store.lock:
        return store.slot_holder(venue_id, slot) is None
