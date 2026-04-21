import logging
from typing import List

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


def _is_currency_reward(deal_details: dict) -> bool:
    """True for FLAT_REWARD deals that reduce price (not earn points)."""
    earn_type = deal_details.get("earn_type")
    # No earn_type = assumed to be a flat dollar discount
    if earn_type is None:
        return True
    return earn_type in ("fixed_currency", "percent_back")


class LoyaltyDiscountEngine(BaseEngine):
    """
    Handles loyalty deals that reduce price:
      - deal_type == DISCOUNT
      - deal_type == FLAT_REWARD where earn_type is fixed_currency,
        percent_back, or earn_type is absent

    Runs in Stage 1 so that member discounts are reflected in the
    preliminary_discounted_price passed to the points engine.
    """

    name = "loyalty_discount"

    def __init__(self):
        self.category_matcher = CategoryMatcher()

    def evaluate(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> List[AppliedDealResult]:
        try:
            logger.info("LoyaltyDiscountEngine.evaluate called: %d deals, merchant=%s", len(deals), request.merchant_slug)
            
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

            # STEP 4 — Further filter to discount-type deals only
            discount_eligible = [
                d for d in eligible
                if d.deal_type == DealType.DISCOUNT
                or (
                    d.deal_type == DealType.FLAT_REWARD
                    and _is_currency_reward(d.deal_details or {})
                )
            ]

            # STEP 5 — Compute saving_amount for each eligible discount deal
            results: List[AppliedDealResult] = []
            for deal in discount_eligible:
                try:
                    details = deal.deal_details or {}
                    product_price = request.product_price
                    saving_amount = 0.0
                    saving_pct = 0.0

                    if deal.deal_type == DealType.DISCOUNT:
                        discount_type = details.get("discount_type")
                        discount_percent = details.get("discount_percent", 0)
                        discount_amount = details.get("discount_amount", 0)
                        discount_amount_max = details.get("discount_amount_max")

                        if discount_type == "amount_off" or (
                            discount_amount > 0 and discount_percent == 0
                        ):
                            saving_amount = float(discount_amount)
                            saving_pct = saving_amount / product_price if product_price else 0.0
                        else:  # percent_off (default)
                            saving_amount = product_price * discount_percent / 100
                            saving_pct = discount_percent / 100

                        if discount_amount_max is not None:
                            saving_amount = min(saving_amount, float(discount_amount_max))
                            saving_pct = saving_amount / product_price if product_price else 0.0

                        saving_amount = min(saving_amount, product_price)

                    elif deal.deal_type == DealType.FLAT_REWARD:
                        spend_min = details.get("spend_min")
                        if spend_min and product_price < spend_min:
                            continue
                        # fixed_currency, percent_back, or earn_type absent — cash/discount
                        saving_amount = min(
                            float(details.get("discount_amount", 0)), product_price
                        )
                        saving_pct = saving_amount / product_price if product_price else 0.0

                    results.append(
                        AppliedDealResult(
                            deal_id=deal.id,
                            deal_title=deal.title,
                            deal_type=deal.deal_type,
                            redemption_method=deal.redemption_method,
                            saving_amount=saving_amount,
                            saving_pct=saving_pct,
                            points_earned=None,
                            is_stackable=deal.is_stackable,
                            applied=True,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "LoyaltyDiscountEngine: error processing deal %s: %s", deal.id, exc
                    )

            return results

        except Exception as exc:
            logger.warning("LoyaltyDiscountEngine.evaluate failed: %s", exc)
            return []
