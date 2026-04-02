import logging
from math import floor
from typing import Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from deal_engine.base_engine import BaseEngine
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal, MembershipProgram, Merchant, Tier
from modules.schemas import DealType

logger = logging.getLogger(__name__)

# Membership info resolved for a single program
_Membership = Dict  # {"tier": Optional[Tier], "rank": Optional[int]}


def _category_excluded(deal_details: dict, product_category: str | None) -> bool:
    """Return True when the deal is category-restricted and the product doesn't qualify."""
    applicable_categories = deal_details.get("applicable_categories", [])
    if not applicable_categories:
        return False  # no restriction — always eligible
    if not product_category:
        return True   # restriction exists but caller supplied no category — exclude
    return product_category.lower() not in [c.lower() for c in applicable_categories]


class LoyaltyEngine(BaseEngine):
    name = "loyalty"

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
                    if deal_tier_rank is None or membership["rank"] < deal_tier_rank:
                        continue

                if deal.deal_type not in (DealType.MULTIPLIER, DealType.DISCOUNT, DealType.FLAT_REWARD):
                    continue

                details = deal.deal_details or {}
                if _category_excluded(details, request.product_category):
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
                        base_points = floor(product_price)
                        multiplier = details.get("points_multiplier", 1)
                        # TODO (v2): filter base_points to applicable_categories only;
                        # for MVP the multiplier is applied to the full product_price.
                        points_earned = floor(base_points * multiplier)
                        saving_amount = 0.0
                        saving_pct = 0.0

                    elif deal.deal_type == DealType.DISCOUNT:
                        saving_pct = details["percent"] / 100
                        saving_amount = min(product_price * saving_pct, product_price)

                    elif deal.deal_type == DealType.FLAT_REWARD:
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
