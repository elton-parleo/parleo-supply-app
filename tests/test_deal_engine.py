"""
Deal engine test suite.

Engine tests (1-7)      — call PromoEngine / LoyaltyEngine directly with real SQLite data.
Calculator tests (8-10) — call TrueCostCalculator.calculate() with hand-crafted fixtures.
Integration test (11)   — POST /api/deals/true-cost via TestClient.
Category tests (12-14)  — validate applicable_categories filtering in both engines.
"""

import pytest

from deal_engine.promo_engine import PromoEngine
from deal_engine.loyalty_engine import LoyaltyEngine
from deal_engine.calculator import TrueCostCalculator
from deal_engine.schemas import TrueCostRequest, AppliedDealResult
from modules.schemas import DealType, RedemptionType


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

    assert results == [], "Deal with minimum_order_value=50 must be excluded when product_price=40"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Category filter: deals with applicable_categories skipped when
#           no product_category is provided in the request
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_category_required_but_absent(seeded, db):
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category=None,
    )

    results = engine.evaluate(request, [seeded["deal3"], seeded["deal4"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal3"].id not in result_ids, (
        "3x multiplier (applicable_categories=['skincare']) must be skipped "
        "when product_category is None"
    )
    assert seeded["deal4"].id not in result_ids, (
        "20% Gold discount (applicable_categories=['skincare']) must be skipped "
        "when product_category is None"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Loyalty engine: no tier signal returns empty
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_no_tier(seeded, db):
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant", product_price=100.0, user_tier_name=None
    )

    results = engine.evaluate(request, [seeded["deal3"], seeded["deal4"]], db)

    assert results == [], "No user_tier_name must return empty from LoyaltyEngine"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Loyalty engine: Bronze tier gets no Gold deals
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_bronze_excluded_from_gold(seeded, db):
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Bronze",
        product_category="skincare",
    )
    loyalty_deals = [seeded["deal3"], seeded["deal4"]]

    results = engine.evaluate(request, loyalty_deals, db)

    gold_deal_ids = {d.id for d in loyalty_deals if d.tier_id == seeded["tiers"]["Gold"].id}
    result_ids = {r.deal_id for r in results}
    assert result_ids.isdisjoint(gold_deal_ids), (
        "Bronze (rank=1) must not receive deals gated at Gold (rank=3)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — Loyalty engine: Gold tier with matching category gets both tier deals
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_gold_gets_all(seeded, db):
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
    )

    results = engine.evaluate(request, [seeded["deal3"], seeded["deal4"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal3"].id in result_ids, "Gold multiplier deal must be returned"
    assert seeded["deal4"].id in result_ids, "Gold discount deal must be returned"


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

    Expected resolution (see calculator.py Rule B):
      - PromoEngine:   deal1 (10% stackable), deal2 ($15 non-stackable)
      - LoyaltyEngine: deal3 (3x multiplier, skincare ✓), deal4 (20% stackable, skincare ✓)
      - stackable sum (10+20=30) > non-stackable (15) → stackable set wins
      - Applied: deal1 + deal4 + deal3(multiplier); deal2 suppressed
      - true_cost = 100 - 10 - 20 = 70   (<100 ✓)
      - total_points_earned = 300 + floor(70) = 370   (>0 ✓)
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
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
    )

    results = engine.evaluate(request, [seeded["deal3"], seeded["deal4"]], db)

    result_ids = {r.deal_id for r in results}
    assert seeded["deal3"].id in result_ids, (
        "3x multiplier must be returned when product_category matches 'skincare'"
    )
    assert seeded["deal4"].id in result_ids, (
        "20% Gold discount must be returned when product_category matches 'skincare'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13 — Category filter: non-matching category excludes category-gated deals
#            but leaves category-agnostic deals untouched
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_nonmatching_category_excludes_deals(seeded, db):
    loyalty_engine = LoyaltyEngine()
    promo_engine = PromoEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="lipstick",
    )

    loyalty_results = loyalty_engine.evaluate(
        request, [seeded["deal3"], seeded["deal4"]], db
    )
    promo_results = promo_engine.evaluate(request, [seeded["deal1"]], db)

    loyalty_ids = {r.deal_id for r in loyalty_results}
    assert seeded["deal3"].id not in loyalty_ids, (
        "3x multiplier (skincare only) must be excluded for 'lipstick' product"
    )
    assert seeded["deal4"].id not in loyalty_ids, (
        "20% Gold discount (skincare only) must be excluded for 'lipstick' product"
    )

    # deal1 has no applicable_categories — it must survive any product_category value
    promo_ids = {r.deal_id for r in promo_results}
    assert seeded["deal1"].id in promo_ids, (
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
        "Deal with no applicable_categories must be returned regardless of product_category"
    )
    assert results[0].deal_id == seeded["deal1"].id
