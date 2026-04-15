import logging
from math import floor
from typing import Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from deal_engine.base_engine import BaseEngine
from deal_engine.category_matcher import CategoryMatcher
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal, MembershipProgram, Merchant, Tier
from modules.schemas import DealType

logger = logging.getLogger(__name__)

# Membership info resolved for a single program
_Membership = Dict  # {"tier": Optional[Tier], "rank": Optional[int]}


class LoyaltyEngine(BaseEngine):
    name = "loyalty"

    def __init__(self):
        self.category_matcher = CategoryMatcher()

    def evaluate(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> List[AppliedDealResult]:
        try:
            # STEP 1 — No membership signal at all
            if request.user_tier_name is None:
                return []

            # STEP 2 — Resolve user's program memberships for this merchant
            merchant_id = self._resolve_merchant_id(request, deals, db)
            if merchant_id is None:
                return []

            programs: List[MembershipProgram] = (
                db.query(MembershipProgram)
                .options(joinedload(MembershipProgram.tiers))
                .filter(MembershipProgram.merchant_id == merchant_id)
                .all()
            )

            memberships: Dict[int, _Membership] = {}
            for program in programs:
                if program.tiers:
                    matched_tier: Optional[Tier] = next(
                        (t for t in program.tiers if t.name.lower() == request.user_tier_name.lower()),
                        None,
                    )
                    if matched_tier is None:
                        continue  # user is not a member of this program
                    memberships[program.id] = {"tier": matched_tier, "rank": matched_tier.rank}
                else:
                    # Program has no tiers — any user with a tier name is considered a member
                    memberships[program.id] = {"tier": None, "rank": None}

            if not memberships:
                return []

            # STEP 3 — Filter eligible loyalty deals
            eligible: List[Deal] = []
            for deal in deals:
                if deal.program_id is None:
                    continue

                if deal.program_id not in memberships:
                    continue

                membership = memberships[deal.program_id]

                if deal.tier_id is None:
                    # Program-wide deal — all members qualify
                    pass
                else:
                    # Tier-specific deal — check rank
                    if membership["rank"] is None:
                        # Program has no tiers, so tier-specific deals don't apply
                        continue
                    deal_tier_rank = deal.tier.rank if deal.tier else None
                    if deal_tier_rank is None or membership["rank"] != deal_tier_rank:
                        continue

                if deal.deal_type not in (DealType.MULTIPLIER, DealType.DISCOUNT, DealType.FLAT_REWARD):
                    continue

                details = deal.deal_details or {}
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

            # STEP 4 & 5 — Compute savings/points and build results
            results: List[AppliedDealResult] = []
            for deal in eligible:
                try:
                    details = deal.deal_details or {}
                    product_price = request.product_price
                    saving_amount = 0.0
                    saving_pct = 0.0
                    points_earned: Optional[int] = None

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

                    elif deal.deal_type == DealType.DISCOUNT:
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
                        earn_type = details.get("earn_type")
                        if earn_type in ("points", "stamps", "coins", "stars"):
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
                        else:  # fixed_currency, percent_back, or earn_type absent — cash/discount
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
                            points_earned=points_earned,
                            is_stackable=deal.is_stackable,
                            applied=True,
                        )
                    )
                except Exception as exc:
                    logger.warning("LoyaltyEngine: error processing deal %s: %s", deal.id, exc)

            return results

        except Exception as exc:
            logger.warning("LoyaltyEngine.evaluate failed: %s", exc)
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

    def _resolve_merchant_id(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> Optional[int]:
        """Return the merchant_id for this request, preferring the pre-loaded deals list."""
        if deals:
            return deals[0].merchant_id
        merchant = db.query(Merchant).filter(Merchant.slug == request.merchant_slug).first()
        return merchant.id if merchant else None
