"""Provider-neutral internal billing operations. Webhook adapters may call this later."""
from datetime import datetime

from services.database_service import apply_organization_subscription_change


def apply_successful_subscription(organization_id: str, plan: str, provider: str,
                                  provider_customer_id: str | None = None,
                                  provider_subscription_id: str | None = None,
                                  current_period_start: datetime | None = None,
                                  current_period_end: datetime | None = None,
                                  cancel_at_period_end: bool = False) -> dict:
    """Trusted internal entry point; it is intentionally not exposed as an API route."""
    return apply_organization_subscription_change(
        organization_id=organization_id,
        plan=plan,
        billing_status="active",
        provider=provider,
        provider_customer_id=provider_customer_id,
        provider_subscription_id=provider_subscription_id,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )
