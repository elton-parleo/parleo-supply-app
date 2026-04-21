import logging
from typing import List

from sqlalchemy.orm import Session

from deal_engine.base_engine import BaseEngine
from deal_engine.category_matcher import CategoryMatcher
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal
from modules.schemas import DealType, RedemptionType

logger = logging.getLogger(__name__)


class PromoEngine(BaseEngine):
    name = "promo"

    def __init__(self):
        self.category_matcher = CategoryMatcher()

    def evaluate(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> List[AppliedDealResult]:
        try:
            logger.info("PromoEngine.evaluate called: %d deals, merchant=%s", len(deals), request.merchant_slug)
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

                scope_categories = details.get("scope_categories", [])
                if scope_categories:
                    if not request.product_category:
                        continue
                    if not self.category_matcher.matches(
                        request.product_category, scope_categories
                    ):
                        continue

                # TODO v2: handle brand aliases e.g. "MAC Cosmetics" -> "MAC"
                scope_brands = details.get("scope_brands", [])
                if scope_brands:
                    if not request.brand:
                        continue
                    if request.brand.lower() not in [b.lower() for b in scope_brands]:
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
