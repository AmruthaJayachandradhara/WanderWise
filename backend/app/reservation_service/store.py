"""In-memory reservation store.

Thread-safe container for reservations, the idempotency-key index, and the
taken-slot index. Deliberately simple — the point is correct semantics
(see semantics.py), not scale. Swappable for SQLite later without touching
the service endpoints.
"""

import threading


class ReservationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reservations: dict[str, dict] = {}
        self._by_idempotency_key: dict[str, str] = {}      # key → reservation_id
        self._taken_slots: dict[tuple[str, str], str] = {}  # (venue_id, slot) → reservation_id

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    # All accessors assume the caller holds `lock` (semantics.py does).

    def get(self, reservation_id: str) -> dict | None:
        return self._reservations.get(reservation_id)

    def get_by_idempotency_key(self, key: str) -> dict | None:
        reservation_id = self._by_idempotency_key.get(key)
        return self._reservations.get(reservation_id) if reservation_id else None

    def slot_holder(self, venue_id: str, slot: str) -> str | None:
        return self._taken_slots.get((venue_id, slot))

    def add(self, reservation: dict, idempotency_key: str) -> None:
        rid = reservation["reservation_id"]
        self._reservations[rid] = reservation
        self._by_idempotency_key[idempotency_key] = rid
        self._taken_slots[(reservation["venue_id"], reservation["slot"])] = rid

    def release_slot(self, venue_id: str, slot: str) -> None:
        self._taken_slots.pop((venue_id, slot), None)

    def reset(self) -> None:
        """Clear all state — used by tests."""
        with self._lock:
            self._reservations.clear()
            self._by_idempotency_key.clear()
            self._taken_slots.clear()
