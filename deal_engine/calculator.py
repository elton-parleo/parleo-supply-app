import logging
from decimal import ROUND_HALF_UP, Decimal
from math import floor
from typing import List

from deal_engine.schemas import AppliedDealResult, TrueCostRequest, TrueCostResponse
from modules.schemas import DealType, RedemptionType

logger = logging.getLogger(__name__)

_TWO_DP = Decimal("0.01")


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(_TWO_DP, rounding=ROUND_HALF_UP))


class TrueCostCalculator:

    def calculate(
        self,
        request: TrueCostRequest,
        engine_results: dict,  # {engine_name: List[AppliedDealResult]}
    ) -> TrueCostResponse:

        # STEP 1 — Flatten all candidate deals from all engines
        all_deals: List[AppliedDealResult] = []
        for results in engine_results.values():
            all_deals.extend(results)

        # STEP 2 — Conflict resolution

        # Rule A — Keep only the highest-saving PROMO_CODE deal
        # (promo_code field no longer exists on AppliedDealResult; identify
        # promo deals by redemption_method instead)
        promo_deals = [
            d for d in all_deals
            if d.redemption_method == RedemptionType.PROMO_CODE
        ]
        if len(promo_deals) > 1:
            best_promo = max(promo_deals, key=lambda d: d.saving_amount)
            for deal in promo_deals:
                if deal is not best_promo:
                    deal.applied = False
                    deal.not_applied_reason = "superseded by higher-value promo"

        # Rule B — Non-stackable vs stackable discount deals
        # MULTIPLIER deals are excluded from this logic (Rule C)
        discount_deals = [
            d for d in all_deals
            if d.applied and d.deal_type in (DealType.DISCOUNT, DealType.FLAT_REWARD)
        ]
        non_stackable = [d for d in discount_deals if not d.is_stackable]
        stackable = [d for d in discount_deals if d.is_stackable]

        if non_stackable and stackable:
            best_non_stackable = max(non_stackable, key=lambda d: d.saving_amount)
            stackable_sum = sum(d.saving_amount for d in stackable)

            if best_non_stackable.saving_amount >= stackable_sum:
                # Non-stackable wins — suppress stackable deals
                for deal in stackable:
                    deal.applied = False
                    deal.not_applied_reason = "conflicts with non-stackable deal"
                # Suppress any other non-stackable deals that lost
                for deal in non_stackable:
                    if deal is not best_non_stackable:
                        deal.applied = False
                        deal.not_applied_reason = "conflicts with non-stackable deal"
            else:
                # Stackable set wins — suppress non-stackable deals
                for deal in non_stackable:
                    deal.applied = False
                    deal.not_applied_reason = "non-stackable deal was lower value than stackable alternatives"

        # Rule C — MULTIPLIER deals are always independent (no action needed;
        # they were never included in conflict checks above)

        # STEP 3 — Compute true_cost
        applied = [d for d in all_deals if d.applied]
        total_discount = sum(
            d.saving_amount for d in applied if d.deal_type != DealType.MULTIPLIER
        )
        product_price = request.product_price
        true_cost = _round2(max(0.0, product_price - total_discount))
        total_savings = _round2(product_price - true_cost)

        # STEP 4 — Compute total_points_earned
        total_points_earned = sum(d.points_earned for d in applied if d.points_earned)
        base_points = floor(true_cost)  # 1 pt per $1 on amount actually paid
        total_points_earned += base_points

        # STEP 5 — Confidence score
        confidence = 1.0
        for engine_name, results in engine_results.items():
            if results == []:
                # Engine ran but returned nothing — may indicate a failure
                confidence *= 0.8
        confidence = _round2(confidence)

        # STEP 6 — Build and return TrueCostResponse
        available_deals = [d for d in all_deals if not d.applied]

        return TrueCostResponse(
            merchant_slug=request.merchant_slug,
            product_price=product_price,
            true_cost=true_cost,
            total_savings=total_savings,
            total_points_earned=total_points_earned,
            applied_deals=applied,
            available_deals=available_deals,
            confidence=confidence,
            user_tier_name=request.user_tier_name,
        )
