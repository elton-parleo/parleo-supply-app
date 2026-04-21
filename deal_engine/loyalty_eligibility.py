import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from deal_engine.category_matcher import CategoryMatcher
from deal_engine.schemas import TrueCostRequest
from modules.models import Deal, MembershipProgram, Tier
from modules.schemas import DealType

logger = logging.getLogger(__name__)


@dataclass
class MembershipInfo:
    program_id: int
    tier: Optional[Tier]      # None if program has no tiers
    tier_rank: Optional[int]  # None if program has no tiers


@dataclass
class EligibilityContext:
    memberships: Dict[int, MembershipInfo]
    # keyed by program_id; empty dict means user has no qualifying memberships


def resolve_memberships(
    request: TrueCostRequest,
    db: Session,
    merchant_id: int,
) -> EligibilityContext:
    """
    Resolve which loyalty programs the user is a member of,
    and their tier within each program.

    Returns EligibilityContext with memberships dict.
    Returns empty EligibilityContext if:
      - request.user_tier_name is None
      - user_tier_name doesn't match any tier in any program
    """
    programs: List[MembershipProgram] = (
        db.query(MembershipProgram)
        .options(joinedload(MembershipProgram.tiers))
        .filter(MembershipProgram.merchant_id == merchant_id)
        .all()
    )

    memberships: Dict[int, MembershipInfo] = {}
    for program in programs:
        if program.tiers:
            matched_tier: Optional[Tier] = next(
                (t for t in program.tiers if t.name.lower() == request.user_tier_name.lower()),
                None,
            )
            if matched_tier is None:
                continue  # user is not a member of this program
            memberships[program.id] = MembershipInfo(
                program_id=program.id,
                tier=matched_tier,
                tier_rank=matched_tier.rank,
            )
        else:
            # Program has no tiers — any user with a tier name is considered a member
            memberships[program.id] = MembershipInfo(
                program_id=program.id,
                tier=None,
                tier_rank=None,
            )

    return EligibilityContext(memberships=memberships)


def filter_eligible_deals(
    deals: List[Deal],
    context: EligibilityContext,
    request: TrueCostRequest,
    category_matcher: CategoryMatcher,
) -> List[Deal]:
    """
    Filter active deals to those the user is eligible for based on:
      - Program membership
      - Tier rank (exact match — tier deals are exclusive)
      - scope_categories (via CategoryMatcher)
      - scope_brands (exact case-insensitive match)
      - scope_channels (online assumed)

    Returns list of eligible Deal objects.
    Only includes deals where deal.program_id is not None.
    spend_min checks are NOT applied here — they belong in per-deal computation.
    """
    eligible: List[Deal] = []
    for deal in deals:
        if deal.program_id is None:
            continue

        if deal.program_id not in context.memberships:
            continue

        membership = context.memberships[deal.program_id]

        if deal.tier_id is None:
            # Program-wide deal — all members qualify
            pass
        else:
            # Tier-specific deal — check rank
            if membership.tier_rank is None:
                # Program has no tiers, so tier-specific deals don't apply
                continue
            deal_tier_rank = deal.tier.rank if deal.tier else None
            if deal_tier_rank is None or membership.tier_rank != deal_tier_rank:
                continue

        if deal.deal_type not in (DealType.MULTIPLIER, DealType.DISCOUNT, DealType.FLAT_REWARD):
            continue

        details = deal.deal_details or {}
        scope_categories = details.get("scope_categories", [])
        if scope_categories:
            if not request.product_category:
                continue
            if not category_matcher.matches(request.product_category, scope_categories):
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

    return eligible
