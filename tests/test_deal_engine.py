"""
Deal engine test suite.

Engine tests (1-7)      — call PromoEngine / LoyaltyEngine directly with real SQLite data.
Calculator tests (8-10) — call TrueCostCalculator.calculate() with hand-crafted fixtures.
Integration test (11)   — POST /api/deals/true-cost via TestClient.
Category tests (12-14)  — validate scope_categories filtering in both engines.
"""

import pytest

from deal_engine.promo_engine import PromoEngine
from deal_engine.loyalty_engine import LoyaltyEngine
from deal_engine.calculator import TrueCostCalculator
from deal_engine.schemas import TrueCostRequest, AppliedDealResult
from modules.schemas import DealType, RedemptionType
from modules.models import Deal


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
        "3x multiplier (scope_categories=['skincare']) must be skipped "
        "when product_category is None"
    )
    assert seeded["deal4"].id not in result_ids, (
        "20% Gold discount (scope_categories=['skincare']) must be skipped "
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
# TEST 7 — Loyalty engine: Gold tier gets only Gold-tier deals (not Silver/Bronze)
#           deal3 seed includes earn_base_value=1, spend_per_increment=1, so
#           points_earned = floor(100/1) * 1 * 3 = 300 (same as the original naive formula).
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_gold_gets_only_gold_tier_deals(seeded, db):
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Gold",
        product_category="skincare",
    )

    all_loyalty_deals = [seeded["deal3"], seeded["deal4"], seeded["deal5"]]
    results = engine.evaluate(request, all_loyalty_deals, db)

    result_ids = {r.deal_id for r in results}

    # Gold-tier deals must be returned
    assert seeded["deal3"].id in result_ids, "Gold multiplier deal must be returned for Gold member"
    assert seeded["deal4"].id in result_ids, "Gold discount deal must be returned for Gold member"

    # Silver-tier deal must NOT be returned (exclusive per-tier matching)
    assert seeded["deal5"].id not in result_ids, (
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
        "3x multiplier (scope_categories=['skincare']) must be excluded for 'lipstick' product"
    )
    assert seeded["deal4"].id not in loyalty_ids, (
        "20% Gold discount (scope_categories=['skincare']) must be excluded for 'lipstick' product"
    )

    # deal1 has no scope_categories — it must survive any product_category value
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
        "Deal with no scope_categories must be returned regardless of product_category"
    )
    assert results[0].deal_id == seeded["deal1"].id


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15 — Loyalty engine: Silver tier gets only Silver-tier deals
#            (Gold and Bronze deals must be excluded)
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_silver_gets_only_silver_tier_deals(seeded, db):
    engine = LoyaltyEngine()
    request = TrueCostRequest(
        merchant_slug="test-merchant",
        product_price=100.0,
        user_tier_name="Silver",
        product_category="skincare",
    )

    all_loyalty_deals = [seeded["deal3"], seeded["deal4"], seeded["deal5"]]
    results = engine.evaluate(request, all_loyalty_deals, db)

    result_ids = {r.deal_id for r in results}

    # Silver-tier deal must be returned
    assert seeded["deal5"].id in result_ids, (
        "Silver-tier 15% discount must be returned for Silver member"
    )

    # Gold-tier deals must NOT be returned
    assert seeded["deal3"].id not in result_ids, (
        "Gold multiplier (rank=3) must NOT be returned for Silver member (rank=2)"
    )
    assert seeded["deal4"].id not in result_ids, (
        "Gold discount (rank=3) must NOT be returned for Silver member (rank=2)"
    )

    # Verify the saving amount is correct
    silver_result = next(r for r in results if r.deal_id == seeded["deal5"].id)
    assert silver_result.saving_amount == 15.0, (
        "Silver 15% discount on $100 must yield saving_amount=15.0"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16 — FLAT_REWARD with earn_type=points, no spend_per_increment → flat bonus
#           points_earned = earn_value directly (no rate calculation)
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_flat_reward_earn_type_points(seeded, db):
    engine = LoyaltyEngine()
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
    engine = LoyaltyEngine()
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
    engine = LoyaltyEngine()
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
    engine = LoyaltyEngine()
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
    engine = LoyaltyEngine()

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
    engine = LoyaltyEngine()

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
    engine = LoyaltyEngine()

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
