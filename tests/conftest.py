"""
Test configuration and shared fixtures.

Boot-order matters here:
  1. Dummy env vars must be set before any module-level SQLAlchemy code runs.
  2. MetaData.create_all is patched so that models.py's module-level
     Base.metadata.create_all(pg_engine) becomes a no-op (no real PG needed).
  3. After all module imports, the patch is removed and we call the real
     create_all against an in-memory SQLite engine.
"""

import os
import sys
from unittest.mock import patch

# ── 1. Dummy env vars ────────────────────────────────────────────────────────
os.environ.setdefault("SUPABASE_DB_HOST_URL", "localhost")
os.environ.setdefault("SUPABASE_DB_PASSWORD", "test")
os.environ.setdefault("DATABASE_POOL_SIZE", "1")

# ── 2. Project root on sys.path ──────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── 3. Patch MetaData.create_all before modules.models is imported ───────────
_pg_patch = patch("sqlalchemy.sql.schema.MetaData.create_all")
_pg_patch.start()

# All imports that trigger module-level SQLAlchemy engine creation go here ↓
from datetime import datetime, timezone, timedelta  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from modules.models import Base, Merchant, MembershipProgram, Tier, Deal  # noqa: E402
from modules.schemas import DealType, RedemptionType  # noqa: E402
from api.api import app, get_db  # noqa: E402  (api/ is a namespace package)

