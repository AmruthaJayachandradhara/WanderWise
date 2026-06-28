"""Demo user profile — hardcoded for Phase 1.

Replaced by DB-backed lookup in Phase 2+. The user_id FK is threaded
through the graph state from day one so multi-user is purely additive.
"""

from dataclasses import dataclass


@dataclass
class UserProfile:
    user_id: str
    home_airport: str
    passport_country: str
    interests: list[str]
    preferences: dict[str, str]
    budget_default: float = 3000.0  # default trip budget; matches the ~$3000 Japan demo
    home_currency: str = "USD"      # currency the budget is stated in


_DEMO_PROFILE = UserProfile(
    user_id="demo-user",
    home_airport="SFO",
    passport_country="US",
    interests=["food", "history", "nature"],
    preferences={"diet": "vegetarian", "seat": "aisle"},
    budget_default=3000.0,
    home_currency="USD",
)


def get_profile(user_id: str) -> UserProfile:
    """Return the profile for user_id. Phase 1: always returns the demo profile."""
    return _DEMO_PROFILE
