"""Centralized DECIDAI plan definitions. Payment providers are intentionally excluded."""
import os
from typing import Final


PLAN_LIMITS: Final[dict[str, dict[str, int | None]]] = {
    "FREE": {"cases_created": 10, "ai_analyses": 10, "team_members": 2, "invitations_sent": 5},
    "PRO": {"cases_created": 100, "ai_analyses": 100, "team_members": 10, "invitations_sent": 30},
    "BUSINESS": {"cases_created": None, "ai_analyses": None, "team_members": 50, "invitations_sent": None},
}


def normalized_plan(plan: str | None) -> str:
    value = (plan or "FREE").upper()
    return value if value in PLAN_LIMITS else "FREE"


def limits_for(plan: str | None) -> dict[str, int | None]:
    return dict(PLAN_LIMITS[normalized_plan(plan)])


def billing_enforcement_enabled() -> bool:
    """Feature flag for future paid-plan enforcement; disabled until billing launches."""
    return os.getenv("BILLING_ENFORCEMENT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
