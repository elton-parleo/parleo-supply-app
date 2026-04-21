"""
Deal engine test suite.

Engine tests (1-7)      — call PromoEngine / LoyaltyDiscountEngine / LoyaltyPointsEngine directly.
Calculator tests (8-10) — call TrueCostCalculator.calculate() with hand-crafted fixtures.
Integration test (11)   — POST /api/deals/true-cost via TestClient.
Category tests (12-14)  — validate scope_categories filtering in both engines.
"""

import pytest
from unittest.mock import patch

from deal_engine.promo_engine import PromoEngine
from deal_engine.loyalty_discount_engine import LoyaltyDiscountEngine
from deal_engine.loyalty_points_engine import LoyaltyPointsEngine
from deal_engine.loyalty_eligibility import (
    EligibilityContext,
    MembershipInfo,
    filter_eligible_deals,
    resolve_memberships,
)
from deal_engine.calculator import TrueCostCalculator
from deal_engine.schemas import TrueCostRequest, AppliedDealResult
from modules.schemas import DealType, RedemptionType
from modules.models import Deal


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_category_matcher():
    """Replace CategoryMatcher.matches with an exact-string fallback for all tests.

    This keeps all existing tests working without a live OpenAI API key.
    The fallback mirrors the original _category_excluded logic:
    return True iff product_category (case-insensitive) is in scope_categories.
    """
    def _exact_match(self, product_category: str, scope_categories: list) -> bool:
        return product_category.lower() in [c.lower() for c in scope_categories]

    with patch(
        "deal_engine.category_matcher.CategoryMatcher.matches",
        new=_exact_match,
    ):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_deal(
    deal_id: int,
    title: str,
    deal_type: DealType,
    saving_amount: float,
    is_stackable: bool,
    points_earned: int | None = None,
    redemption_method: RedemptionType = RedemptionType.AUTOMATIC,
) -> AppliedDealResult:
    """Build an AppliedDealResult for calculator unit tests (no DB required)."""
    saving_pct = saving_amount / 100.0
    return AppliedDealResult(
        deal_id=deal_id,
        deal_title=title,
        deal_type=deal_type,
        redemption_method=redemption_method,
        saving_amount=saving_amount,
        saving_pct=saving_pct,
        points_earned=points_earned,
        is_stackable=is_stackable,
        applied=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Promo engine: automatic discount applied
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_automatic_discount(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(merchant_slug="test-merchant", product_price=100.0)

    results = engine.evaluate(request, [seeded["deal1"]], db)

    assert len(results) == 1
    r = results[0]
    assert r.deal_id == seeded["deal1"].id
    assert r.saving_amount == 10.0
    assert r.applied is True


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Promo engine: PROMO_CODE deal returned without a code in the request
# (engine now returns all eligible promo deals; caller supplies no code)
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_code_deal_returned_automatically(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(merchant_slug="test-merchant", product_price=80.0)

    results = engine.evaluate(request, [seeded["deal2"]], db)

    assert len(results) == 1
    assert results[0].saving_amount == 15.0
    assert results[0].applied is True


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Promo engine: minimum order value not met
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_min_order_not_met(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(merchant_slug="test-merchant", product_price=40.0)

    results = engine.evaluate(request, [seeded["deal2"]], db)

    assert results == [], "Deal with spend_min=50 must be excluded when product_price=40"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Category filter: deals with scope_categories skipped when
#           no product_category is provided in the request
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_category_required_but_absent(seeded, db):
    points_engine = LoyaltyPointsEngine()   # deal3 is MULTIPLIER
    discount_engine = LoyaltyDiscountEngine()  # deal4 is DISCOUNT
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category=None,
    )

    points_results = points_engine.evaluate(request, [seeded["deal3"]], db)
    discount_results = discount_engine.evaluate(request, [seeded["deal4"]], db)

    assert seeded["deal3"].id not in {r.deal_id for r in points_results}, (
        "3x multiplier (scope_categories=['skincare']) must be skipped "
        "when product_category is None"
    )
    assert seeded["deal4"].id not in {r.deal_id for r in discount_results}, (
        "20% Gold discount (scope_categories=['skincare']) must be skipped "
        "when product_category is None"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Loyalty engine: no tier signal returns empty
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_no_tier(seeded, db):
    points_engine = LoyaltyPointsEngine()
    discount_engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant", product_price=100.0, user_tier_name=None
    )

    assert points_engine.evaluate(request, [seeded["deal3"]], db) == [], (
        "No user_tier_name must return empty from LoyaltyPointsEngine"
    )
    assert discount_engine.evaluate(request, [seeded["deal4"]], db) == [], (
        "No user_tier_name must return empty from LoyaltyDiscountEngine"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Loyalty engine: Bronze tier gets no Gold deals
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_bronze_excluded_from_gold(seeded, db):
    points_engine = LoyaltyPointsEngine()   # deal3 is MULTIPLIER
    discount_engine = LoyaltyDiscountEngine()  # deal4 is DISCOUNT
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
        product_category="skincare",
    )

    points_results = points_engine.evaluate(request, [seeded["deal3"]], db)
    discount_results = discount_engine.evaluate(request, [seeded["deal4"]], db)

    assert seeded["deal3"].id not in {r.deal_id for r in points_results}, (
        "Bronze (rank=1) must not receive Gold MULTIPLIER deal (rank=3)"
    )
    assert seeded["deal4"].id not in {r.deal_id for r in discount_results}, (
        "Bronze (rank=1) must not receive Gold DISCOUNT deal (rank=3)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — Loyalty engine: Gold tier gets only Gold-tier deals (not Silver/Bronze)
#           deal3 seed includes earn_base_value=1, spend_per_increment=1, so
#           points_earned = floor(100/1) * 1 * 3 = 300 (same as the original naive formula).
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_gold_gets_only_gold_tier_deals(seeded, db):
    # deal3: Gold MULTIPLIER → LoyaltyPointsEngine
    # deal4: Gold DISCOUNT → LoyaltyDiscountEngine
    # deal5: Silver DISCOUNT → LoyaltyDiscountEngine (must NOT be returned)
    points_engine = LoyaltyPointsEngine()
    discount_engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand="NARS",  # deal3 requires scope_brands=["NARS", "Charlotte Tilbury"]
    )

    points_results = points_engine.evaluate(request, [seeded["deal3"]], db)
    discount_results = discount_engine.evaluate(request, [seeded["deal4"], seeded["deal5"]], db)

    points_result_ids = {r.deal_id for r in points_results}
    discount_result_ids = {r.deal_id for r in discount_results}

    assert seeded["deal3"].id in points_result_ids, (
        "Gold multiplier deal must be returned for Gold member"
    )
    assert seeded["deal4"].id in discount_result_ids, (
        "Gold discount deal must be returned for Gold member"
    )
    assert seeded["deal5"].id not in discount_result_ids, (
        "Silver-tier deal (rank=2) must NOT be returned for Gold member (rank=3)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — Calculator: non-stackable deal wins when higher than stackable sum
# ─────────────────────────────────────────────────────────────────────────────

def test_calculator_nonstackable_wins():
    calc = TrueCostCalculator()
    request = TrueCostRequest(merchant_slug="test", product_price=100.0)

    deal_10pct = _make_deal(
        1, "10% off", DealType.DISCOUNT, saving_amount=10.0, is_stackable=True
    )
    deal_15flat = _make_deal(
        2, "$15 off", DealType.FLAT_REWARD, saving_amount=15.0, is_stackable=False,
        redemption_method=RedemptionType.PROMO_CODE,
    )

    response = calc.calculate(request, {"promo": [deal_10pct, deal_15flat]})

    applied_ids = {d.deal_id for d in response.applied_deals}
    not_applied_ids = {d.deal_id for d in response.available_deals}

    assert 2 in applied_ids, "Non-stackable $15 deal should be applied"
    assert 1 in not_applied_ids, "Stackable 10% deal should be suppressed"
    assert response.true_cost == 85.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9 — Calculator: stackable set wins when sum exceeds non-stackable
# ─────────────────────────────────────────────────────────────────────────────

def test_calculator_stackable_wins():
    calc = TrueCostCalculator()
    request = TrueCostRequest(merchant_slug="test", product_price=100.0)

    deal_10pct = _make_deal(
        1, "10% off", DealType.DISCOUNT, saving_amount=10.0, is_stackable=True
    )
    deal_8flat = _make_deal(
        2, "$8 off", DealType.FLAT_REWARD, saving_amount=8.0, is_stackable=False,
        redemption_method=RedemptionType.PROMO_CODE,
    )

    response = calc.calculate(request, {"promo": [deal_10pct, deal_8flat]})

    applied_ids = {d.deal_id for d in response.applied_deals}
    not_applied_ids = {d.deal_id for d in response.available_deals}

    assert 1 in applied_ids, "Stackable 10% deal should be applied (sum 10 > non-stackable 8)"
    assert 2 in not_applied_ids, "Non-stackable $8 deal should be suppressed"
    assert response.true_cost == 90.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10 — Calculator: multiplier deal is never blocked by conflict rules
# ─────────────────────────────────────────────────────────────────────────────

def test_calculator_multiplier_not_blocked():
    """
    MULTIPLIER deals pass through conflict resolution unblocked regardless of any
    earn_cap or spend_per_increment — those are resolved upstream in the engine and
    arrive here as a pre-computed points_earned value. The calculator only checks
    deal_type, not deal_details, so this behaviour is unchanged by the engine updates.
    """
    calc = TrueCostCalculator()
    request = TrueCostRequest(merchant_slug="test", product_price=100.0)

    deal_promo = _make_deal(
        1, "$15 promo", DealType.FLAT_REWARD, saving_amount=15.0, is_stackable=False,
        redemption_method=RedemptionType.PROMO_CODE,
    )
    deal_multiplier = _make_deal(
        2, "3x points", DealType.MULTIPLIER, saving_amount=0.0, is_stackable=True,
        points_earned=300,
    )

    response = calc.calculate(
        request, {"promo": [deal_promo], "loyalty": [deal_multiplier]}
    )

    applied_ids = {d.deal_id for d in response.applied_deals}
    assert 1 in applied_ids, "Non-stackable promo must be applied"
    assert 2 in applied_ids, "Multiplier must not be blocked by non-stackable conflict rule"
    assert response.total_points_earned > 0
    assert response.true_cost == 85.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11 — Full endpoint integration test
# ─────────────────────────────────────────────────────────────────────────────

def test_true_cost_endpoint(client):
    """
    Gold tier, skincare product, $100 price.
    Verifies savings are applied and the Gold multiplier awards points.
    Exact values depend on the full seeded deal set (see conftest.py db fixture).
    """
    payload = {
        "merchant_slug": "test-merchant",
        "product_price": 100.0,
        "user_tier_name": "Gold",
        "product_category": "skincare",
    }

    response = client.post("/api/deals/true-cost", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["true_cost"] < 100.0, "Some savings must be applied"
    assert data["total_points_earned"] > 0, "Gold multiplier must award points"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12 — Category filter: matching category returns category-gated deals
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_matching_category_returns_deals(seeded, db):
    points_engine = LoyaltyPointsEngine()   # deal3 is MULTIPLIER
    discount_engine = LoyaltyDiscountEngine()  # deal4 is DISCOUNT
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand="NARS",  # deal3 requires scope_brands=["NARS", "Charlotte Tilbury"]
    )

    points_results = points_engine.evaluate(request, [seeded["deal3"]], db)
    discount_results = discount_engine.evaluate(request, [seeded["deal4"]], db)

    assert seeded["deal3"].id in {r.deal_id for r in points_results}, (
        "3x multiplier must be returned when product_category matches 'skincare' and brand matches"
    )
    assert seeded["deal4"].id in {r.deal_id for r in discount_results}, (
        "20% Gold discount must be returned when product_category matches 'skincare'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13 — Category filter: non-matching category excludes category-gated deals
#            but leaves category-agnostic deals untouched
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_nonmatching_category_excludes_deals(seeded, db):
    points_engine = LoyaltyPointsEngine()   # deal3 is MULTIPLIER
    discount_engine = LoyaltyDiscountEngine()  # deal4 is DISCOUNT
    promo_engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="lipstick",
    )

    points_results = points_engine.evaluate(request, [seeded["deal3"]], db)
    discount_results = discount_engine.evaluate(request, [seeded["deal4"]], db)
    promo_results = promo_engine.evaluate(request, [seeded["deal1"]], db)

    assert seeded["deal3"].id not in {r.deal_id for r in points_results}, (
        "3x multiplier (scope_categories=['skincare']) must be excluded for 'lipstick' product"
    )
    assert seeded["deal4"].id not in {r.deal_id for r in discount_results}, (
        "20% Gold discount (scope_categories=['skincare']) must be excluded for 'lipstick' product"
    )

    # deal1 has no scope_categories — it must survive any product_category value
    assert seeded["deal1"].id in {r.deal_id for r in promo_results}, (
        "Category-agnostic 10% deal must still be returned for any product_category"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 14 — Category filter: deal with no applicable_categories applies to all
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_no_category_restriction_applies_to_all(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        product_category="lipstick",
    )

    results = engine.evaluate(request, [seeded["deal1"]], db)

    assert len(results) == 1, (
        "Deal with no scope_categories must be returned regardless of product_category"
    )
    assert results[0].deal_id == seeded["deal1"].id


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15 — Loyalty engine: Silver tier gets only Silver-tier deals
#            (Gold and Bronze deals must be excluded)
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_silver_gets_only_silver_tier_deals(seeded, db):
    # deal5: Silver DISCOUNT → LoyaltyDiscountEngine (must be returned)
    # deal3: Gold MULTIPLIER → LoyaltyPointsEngine (must NOT be returned)
    # deal4: Gold DISCOUNT → LoyaltyDiscountEngine (must NOT be returned)
    points_engine = LoyaltyPointsEngine()
    discount_engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Silver",
        product_category="skincare",
    )

    points_results = points_engine.evaluate(request, [seeded["deal3"]], db)
    discount_results = discount_engine.evaluate(request, [seeded["deal4"], seeded["deal5"]], db)

    discount_result_ids = {r.deal_id for r in discount_results}

    assert seeded["deal5"].id in discount_result_ids, (
        "Silver-tier 15% discount must be returned for Silver member"
    )
    assert seeded["deal3"].id not in {r.deal_id for r in points_results}, (
        "Gold multiplier (rank=3) must NOT be returned for Silver member (rank=2)"
    )
    assert seeded["deal4"].id not in discount_result_ids, (
        "Gold discount (rank=3) must NOT be returned for Silver member (rank=2)"
    )

    silver_result = next(r for r in discount_results if r.deal_id == seeded["deal5"].id)
    assert silver_result.saving_amount == 15.0, (
        "Silver 15% discount on $100 must yield saving_amount=15.0"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16 — FLAT_REWARD with earn_type=points, no spend_per_increment → flat bonus
#           points_earned = earn_value directly (no rate calculation)
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_flat_reward_earn_type_points(seeded, db):
    engine = LoyaltyPointsEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )

    results = engine.evaluate(request, [seeded["deal6"]], db)

    assert len(results) == 1
    r = results[0]
    assert r.points_earned == 500, (
        "earn_type=points with earn_value=500 must return points_earned=500"
    )
    assert r.saving_amount == 0.0, (
        "Points-earning FLAT_REWARD must not set saving_amount"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 17 — FLAT_REWARD flat bonus with earn_cap per_transaction
#           spend_per_increment absent → flat bonus; earn_cap=300 caps from 500
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_flat_reward_earn_cap_per_transaction(seeded, db):
    engine = LoyaltyPointsEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )

    results = engine.evaluate(request, [seeded["deal7"]], db)

    assert len(results) == 1
    r = results[0]
    assert r.points_earned == 300, (
        "earn_cap=300 per_transaction must cap points_earned from 500 to 300"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 18 — FLAT_REWARD with earn_type=fixed_currency returns saving_amount
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_flat_reward_fixed_currency_returns_saving(seeded, db):
    engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )

    results = engine.evaluate(request, [seeded["deal8"]], db)

    assert len(results) == 1
    r = results[0]
    assert r.saving_amount == 10.0, (
        "earn_type=fixed_currency with discount_amount=10 must set saving_amount=10.0"
    )
    assert r.points_earned is None, (
        "Fixed-currency FLAT_REWARD must not set points_earned"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 19 — MULTIPLIER respects spend_per_increment
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_multiplier_spend_per_increment(seeded, db):
    engine = LoyaltyPointsEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=90.0,
        user_tier_name="Gold",
    )

    results = engine.evaluate(request, [seeded["deal9"]], db)

    assert len(results) == 1
    r = results[0]
    # increments = floor(90 / 3) = 30
    # base_points = 30 * earn_base_value(1) = 30
    # points_earned = floor(30 * earn_multiplier(3)) = 90
    assert r.points_earned == 90, (
        "spend_per_increment=3 on $90 → 30 increments × base=1 × multiplier=3 = 90 pts"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 20 — DISCOUNT deal with discount_amount_max caps saving_amount
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_discount_amount_max_caps_saving(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
    )

    results = engine.evaluate(request, [seeded["deal10"]], db)

    assert len(results) == 1
    r = results[0]
    assert r.saving_amount == 15.0, (
        "20% of $100 = $20, but discount_amount_max=15 must cap saving_amount to $15"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 21 — scope_channels filters out in_store-only deals
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_scope_channels_excludes_instore_deal(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
    )

    results = engine.evaluate(request, [seeded["deal11"]], db)

    assert results == [], (
        "Deal with scope_channels=['in_store'] must be excluded; MVP assumes online channel"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 22 — Deal with no scope_channels applies to all channels
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_no_scope_channels_applies_to_all_channels(seeded, db):
    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
    )

    results = engine.evaluate(request, [seeded["deal1"]], db)

    assert len(results) == 1, (
        "Deal with no scope_channels must be returned regardless of channel"
    )
    assert results[0].deal_id == seeded["deal1"].id


# ─────────────────────────────────────────────────────────────────────────────
# TEST 23 — FLAT_REWARD with earn_type=points and spend_per_increment → rate-based
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_flat_reward_rate_based_points(seeded, db):
    engine = LoyaltyPointsEngine()

    deal = Deal(
        title="_t23_flat_reward_rate_based",
        deal_type=DealType.FLAT_REWARD,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_type": "points", "earn_value": 2, "spend_per_increment": 5},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=seeded["merchant"].id,
        program_id=seeded["program"].id,
    )
    db.add(deal)
    db.flush()
    try:
        request = TrueCostRequest(
            merchant_slug="test-merchant",
            product_price=100.0,
            user_tier_name="Bronze",
        )
        results = engine.evaluate(request, [deal], db)

        assert len(results) == 1
        r = results[0]
        # increments = floor(100 / 5) = 20, raw_points = floor(20 * 2) = 40
        assert r.points_earned == 40, (
            "spend_per_increment=5 on $100 → 20 increments × earn_value=2 = 40 pts"
        )
        assert r.saving_amount == 0.0
    finally:
        db.delete(deal)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 24 — FLAT_REWARD rate-based with earn_cap caps the computed points
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_flat_reward_rate_based_points_with_cap(seeded, db):
    engine = LoyaltyPointsEngine()

    deal = Deal(
        title="_t24_flat_reward_rate_based_capped",
        deal_type=DealType.FLAT_REWARD,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={
            "earn_type": "points",
            "earn_value": 2,
            "spend_per_increment": 5,
            "earn_cap": 30,
            "earn_cap_period": "per_transaction",
        },
        is_stackable=True,
        is_evergreen=True,
        merchant_id=seeded["merchant"].id,
        program_id=seeded["program"].id,
    )
    db.add(deal)
    db.flush()
    try:
        request = TrueCostRequest(
            merchant_slug="test-merchant",
            product_price=100.0,
            user_tier_name="Bronze",
        )
        results = engine.evaluate(request, [deal], db)

        assert len(results) == 1
        r = results[0]
        # raw = floor(100/5) * 2 = 40, capped to earn_cap=30
        assert r.points_earned == 30, (
            "Rate-based earn of 40 pts must be capped to earn_cap=30 per_transaction"
        )
    finally:
        db.delete(deal)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 25 — MULTIPLIER with spend_per_increment not equal to 1
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_multiplier_spend_per_increment_non_unit(seeded, db):
    engine = LoyaltyPointsEngine()

    deal = Deal(
        title="_t25_multiplier_spend_per_increment_2",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 4, "earn_base_value": 1, "spend_per_increment": 2},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=seeded["merchant"].id,
        program_id=seeded["program"].id,
        tier_id=seeded["tiers"]["Gold"].id,
    )
    db.add(deal)
    db.flush()
    try:
        request = TrueCostRequest(
            merchant_slug="test-merchant",
            product_price=100.0,
            user_tier_name="Gold",
        )
        results = engine.evaluate(request, [deal], db)

        assert len(results) == 1
        r = results[0]
        # increments = floor(100 / 2) = 50
        # base_points = 50 * earn_base_value(1) = 50
        # points_earned = floor(50 * earn_multiplier(4)) = 200
        assert r.points_earned == 200, (
            "spend_per_increment=2 on $100 → 50 increments × base=1 × multiplier=4 = 200 pts"
        )
    finally:
        db.delete(deal)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 26 — CategoryMatcher: LLM returns True → category-gated deal is returned
# ─────────────────────────────────────────────────────────────────────────────

def test_category_matcher_llm_match_returns_deal(seeded, db):
    """Override the autouse exact-string mock to simulate LLM returning a semantic match.

    The product_category is 'face cream' and the deal scopes 'skincare'.
    Exact-string matching would miss this; LLM matching would catch it.
    We override CategoryMatcher.matches to always return True to simulate
    the LLM recognising the semantic relationship.
    """
    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        product_category="face cream",  # not an exact match for "skincare"
    )

    deal = Deal(
        title="_t26_category_matcher_llm_match",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10, "scope_categories": ["skincare"]},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=seeded["merchant"].id,
    )
    db.add(deal)
    db.flush()
    try:
        with patch(
            "deal_engine.category_matcher.CategoryMatcher.matches",
            return_value=True,
        ):
            results = engine.evaluate(request, [deal], db)

        assert len(results) == 1, (
            "LLM match=True must include the category-gated deal in results"
        )
        assert results[0].deal_id == deal.id
        assert results[0].saving_amount == 10.0
    finally:
        db.delete(deal)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 27 — CategoryMatcher: LLM returns False → category-gated deal excluded
# ─────────────────────────────────────────────────────────────────────────────

def test_category_matcher_llm_no_match_excludes_deal(seeded, db):
    """Override the autouse mock to simulate LLM returning no semantic match.

    Even though the product_category string is non-empty, a False from
    CategoryMatcher.matches must cause the deal to be excluded.
    """
    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        product_category="furniture",
    )

    deal = Deal(
        title="_t27_category_matcher_llm_no_match",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10, "scope_categories": ["skincare"]},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=seeded["merchant"].id,
    )
    db.add(deal)
    db.flush()
    try:
        with patch(
            "deal_engine.category_matcher.CategoryMatcher.matches",
            return_value=False,
        ):
            results = engine.evaluate(request, [deal], db)

        assert results == [], (
            "LLM match=False must exclude the category-gated deal"
        )
    finally:
        db.delete(deal)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 28 — CategoryMatcher: _llm_match raises → matches() catches, returns False,
#            engine excludes the deal and continues without re-raising
# ─────────────────────────────────────────────────────────────────────────────

def test_category_matcher_llm_error_excludes_deal_gracefully(seeded, db, caplog):
    """When _llm_match raises (e.g. network/API failure), CategoryMatcher.matches()
    must catch the exception, log a warning, return False, and the engine must
    exclude the deal rather than propagating the error.

    Strategy: override the autouse mock by installing a 'real' matches() implementation
    (the try/except wrapper that delegates to _llm_match), then patch _llm_match to raise.
    """
    import logging
    from deal_engine.category_matcher import CategoryMatcher

    _cm_logger = logging.getLogger("deal_engine.category_matcher")

    def _real_matches(self, product_category: str, scope_categories: list) -> bool:
        """Re-implements the real matches() logic so we can test its error handling."""
        try:
            return self._llm_match(product_category, scope_categories)
        except Exception as e:
            _cm_logger.warning(
                "CategoryMatcher.matches failed for product='%s' scope=%s: %s",
                product_category,
                scope_categories,
                e,
            )
            return False

    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        product_category="skincare",
    )

    deal = Deal(
        title="_t28_category_matcher_llm_error",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10, "scope_categories": ["skincare"]},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=seeded["merchant"].id,
    )
    db.add(deal)
    db.flush()
    try:
        with patch.object(CategoryMatcher, "matches", new=_real_matches), \
             patch.object(CategoryMatcher, "_llm_match", side_effect=RuntimeError("API timeout")), \
             caplog.at_level(logging.WARNING, logger="deal_engine.category_matcher"):

            results = engine.evaluate(request, [deal], db)

        assert results == [], (
            "When _llm_match raises, matches() must return False and the deal must be excluded"
        )
        assert any("API timeout" in r.message for r in caplog.records), (
            "A WARNING log containing the exception message must have been emitted"
        )
    finally:
        db.delete(deal)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 29 — Brand match: deal with scope_brands returned when brand matches
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_brand_match_returns_deal(seeded, db):
    engine = LoyaltyPointsEngine()  # deal3 is MULTIPLIER
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand="NARS",
    )

    results = engine.evaluate(request, [seeded["deal3"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal3"].id in result_ids, (
        "Deal with scope_brands=['NARS', 'Charlotte Tilbury'] must be returned "
        "when brand='NARS' matches"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 30 — Brand mismatch: deal with scope_brands excluded when brand does not match
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_brand_mismatch_excludes_deal(seeded, db):
    engine = LoyaltyPointsEngine()  # deal3 is MULTIPLIER
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand="MAC",
    )

    results = engine.evaluate(request, [seeded["deal3"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal3"].id not in result_ids, (
        "Deal with scope_brands=['NARS', 'Charlotte Tilbury'] must be excluded "
        "when brand='MAC' does not match (category 'skincare' matches but brand does not)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 31 — No brand provided: deal with scope_brands excluded conservatively
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_no_brand_excludes_brand_scoped_deal(seeded, db):
    engine = LoyaltyPointsEngine()  # deal3 is MULTIPLIER
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand=None,
    )

    results = engine.evaluate(request, [seeded["deal3"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal3"].id not in result_ids, (
        "Deal with scope_brands must be excluded when request.brand is None "
        "(cannot verify brand — exclude conservatively)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 32 — Deal with no scope_brands applies to all brands
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_no_scope_brands_applies_to_all_brands(seeded, db):
    engine = LoyaltyDiscountEngine()  # deal4 is DISCOUNT
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand="MAC",
    )

    # deal4: 20% Gold discount, scope_categories=["skincare"], no scope_brands
    results = engine.evaluate(request, [seeded["deal4"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal4"].id in result_ids, (
        "Deal with no scope_brands must be returned regardless of brand"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 33 — Preliminary price is passed to loyalty engine
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_preliminary_price_passed_to_loyalty(db):
    """Stage 1 LoyaltyDiscountEngine (20% member discount) reduces price 100→80;
    Stage 2 LoyaltyPointsEngine (2x MULTIPLIER) on price=80 yields points=160, not 200."""
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant, MembershipProgram

    merchant = Merchant(name="_T33 Merchant", slug="_t33_merchant", url="https://t33.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T33 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    # Program-wide member DISCOUNT (no tier required) — goes to LoyaltyDiscountEngine
    member_discount_deal = Deal(
        title="_T33 20% member discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 20},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    # Program-wide MULTIPLIER — goes to LoyaltyPointsEngine
    multiplier_deal = Deal(
        title="_T33 2x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 2, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    db.add_all([member_discount_deal, multiplier_deal])
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t33_merchant",
            product_price=100.0,
            user_tier_name="Bronze",  # program-wide deals apply to all members
        )
        result = orchestrator.run(request, db)

        # Verify engine_results has the correct keys
        assert "loyalty_discount" in result["engine_results"], (
            "engine_results must contain 'loyalty_discount' key"
        )
        assert "loyalty_points" in result["engine_results"], (
            "engine_results must contain 'loyalty_points' key"
        )

        # LoyaltyDiscountEngine: 20% on $100 = $20 saving
        discount_results = result["engine_results"]["loyalty_discount"]
        discount_for_deal = [r for r in discount_results if r.deal_id == member_discount_deal.id]
        assert len(discount_for_deal) == 1
        assert discount_for_deal[0].saving_amount == 20.0, (
            "LoyaltyDiscountEngine: 20% on $100 must yield saving_amount=20.0"
        )

        # LoyaltyPointsEngine: 2x on preliminary_price=$80 = 160 points
        points_results = result["engine_results"]["loyalty_points"]
        multiplier_results = [r for r in points_results if r.deal_id == multiplier_deal.id]
        assert len(multiplier_results) == 1, "Multiplier deal must appear in loyalty_points results"
        assert multiplier_results[0].points_earned == 160, (
            "LoyaltyPointsEngine must use preliminary price=80 (after 20% member discount), "
            f"yielding 160 points, got {multiplier_results[0].points_earned}"
        )
    finally:
        db.delete(multiplier_deal)
        db.delete(member_discount_deal)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 34 — No stage 1 discounts: loyalty engine uses original price
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_no_promo_loyalty_uses_original_price(db):
    """With no promo deals, preliminary_price == product_price; loyalty 2x on
    100 → points_earned==200."""
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant, MembershipProgram, Tier

    merchant = Merchant(name="_T34 Merchant", slug="_t34_merchant", url="https://t34.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T34 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    gold_tier = Tier(program_id=program.id, name="Gold", rank=3)
    db.add(gold_tier)
    db.flush()

    multiplier_deal = Deal(
        title="_T34 2x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 2, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
        tier_id=gold_tier.id,
    )
    db.add(multiplier_deal)
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t34_merchant",
            product_price=100.0,
            user_tier_name="Gold",
        )
        result = orchestrator.run(request, db)

        points_results = result["engine_results"].get("loyalty_points", [])
        multiplier_results = [r for r in points_results if r.deal_id == multiplier_deal.id]
        assert len(multiplier_results) == 1
        assert multiplier_results[0].points_earned == 200, (
            "With no discount deals, LoyaltyPointsEngine must use original price=100, "
            f"yielding 200 points, got {multiplier_results[0].points_earned}"
        )
    finally:
        db.delete(multiplier_deal)
        db.delete(gold_tier)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 35 — Stage 1 engine failure does not block stage 2
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_stage1_failure_does_not_block_stage2(db):
    """If LoyaltyDiscountEngine.evaluate raises, engine_results['loyalty_discount']==[]
    and LoyaltyPointsEngine still runs using the original product_price."""
    from deal_engine.orchestrator import DealOrchestrator
    from deal_engine.loyalty_discount_engine import LoyaltyDiscountEngine
    from modules.models import Merchant, MembershipProgram, Tier

    merchant = Merchant(name="_T35 Merchant", slug="_t35_merchant", url="https://t35.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T35 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    gold_tier = Tier(program_id=program.id, name="Gold", rank=3)
    db.add(gold_tier)
    db.flush()

    multiplier_deal = Deal(
        title="_T35 2x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 2, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
        tier_id=gold_tier.id,
    )
    db.add(multiplier_deal)
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t35_merchant",
            product_price=100.0,
            user_tier_name="Gold",
        )

        with patch.object(LoyaltyDiscountEngine, "evaluate", side_effect=Exception("discount failed")):
            result = orchestrator.run(request, db)

        assert result["engine_results"].get("loyalty_discount") == [], (
            "engine_results['loyalty_discount'] must be [] when LoyaltyDiscountEngine raises"
        )
        points_results = result["engine_results"].get("loyalty_points", [])
        multiplier_results = [r for r in points_results if r.deal_id == multiplier_deal.id]
        assert len(multiplier_results) == 1
        assert multiplier_results[0].points_earned == 200, (
            "When stage 1 fails, LoyaltyPointsEngine must fall back to original price=100, "
            f"yielding 200 points, got {multiplier_results[0].points_earned}"
        )
    finally:
        db.delete(multiplier_deal)
        db.delete(gold_tier)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 36 — _compute_preliminary_price: non-stackable wins over stackable stack
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_preliminary_price_nonstackable_wins():
    """Non-stackable deal alone (30% → $70) beats the stackable stack ($82.8).
    Bug: old logic incorrectly combined both → $57.96.
    """
    from deal_engine.orchestrator import DealOrchestrator

    orchestrator = DealOrchestrator()

    results = [
        AppliedDealResult(
            deal_id=1,
            deal_title="30% non-stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=30.0,
            saving_pct=0.30,
            is_stackable=False,
            applied=True,
        ),
        AppliedDealResult(
            deal_id=2,
            deal_title="10% stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=10.0,
            saving_pct=0.10,
            is_stackable=True,
            applied=True,
        ),
        AppliedDealResult(
            deal_id=3,
            deal_title="8% stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=8.0,
            saving_pct=0.08,
            is_stackable=True,
            applied=True,
        ),
    ]

    # Option 1 (non-stackable alone): 100 - 30 = 70.0
    # Option 2 (stackable stack):     10% of 100=10→90; 8% of 90=7.2→82.8
    # Winner: 70.0
    price = orchestrator._compute_preliminary_price(100.0, results)
    assert price == 70.0, (
        f"Non-stackable alone (70.0) must beat stackable stack (82.8), got {price}"
    )
    assert abs(price - 57.96) > 1.0, (
        "Must NOT produce the buggy result of ~57.96 that combines both options"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 37 — _compute_preliminary_price: stackable stack wins over non-stackable
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_preliminary_price_stackable_wins():
    """Stackable stack (15%+12% → $74.8) beats non-stackable alone (5% → $95).
    Verifies the comparison runs in both directions.
    """
    from deal_engine.orchestrator import DealOrchestrator

    orchestrator = DealOrchestrator()

    results = [
        AppliedDealResult(
            deal_id=1,
            deal_title="5% non-stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=5.0,
            saving_pct=0.05,
            is_stackable=False,
            applied=True,
        ),
        AppliedDealResult(
            deal_id=2,
            deal_title="15% stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=15.0,
            saving_pct=0.15,
            is_stackable=True,
            applied=True,
        ),
        AppliedDealResult(
            deal_id=3,
            deal_title="12% stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=12.0,
            saving_pct=0.12,
            is_stackable=True,
            applied=True,
        ),
    ]

    # Option 1 (non-stackable alone): 100 - 5 = 95.0
    # Option 2 (stackable stack):     15% of 100=15→85; 12% of 85=10.2→74.8
    # Winner: 74.8
    price = orchestrator._compute_preliminary_price(100.0, results)
    assert abs(price - 74.8) < 0.01, (
        f"Stackable stack (74.8) must beat non-stackable alone (95.0), got {price}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 38 — engine_results dict keys are unchanged after refactor
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_engine_results_keys(db):
    """engine_results must contain 'promo', 'loyalty_discount', and 'loyalty_points' keys."""
    from deal_engine.orchestrator import DealOrchestrator

    orchestrator = DealOrchestrator()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
        brand="NARS",
    )
    result = orchestrator.run(request, db)

    assert "promo" in result["engine_results"], "engine_results must contain 'promo' key"
    assert "loyalty_discount" in result["engine_results"], (
        "engine_results must contain 'loyalty_discount' key"
    )
    assert "loyalty_points" in result["engine_results"], (
        "engine_results must contain 'loyalty_points' key"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 46 — _compute_preliminary_price: empty stage_1_results returns original
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_preliminary_price_empty_returns_original():
    from deal_engine.orchestrator import DealOrchestrator

    orchestrator = DealOrchestrator()
    assert orchestrator._compute_preliminary_price(100.0, []) == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 47 — _compute_preliminary_price: only non-stackable deals
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_preliminary_price_only_nonstackable():
    """When there are only non-stackable deals and no stackable deals,
    the best non-stackable must be applied alone."""
    from deal_engine.orchestrator import DealOrchestrator

    orchestrator = DealOrchestrator()

    results = [
        AppliedDealResult(
            deal_id=1,
            deal_title="20% non-stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=20.0,
            saving_pct=0.20,
            is_stackable=False,
            applied=True,
        ),
        AppliedDealResult(
            deal_id=2,
            deal_title="15% non-stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=15.0,
            saving_pct=0.15,
            is_stackable=False,
            applied=True,
        ),
    ]

    # Option 1: best non-stackable = 20 → 100 - 20 = 80.0
    # Option 2: no stackable deals
    price = orchestrator._compute_preliminary_price(100.0, results)
    assert price == 80.0, (
        f"Best non-stackable (20%) alone must yield 80.0, got {price}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 48 — _compute_preliminary_price: only stackable deals
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_preliminary_price_only_stackable():
    """When there are only stackable deals and no non-stackable deals,
    the stackable stack is applied cumulatively."""
    from deal_engine.orchestrator import DealOrchestrator

    orchestrator = DealOrchestrator()

    results = [
        AppliedDealResult(
            deal_id=1,
            deal_title="10% stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=10.0,
            saving_pct=0.10,
            is_stackable=True,
            applied=True,
        ),
        AppliedDealResult(
            deal_id=2,
            deal_title="8% stackable",
            deal_type=DealType.DISCOUNT,
            redemption_method=RedemptionType.AUTOMATIC,
            saving_amount=8.0,
            saving_pct=0.08,
            is_stackable=True,
            applied=True,
        ),
    ]

    # Option 1: no non-stackable deals
    # Option 2: 10% of 100=10→90; 8% of 90=7.2→82.8
    price = orchestrator._compute_preliminary_price(100.0, results)
    assert abs(price - 82.8) < 0.01, (
        f"Stackable stack (10%+8%) must yield 82.8, got {price}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 39 — Member discount in stage 1, public promo also in stage 1
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_member_discount_and_public_promo_in_stage1(db):
    """Both PromoEngine and LoyaltyDiscountEngine run in stage 1.
    Combined discounts (10% public + 20% member, both stackable) reduce price to 72.
    LoyaltyPointsEngine receives 72 and computes 3x points = 216.
    """
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant, MembershipProgram

    merchant = Merchant(name="_T39 Merchant", slug="_t39_merchant", url="https://t39.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T39 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    public_discount = Deal(
        title="_T39 10% public discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        # no program_id → PromoEngine
    )
    member_discount = Deal(
        title="_T39 20% member discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 20},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,  # LoyaltyDiscountEngine
    )
    multiplier = Deal(
        title="_T39 3x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 3, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,  # LoyaltyPointsEngine
    )
    db.add_all([public_discount, member_discount, multiplier])
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t39_merchant",
            product_price=100.0,
            user_tier_name="Bronze",
        )
        result = orchestrator.run(request, db)

        # _compute_preliminary_price with two stackable deals (sorted by saving_amount desc):
        #   20% stackable: saving = 0.20 * 100 = 20, running = 80
        #   10% stackable: saving = 0.10 * 80 = 8, running = 72
        # LoyaltyPointsEngine receives price=72, 3x → 216 pts
        points_results = result["engine_results"].get("loyalty_points", [])
        multiplier_results = [r for r in points_results if r.deal_id == multiplier.id]
        assert len(multiplier_results) == 1
        assert multiplier_results[0].points_earned == 216, (
            "LoyaltyPointsEngine must receive preliminary price=72, "
            f"yielding 3x * 72 = 216 pts, got {multiplier_results[0].points_earned}"
        )

        # Confirm the discount results are present from both stage-1 engines
        promo_results = result["engine_results"].get("promo", [])
        assert any(r.deal_id == public_discount.id for r in promo_results), (
            "Public 10% discount must appear in promo engine results"
        )
        discount_results = result["engine_results"].get("loyalty_discount", [])
        assert any(r.deal_id == member_discount.id for r in discount_results), (
            "Member 20% discount must appear in loyalty_discount engine results"
        )
    finally:
        db.delete(multiplier)
        db.delete(member_discount)
        db.delete(public_discount)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 40 — Non-member gets no loyalty discount and no points
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_non_member_gets_no_loyalty(db):
    """user_tier_name=None → both loyalty engines return []; only public promo applies."""
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant, MembershipProgram

    merchant = Merchant(name="_T40 Merchant", slug="_t40_merchant", url="https://t40.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T40 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    public_discount = Deal(
        title="_T40 10% public discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
    )
    member_discount = Deal(
        title="_T40 20% member discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 20},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    multiplier = Deal(
        title="_T40 3x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 3, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    db.add_all([public_discount, member_discount, multiplier])
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t40_merchant",
            product_price=100.0,
            user_tier_name=None,  # non-member
        )
        result = orchestrator.run(request, db)

        assert result["engine_results"].get("loyalty_discount") == [], (
            "Non-member must get no loyalty_discount results"
        )
        assert result["engine_results"].get("loyalty_points") == [], (
            "Non-member must get no loyalty_points results"
        )

        promo_results = result["engine_results"].get("promo", [])
        assert any(r.deal_id == public_discount.id for r in promo_results), (
            "Non-member must still receive the public 10% promo deal"
        )
    finally:
        db.delete(multiplier)
        db.delete(member_discount)
        db.delete(public_discount)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 41 — resolve_memberships: program with no tiers
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_memberships_program_with_no_tiers(db):
    """When a program has no tiers, any user with a non-None user_tier_name is
    considered a member. tier and tier_rank must both be None."""
    from modules.models import Merchant, MembershipProgram

    merchant = Merchant(name="_T41 Merchant", slug="_t41_merchant", url="https://t41.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T41 No-Tier Program",
        program_description="",
        # no tiers added
    )
    db.add(program)
    db.flush()

    try:
        request = TrueCostRequest(
            merchant_slug="_t41_merchant",
            product_price=100.0,
            user_tier_name="Member",
        )
        context = resolve_memberships(request, db, merchant.id)

        assert program.id in context.memberships, (
            "Program with no tiers must appear in memberships for any non-None user_tier_name"
        )
        info = context.memberships[program.id]
        assert info.tier is None, "tier must be None when program has no tiers"
        assert info.tier_rank is None, "tier_rank must be None when program has no tiers"
    finally:
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 42 — resolve_memberships: tier name not in any program
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_memberships_unknown_tier_returns_empty(seeded, db):
    """user_tier_name that matches no tier in any program → empty memberships dict."""
    from modules.models import Merchant as _Merchant

    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="NonExistentTier",
    )
    merchant = db.query(_Merchant).filter_by(slug="test-merchant").first()

    context = resolve_memberships(request, db, merchant.id)

    assert context.memberships == {}, (
        "Unknown tier name must return empty memberships dict without raising"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 43 — filter_eligible_deals: program-wide deal (no tier_id) applies to all members
# ─────────────────────────────────────────────────────────────────────────────

def test_filter_eligible_deals_program_wide_deal(seeded, db):
    """A deal with program_id set but tier_id=None must be returned for any member
    regardless of their tier rank."""
    from deal_engine.category_matcher import CategoryMatcher

    # deal6: program-wide FLAT_REWARD (earn_type=points), no tier_id
    context = EligibilityContext(memberships={
        seeded["program"].id: MembershipInfo(
            program_id=seeded["program"].id,
            tier=seeded["tiers"]["Bronze"],
            tier_rank=1,
        )
    })
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )

    eligible = filter_eligible_deals(
        [seeded["deal6"]], context, request, CategoryMatcher()
    )

    assert seeded["deal6"].id in {d.id for d in eligible}, (
        "Program-wide deal (tier_id=None) must be eligible for any member"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 44 — filter_eligible_deals: tier-specific deal exact rank match
# ─────────────────────────────────────────────────────────────────────────────

def test_filter_eligible_deals_tier_exact_match(seeded, db):
    """A deal gated at Silver (rank=2) must be returned for a Silver user (rank=2)."""
    from deal_engine.category_matcher import CategoryMatcher

    # deal5: Silver DISCOUNT, tier_id=silver.id (rank=2)
    context = EligibilityContext(memberships={
        seeded["program"].id: MembershipInfo(
            program_id=seeded["program"].id,
            tier=seeded["tiers"]["Silver"],
            tier_rank=2,
        )
    })
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Silver",
    )

    eligible = filter_eligible_deals(
        [seeded["deal5"]], context, request, CategoryMatcher()
    )

    assert seeded["deal5"].id in {d.id for d in eligible}, (
        "Tier-specific deal (rank=2) must be returned for Silver user (rank=2)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 45 — filter_eligible_deals: tier-specific deal rank mismatch
# ─────────────────────────────────────────────────────────────────────────────

def test_filter_eligible_deals_tier_rank_mismatch(seeded, db):
    """A deal gated at Gold (rank=3) must NOT be returned for a Silver user (rank=2).
    Uses deal9 (Gold MULTIPLIER, no scope_categories) to isolate the tier check."""
    from deal_engine.category_matcher import CategoryMatcher

    # deal9: Gold MULTIPLIER (tier_id=gold.id, rank=3), no scope_categories
    context = EligibilityContext(memberships={
        seeded["program"].id: MembershipInfo(
            program_id=seeded["program"].id,
            tier=seeded["tiers"]["Silver"],
            tier_rank=2,
        )
    })
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Silver",
    )

    eligible = filter_eligible_deals(
        [seeded["deal9"]], context, request, CategoryMatcher()
    )

    assert seeded["deal9"].id not in {d.id for d in eligible}, (
        "Gold deal (rank=3) must NOT be returned for Silver user (rank=2)"
    )



# ─────────────────────────────────────────────────────────────────────────────
# TEST 52 — Members-only PROMO_CODE deal is discovered without a user-supplied code
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_discount_promo_code_discovered_without_input(seeded, db):
    """LoyaltyDiscountEngine must return PROMO_CODE deals regardless of whether
    the user supplied any code. The deal's promo_code string must be surfaced
    on the result so the caller knows what to enter at checkout."""
    engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )
    results = engine.evaluate(request, [seeded["deal12"]], db)

    deal_ids = {r.deal_id for r in results}
    assert seeded["deal12"].id in deal_ids, (
        "PROMO_CODE deal must be discovered and returned without a user-supplied code"
    )
    matched = next(r for r in results if r.deal_id == seeded["deal12"].id)
    assert matched.saving_amount == 20.0, "20% of $100 must yield saving_amount=20.0"
    assert matched.redemption_method == RedemptionType.PROMO_CODE, (
        "Result must carry redemption_method=PROMO_CODE"
    )
    assert matched.promo_code == "MEMBER20", (
        "promo_code field on result must surface the deal's code string"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 54 — All three redemption types discovered together
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_discount_all_redemption_types_discovered(seeded, db):
    """PROMO_CODE, AUTOMATIC, and ACTIVATED deals must all appear in results
    for an eligible member — no redemption type is gated on user input."""
    engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )
    results = engine.evaluate(
        request,
        [seeded["deal12"], seeded["deal13"], seeded["deal14"]],
        db,
    )

    deal_ids = {r.deal_id for r in results}
    assert seeded["deal12"].id in deal_ids, "PROMO_CODE deal must be discovered"
    assert seeded["deal13"].id in deal_ids, "AUTOMATIC deal must be included"
    assert seeded["deal14"].id in deal_ids, "ACTIVATED deal must be included"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 55 — Non-member is excluded regardless of deal type
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_discount_non_member_excluded(seeded, db):
    """A user with no tier (non-member) must receive nothing — the program/tier
    eligibility check fires before any redemption-type logic."""
    engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name=None,
    )
    results = engine.evaluate(request, [seeded["deal12"]], db)

    assert results == [], "Non-member must receive no results"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 56 — AUTOMATIC and PROMO_CODE deals both discovered together
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_discount_automatic_and_promo_code_both_discovered(seeded, db):
    """Both AUTOMATIC and PROMO_CODE deals must appear in results together."""
    engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )
    results = engine.evaluate(
        request,
        [seeded["deal12"], seeded["deal13"]],
        db,
    )

    deal_ids = {r.deal_id for r in results}
    assert seeded["deal13"].id in deal_ids, "AUTOMATIC deal must be included"
    assert seeded["deal12"].id in deal_ids, "PROMO_CODE deal must be discovered alongside AUTOMATIC"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 57 — ACTIVATED deal applied to eligible member (MVP behaviour)
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_discount_activated_applied_to_eligible_member(seeded, db):
    """ACTIVATED deals must be applied to eligible members without any
    activation-state check at MVP."""
    engine = LoyaltyDiscountEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
    )
    results = engine.evaluate(request, [seeded["deal14"]], db)

    deal_ids = {r.deal_id for r in results}
    assert seeded["deal14"].id in deal_ids, (
        "ACTIVATED deal must be applied to eligible member at MVP "
        "(activation tracking is a v2 concern)"
    )
    matched = next(r for r in results if r.deal_id == seeded["deal14"].id)
    assert matched.saving_amount == 5.0, "5% of $100 must yield saving_amount=5.0"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 60 — Full orchestrator flow: PROMO_CODE deal applied in stage 1 optimistically
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_member_promo_code_applied_in_stage1(db):
    """PROMO_CODE deal is discovered optimistically in stage 1 without any
    user-supplied code. Its saving reduces the preliminary price passed to stage 2.
    A 1x multiplier seeded alongside it receives preliminary_price=80, yielding 80 pts."""
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant, MembershipProgram, Tier

    merchant = Merchant(name="_T60 Merchant", slug="_t60_merchant", url="https://t60.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T60 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    bronze_tier = Tier(program_id=program.id, name="Bronze", rank=1)
    db.add(bronze_tier)
    db.flush()

    deal_promo = Deal(
        title="_T60 20% promo code deal",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.PROMO_CODE,
        promo_code="MEMBER20",
        deal_details={"discount_percent": 20},
        is_stackable=False,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    deal_multiplier = Deal(
        title="_T60 1x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 1, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    db.add(deal_promo)
    db.add(deal_multiplier)
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t60_merchant",
            product_price=100.0,
            user_tier_name="Bronze",
        )
        result = orchestrator.run(request, db)

        discount_results = result["engine_results"]["loyalty_discount"]
        promo_matches = [r for r in discount_results if r.deal_id == deal_promo.id]
        assert len(promo_matches) == 1, (
            "PROMO_CODE deal must appear in loyalty_discount stage 1 results"
        )
        assert promo_matches[0].saving_amount == 20.0, "20% of $100 must yield saving_amount=20.0"
        assert promo_matches[0].promo_code == "MEMBER20", (
            "promo_code field must surface the deal's code string"
        )

        # Multiplier receives preliminary_price=80 (after 20% off), so points_earned=80
        points_results = result["engine_results"]["loyalty_points"]
        mult_matches = [r for r in points_results if r.deal_id == deal_multiplier.id]
        assert len(mult_matches) == 1, "Multiplier must appear in loyalty_points results"
        assert mult_matches[0].points_earned == 80, (
            "1x multiplier on preliminary_price=80 must yield 80 points, "
            f"got {mult_matches[0].points_earned}"
        )
    finally:
        db.delete(deal_promo)
        db.delete(deal_multiplier)
        db.delete(bronze_tier)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 61 — Orchestrator: PROMO_CODE (non-stackable) beats AUTOMATIC (stackable)
#           in preliminary price when it offers a larger saving
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_promo_code_beats_automatic_when_larger(db):
    """With both a PROMO_CODE deal (20% off, non-stackable) and an AUTOMATIC deal
    (10% off, stackable), the preliminary price algorithm picks the best option:
      Option 1: non-stackable alone = 80
      Option 2: stackable stack     = 90
    Best is min(80, 90) = 80, so the multiplier earns 80 points."""
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant, MembershipProgram, Tier

    merchant = Merchant(name="_T61 Merchant", slug="_t61_merchant", url="https://t61.test")
    db.add(merchant)
    db.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="_T61 Program",
        program_description="",
    )
    db.add(program)
    db.flush()

    bronze_tier = Tier(program_id=program.id, name="Bronze", rank=1)
    db.add(bronze_tier)
    db.flush()

    deal_promo = Deal(
        title="_T61 20% promo code deal",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.PROMO_CODE,
        promo_code="MEMBER20",
        deal_details={"discount_percent": 20},
        is_stackable=False,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    deal_auto = Deal(
        title="_T61 10% automatic deal",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    deal_multiplier = Deal(
        title="_T61 1x multiplier",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 1, "earn_base_value": 1, "spend_per_increment": 1},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    db.add(deal_promo)
    db.add(deal_auto)
    db.add(deal_multiplier)
    db.commit()

    try:
        orchestrator = DealOrchestrator()
        request = TrueCostRequest(
            merchant_slug="_t61_merchant",
            product_price=100.0,
            user_tier_name="Bronze",
        )
        result = orchestrator.run(request, db)

        discount_results = result["engine_results"]["loyalty_discount"]
        discount_ids = {r.deal_id for r in discount_results}

        assert deal_promo.id in discount_ids, (
            "PROMO_CODE deal must be discovered optimistically in stage 1"
        )
        assert deal_auto.id in discount_ids, (
            "AUTOMATIC deal must also appear in stage 1 results"
        )

        # Preliminary price: best of (non-stackable 20%=80) vs (stackable 10%=90) → 80
        # Multiplier therefore earns 80 points
        points_results = result["engine_results"]["loyalty_points"]
        mult_matches = [r for r in points_results if r.deal_id == deal_multiplier.id]
        assert len(mult_matches) == 1
        assert mult_matches[0].points_earned == 80, (
            "Non-stackable PROMO_CODE 20% off wins preliminary price calculation: "
            "1x multiplier on preliminary_price=80 must yield 80 points, "
            f"got {mult_matches[0].points_earned}"
        )
    finally:
        db.delete(deal_promo)
        db.delete(deal_auto)
        db.delete(deal_multiplier)
        db.delete(bronze_tier)
        db.delete(program)
        db.delete(merchant)
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 62 — PromoEngine surfaces promo_code on public PROMO_CODE deals
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_engine_surfaces_promo_code(seeded, db):
    """PromoEngine must surface the deal's promo_code string on the result for
    PROMO_CODE redemption deals. deal2 is a public PROMO_CODE 'SAVE15' deal."""
    from deal_engine.promo_engine import PromoEngine

    engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
    )
    results = engine.evaluate(request, [seeded["deal2"]], db)

    assert any(r.deal_id == seeded["deal2"].id for r in results), (
        "deal2 (public PROMO_CODE SAVE15) must appear in PromoEngine results"
    )
    matched = next(r for r in results if r.deal_id == seeded["deal2"].id)
    assert matched.promo_code == "SAVE15", (
        "promo_code field must surface 'SAVE15' for deal2"
    )
    assert matched.redemption_method == RedemptionType.PROMO_CODE