# ── 4. Restore real create_all and build SQLite test DB ─────────────────────
_pg_patch.stop()

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
Base.metadata.create_all(_test_engine)
_TestSession = sessionmaker(bind=_test_engine)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db():
    """
    Single SQLite session seeded with:
      - 1 Merchant  (slug="test-merchant")
      - 1 MembershipProgram
      - 3 Tiers     (Bronze rank=1, Silver rank=2, Gold rank=3)
      - 11 Deals    (see inline comments)
    """
    session = _TestSession()

    merchant = Merchant(name="Test Merchant", slug="test-merchant", url="https://test.com")
    session.add(merchant)
    session.flush()

    program = MembershipProgram(
        merchant_id=merchant.id,
        program_name="Test Rewards",
        program_description="Test loyalty program",
    )
    session.add(program)
    session.flush()

    bronze = Tier(program_id=program.id, name="Bronze", rank=1)
    silver = Tier(program_id=program.id, name="Silver", rank=2)
    gold = Tier(program_id=program.id, name="Gold", rank=3)
    session.add_all([bronze, silver, gold])
    session.flush()

    # Deal 1 — public DISCOUNT 10%, AUTOMATIC, evergreen, stackable
    deal1 = Deal(
        title="10% off everything",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
    )
    # Deal 2 — public FLAT_REWARD $15, PROMO_CODE "SAVE15", min $50, NOT stackable, evergreen
    deal2 = Deal(
        title="$15 off orders over $50",
        deal_type=DealType.FLAT_REWARD,
        redemption_method=RedemptionType.PROMO_CODE,
        promo_code="SAVE15",
        deal_details={"discount_amount": 15, "spend_min": 50},
        is_stackable=False,
        is_evergreen=True,
        merchant_id=merchant.id,
    )
    # Deal 3 — Gold loyalty MULTIPLIER 3x, evergreen
    deal3 = Deal(
        title="3x points for Gold members",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 3, "earn_base_value": 1, "spend_per_increment": 1, "scope_categories": ["skincare"], "scope_brands": ["NARS", "Charlotte Tilbury"]},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
        tier_id=gold.id,
    )
    # Deal 4 — Gold loyalty DISCOUNT 20%, evergreen, stackable
    deal4 = Deal(
        title="20% off for Gold members",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 20, "scope_categories": ["skincare"]},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
        tier_id=gold.id,
    )
    # Deal 5 — Silver loyalty DISCOUNT 15%, evergreen, stackable (no category restriction)
    deal5 = Deal(
        title="15% off for Silver members",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 15},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
        tier_id=silver.id,
    )
    # Deal 6 — program-wide FLAT_REWARD 500pts (earn_type=points), spend_min=50, evergreen
    deal6 = Deal(
        title="500 bonus points for members",
        deal_type=DealType.FLAT_REWARD,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_type": "points", "earn_value": 500, "spend_min": 50},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    # Deal 7 — program-wide FLAT_REWARD 500pts, earn_cap=300 per_transaction, evergreen
    deal7 = Deal(
        title="500 bonus points capped at 300",
        deal_type=DealType.FLAT_REWARD,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={
            "earn_type": "points",
            "earn_value": 500,
            "earn_cap": 300,
            "earn_cap_period": "per_transaction",
        },
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    # Deal 8 — program-wide FLAT_REWARD $10 fixed_currency discount, evergreen
    deal8 = Deal(
        title="$10 fixed currency reward for members",
        deal_type=DealType.FLAT_REWARD,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_type": "fixed_currency", "discount_amount": 10},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    # Deal 9 — Gold loyalty MULTIPLIER 3x, spend_per_increment=3, evergreen
    deal9 = Deal(
        title="3x points per $3 for Gold members",
        deal_type=DealType.MULTIPLIER,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"earn_multiplier": 3, "earn_base_value": 1, "spend_per_increment": 3},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
        tier_id=gold.id,
    )
    # Deal 10 — public DISCOUNT 20% capped at $15, evergreen, stackable (promo engine)
    deal10 = Deal(
        title="20% off capped at $15",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 20, "discount_amount_max": 15},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
    )
    # Deal 11 — public DISCOUNT 10% in-store only, evergreen (filtered by scope_channels)
    deal11 = Deal(
        title="10% off in-store only",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10, "scope_channels": ["in_store"]},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
    )
    # Deal 12 — program-wide members-only PROMO_CODE DISCOUNT 20%, NOT stackable, evergreen
    deal12 = Deal(
        title="Members 20% promo code discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.PROMO_CODE,
        promo_code="MEMBER20",
        deal_details={"discount_percent": 20},
        is_stackable=False,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    # Deal 13 — program-wide members-only AUTOMATIC DISCOUNT 10%, stackable, evergreen
    deal13 = Deal(
        title="Members 10% automatic discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.AUTOMATIC,
        deal_details={"discount_percent": 10},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    # Deal 14 — program-wide members-only ACTIVATED DISCOUNT 5%, stackable, evergreen
    deal14 = Deal(
        title="Members 5% activated discount",
        deal_type=DealType.DISCOUNT,
        redemption_method=RedemptionType.ACTIVATED,
        deal_details={"discount_percent": 5},
        is_stackable=True,
        is_evergreen=True,
        merchant_id=merchant.id,
        program_id=program.id,
    )
    session.add_all([deal1, deal2, deal3, deal4, deal5, deal6, deal7, deal8, deal9, deal10, deal11, deal12, deal13, deal14])
    session.commit()

    yield session
    session.close()


@pytest.fixture(scope="session")
def seeded(db):
    """Returns a dict of named ORM objects so tests can reference IDs/ranks."""
    merchant = db.query(Merchant).filter_by(slug="test-merchant").first()
    program = db.query(MembershipProgram).filter_by(merchant_id=merchant.id).first()
    tiers = {t.name: t for t in db.query(Tier).filter_by(program_id=program.id).all()}
    deal_map = {
        d.title: d
        for d in db.query(Deal).filter_by(merchant_id=merchant.id).all()
    }
    return {
        "merchant": merchant,
        "program": program,
        "tiers": tiers,
        "deal1": deal_map["10% off everything"],
        "deal2": deal_map["$15 off orders over $50"],
        "deal3": deal_map["3x points for Gold members"],
        "deal4": deal_map["20% off for Gold members"],
        "deal5": deal_map["15% off for Silver members"],
        "deal6": deal_map["500 bonus points for members"],
        "deal7": deal_map["500 bonus points capped at 300"],
        "deal8": deal_map["$10 fixed currency reward for members"],
        "deal9": deal_map["3x points per $3 for Gold members"],
        "deal10": deal_map["20% off capped at $15"],
        "deal11": deal_map["10% off in-store only"],
        "deal12": deal_map["Members 20% promo code discount"],
        "deal13": deal_map["Members 10% automatic discount"],
        "deal14": deal_map["Members 5% activated discount"],
    }


@pytest.fixture(scope="session")
def client(db):
    """TestClient with get_db overridden to use the SQLite test session."""
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
