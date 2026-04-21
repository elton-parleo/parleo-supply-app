import logging
from math import floor
from typing import List, Optional

from sqlalchemy.orm import Session

from deal_engine.base_engine import BaseEngine
from deal_engine.category_matcher import CategoryMatcher
from deal_engine.loyalty_eligibility import (
    EligibilityContext,  # noqa: F401 — re-exported for convenience
    filter_eligible_deals,
    resolve_memberships,
)
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal
from modules.schemas import DealType

logger = logging.getLogger(__name__)


def _is_points_reward(deal_details: dict) -> bool:
    """True for FLAT_REWARD deals that earn points/stamps/coins/stars."""
    earn_type = deal_details.get("earn_type")
    return earn_type in ("points", "stamps", "coins", "stars")


class LoyaltyPointsEngine(BaseEngine):
    """
    Handles loyalty deals that earn points:
      - deal_type == MULTIPLIER
      - deal_type == FLAT_REWARD where earn_type is points, stamps, coins, or stars

    Runs in Stage 2. By the time this engine runs, request.product_price has
    been set to the preliminary_discounted_price by the orchestrator, so all
    points calculations use the post-discount price directly.
    """

    name = "loyalty_points"

    def __init__(self):
        self.category_matcher = CategoryMatcher()

    def evaluate(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> List[AppliedDealResult]:
        try:
            # STEP 1 — Early exit if no membership signal
            if request.user_tier_name is None:
                return []

            # STEP 2 — Resolve memberships
            if not deals:
                return []
            merchant_id = deals[0].merchant_id
            context = resolve_memberships(request, db, merchant_id)
            if not context.memberships:
                return []

            # STEP 3 — Filter eligible deals
            eligible = filter_eligible_deals(deals, context, request, self.category_matcher)

            # STEP 4 — Further filter to points-earning deals only
            points_eligible = [
                d for d in eligible
                if d.deal_type == DealType.MULTIPLIER
                or (
                    d.deal_type == DealType.FLAT_REWARD
                    and _is_points_reward(d.deal_details or {})
                )
            ]

            # STEP 5 — Compute points_earned for each eligible points deal
            results: List[AppliedDealResult] = []
            for deal in points_eligible:
                try:
                    details = deal.deal_details or {}
                    product_price = request.product_price
                    points_earned: Optional[int] = None
                    saving_amount = 0.0
                    saving_pct = 0.0

                    if deal.deal_type == DealType.MULTIPLIER:
                        spend_min = details.get("spend_min")
                        if spend_min and product_price < spend_min:
                            continue
                        earn_base_value = details.get("earn_base_value", 1)
                        spend_per_increment = details.get("spend_per_increment", 1)
                        earn_multiplier = details.get("earn_multiplier", 1)
                        # TODO (v2): filter base_points to scope_categories only;
                        # for MVP the multiplier is applied to the full product_price.
                        increments = floor(product_price / spend_per_increment)
                        base_points = increments * earn_base_value
                        points_earned = self._apply_earn_cap(
                            floor(base_points * earn_multiplier), details
                        )
                        saving_amount = 0.0
                        saving_pct = 0.0

                    elif deal.deal_type == DealType.FLAT_REWARD:
                        spend_min = details.get("spend_min")
                        if spend_min and product_price < spend_min:
                            continue
                        earn_value = details.get("earn_value", 0)
                        spend_per_increment = details.get("spend_per_increment")
                        if spend_per_increment:
                            # Rate-based: earn earn_value points per spend_per_increment dollars
                            increments = floor(product_price / spend_per_increment)
                            raw_points = floor(increments * earn_value)
                        else:
                            # Flat bonus: earn_value is a fixed point award regardless of spend
                            raw_points = int(earn_value)
                        points_earned = self._apply_earn_cap(raw_points, details)
                        saving_amount = 0.0
                        saving_pct = 0.0

                    else:
                        continue

                    results.append(
                        AppliedDealResult(
                            deal_id=deal.id,
                            deal_title=deal.title,
                            deal_type=deal.deal_type,
                            redemption_method=deal.redemption_method,
                            saving_amount=saving_amount,
                            saving_pct=saving_pct,
                            points_earned=points_earned,
                            is_stackable=deal.is_stackable,
                            applied=True,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "LoyaltyPointsEngine: error processing deal %s: %s", deal.id, exc
                    )

            return results

        except Exception as exc:
            logger.warning("LoyaltyPointsEngine.evaluate failed: %s", exc)
            return []

    def _apply_earn_cap(self, points: int, deal_details: dict) -> int:
        """
        Cap points_earned by earn_cap if present.
        For MVP, only enforce per_transaction cap (most common case).
        All other earn_cap_period values are noted but not enforced
        (cross-transaction tracking is a v2 feature).
        """
        earn_cap = deal_details.get("earn_cap")
        earn_cap_period = deal_details.get("earn_cap_period")

        if earn_cap is None:
            return points

        if earn_cap_period == "per_transaction" or earn_cap_period is None:
            return min(points, int(earn_cap))

        # TODO v2: enforce daily/monthly/annual caps via user transaction history
        # For now return uncapped with a warning log
        logger.debug(
            "earn_cap_period=%r is not enforced at MVP; returning uncapped points=%d",
            earn_cap_period,
            points,
        )
        return points
