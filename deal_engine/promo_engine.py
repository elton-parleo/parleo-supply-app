import logging
from typing import List

from sqlalchemy.orm import Session

from deal_engine.base_engine import BaseEngine
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal
from modules.schemas import DealType, RedemptionType

logger = logging.getLogger(__name__)


def _category_excluded(deal_details: dict, product_category: str | None) -> bool:
    """Return True when the deal is category-restricted and the product doesn't qualify."""
    applicable_categories = deal_details.get("scope_categories", [])
    if not applicable_categories:
        return False  # no restriction — always eligible
    if not product_category:
        return True   # restriction exists but caller supplied no category — exclude
    return product_category.lower() not in [c.lower() for c in applicable_categories]


class PromoEngine(BaseEngine):
    name = "promo"

    def evaluate(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> List[AppliedDealResult]:
        try:
            # STEP 1 — Filter eligible deals
            eligible: List[Deal] = []
            for deal in deals:
                # Only public deals (not membership-gated)
                if deal.program_id is not None or deal.tier_id is not None:
                    continue

                if deal.deal_type not in (DealType.DISCOUNT, DealType.FLAT_REWARD):
                    continue

                if deal.redemption_method not in (RedemptionType.AUTOMATIC, RedemptionType.PROMO_CODE):
                    continue

                details = deal.deal_details or {}

                min_order = details.get("spend_min")
                if min_order is not None and request.product_price < min_order:
                    continue

                if _category_excluded(details, request.product_category):
                    continue

                scope_channels = details.get("scope_channels", [])
                if scope_channels and "online" not in [c.lower() for c in scope_channels]:
                    # TODO v2: accept channel as input on TrueCostRequest
                    continue

                eligible.append(deal)

            # STEP 2 & 3 — Compute savings and build results
            results: List[AppliedDealResult] = []
            for deal in eligible:
                try:
                    details = deal.deal_details or {}
                    product_price = request.product_price

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
                    else:  # FLAT_REWARD — flat dollar discount (discount_amount)
                        # Points earning for FLAT_REWARD deals is handled exclusively by
                        # LoyaltyEngine; PromoEngine always returns points_earned=None.
                        saving_amount = min(float(details.get("discount_amount", 0)), product_price)
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
                    logger.warning("PromoEngine: error processing deal %s: %s", deal.id, exc)

            return results

        except Exception as exc:
            logger.warning("PromoEngine.evaluate failed: %s", exc)
            return []
