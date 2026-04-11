"""
Product resolver test suite.

Tests 1-6  — unit/integration tests for ProductResolver.resolve()
              using the real SQLite DB from conftest.py (seeded with test-merchant).
Test 7-8   — endpoint tests via TestClient with ProductResolver.resolve() mocked.
Test 9     — confirms user_tier_name is passed through to TrueCostRequest.
"""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from product_resolver.resolver import ProductResolver
from product_resolver.scraper import ProductScraper
from product_resolver.extractor import ProductExtractor
from product_resolver.schemas import ExtractedProduct, ProductTrueCostResponse
from deal_engine.schemas import TrueCostResponse


# ─────────────────────────────────────────────────────────────────────────────
# Empty-DB fixture (for TEST 6 only)
# ─────────────────────────────────────────────────────────────────────────────

# Re-use the already-imported Base (patching is done in conftest.py by now)
from modules.models import Base

_empty_engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}
)
Base.metadata.create_all(_empty_engine)
_EmptySession = sessionmaker(bind=_empty_engine)


@pytest.fixture
def empty_db():
    """A fresh SQLite session with no seeded data."""
    session = _EmptySession()
    yield session
    session.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_extracted(
    merchant_slug="test-merchant",
    product_price=100.0,
    product_category="skincare",
) -> ExtractedProduct:
    return ExtractedProduct(
        merchant_slug=merchant_slug,
        product_name="Test Moisturiser",
        product_sku="SKU-001",
        product_category=product_category,
        product_price=product_price,
        currency="USD",
        extraction_confidence=0.95,
    )


def _make_true_cost_response(merchant_slug="sephora", product_price=22.0) -> TrueCostResponse:
    return TrueCostResponse(
        merchant_slug=merchant_slug,
        product_price=product_price,
        true_cost=19.80,
        total_savings=2.20,
        total_points_earned=66,
        applied_deals=[],
        available_deals=[],
        confidence=1.0,
        user_tier_name=None,
    )


def _make_product_true_cost_response() -> ProductTrueCostResponse:
    return ProductTrueCostResponse(
        product_url="https://www.sephora.com/product/test",
        product_name="Rare Beauty Soft Pinch Tinted Lip Oil",
        product_sku="P123456",
        product_category="lip",
        merchant_slug="sephora",
        true_cost_result=_make_true_cost_response(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Happy path: valid URL, merchant matched from seeded slug list
# ─────────────────────────────────────────────────────────────────────────────

def test_resolver_happy_path(db):
    extracted = _make_extracted(merchant_slug="test-merchant", product_price=100.0)

    with (
        patch.object(ProductScraper, "scrape", return_value="fake page content") as mock_scrape,
        patch.object(ProductExtractor, "extract", return_value=extracted) as mock_extract,
    ):
        resolver = ProductResolver()
        result = resolver.resolve("https://test.com/product", db)

    # Correct types and values
    assert isinstance(result, ProductTrueCostResponse)
    assert result.merchant_slug == "test-merchant"
    assert result.true_cost_result.product_price == 100.0

    # Extractor was called with known slugs that include "test-merchant"
    _, extract_call_kwargs = mock_extract.call_args
    slugs_arg = mock_extract.call_args[0][2]  # third positional arg
    assert "test-merchant" in slugs_arg, (
        "known_merchant_slugs passed to extractor must contain 'test-merchant'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Scraper failure: ValueError bubbles up
# ─────────────────────────────────────────────────────────────────────────────

def test_resolver_scraper_failure(db):
    with patch.object(ProductScraper, "scrape", side_effect=ValueError("Failed to scrape")):
        resolver = ProductResolver()
        with pytest.raises(ValueError, match="Failed to scrape"):
            resolver.resolve("https://test.com/product", db)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — LLM returns null merchant_slug: descriptive error raised
# ─────────────────────────────────────────────────────────────────────────────

def test_resolver_null_merchant_slug(db):
    extracted = _make_extracted(merchant_slug=None)

    with (
        patch.object(ProductScraper, "scrape", return_value="page"),
        patch.object(ProductExtractor, "extract", return_value=extracted),
    ):
        resolver = ProductResolver()
        with pytest.raises(ValueError, match="Could not match the product page"):
            resolver.resolve("https://test.com/product", db)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — LLM hallucinates a slug not in the list: caught by defensive check
# ─────────────────────────────────────────────────────────────────────────────

def test_resolver_hallucinated_slug(db):
    extracted = _make_extracted(merchant_slug="made-up-merchant")

    with (
        patch.object(ProductScraper, "scrape", return_value="page"),
        patch.object(ProductExtractor, "extract", return_value=extracted),
    ):
        resolver = ProductResolver()
        with pytest.raises(ValueError, match="not in the known merchant list"):
            resolver.resolve("https://test.com/product", db)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — LLM returns invalid JSON: ValueError bubbles from extractor
# ─────────────────────────────────────────────────────────────────────────────

def test_extractor_invalid_json():
    with patch("product_resolver.extractor.ChatClient") as MockChatClient:
        instance = MockChatClient.return_value
        instance.generate.return_value = "this is not json at all"

        extractor = ProductExtractor()
        with pytest.raises(ValueError, match="invalid JSON"):
            extractor.extract(
                page_content="some page content",
                product_url="https://test.com/product",
                known_merchant_slugs=["test-merchant"],
            )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — No merchants in DB: early error before scraping
# ─────────────────────────────────────────────────────────────────────────────

def test_resolver_no_merchants_in_db(empty_db):
    with patch.object(ProductScraper, "scrape") as mock_scrape:
        resolver = ProductResolver()
        with pytest.raises(ValueError, match="No merchants found in database"):
            resolver.resolve("https://test.com/product", empty_db)

        mock_scrape.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — Endpoint integration: POST /api/product-true-cost returns 200
# ─────────────────────────────────────────────────────────────────────────────

def test_endpoint_returns_200(client):
    mock_response = _make_product_true_cost_response()

    with patch(
        "product_resolver.resolver.ProductResolver.resolve",
        return_value=mock_response,
    ):
        response = client.post(
            "/api/product-true-cost",
            json={"product_url": "https://www.sephora.com/product/test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["merchant_slug"] == "sephora"
    assert data["product_name"] == "Rare Beauty Soft Pinch Tinted Lip Oil"
    assert "true_cost_result" in data
    assert data["true_cost_result"]["product_price"] == 22.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — Endpoint: unmatched merchant returns 422
# ─────────────────────────────────────────────────────────────────────────────

def test_endpoint_unmatched_merchant_returns_422(client):
    with patch(
        "product_resolver.resolver.ProductResolver.resolve",
        side_effect=ValueError("Could not match the product page to any known merchant"),
    ):
        response = client.post(
            "/api/product-true-cost",
            json={"product_url": "https://www.sephora.com/product/test"},
        )

    assert response.status_code == 422
    assert "Could not match the product page" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────────
# TEST 9 — user_tier_name is passed through to TrueCostRequest unmodified
# ─────────────────────────────────────────────────────────────────────────────────

def test_user_tier_name_passed_to_engine(db):
    from deal_engine.orchestrator import DealOrchestrator
    from modules.models import Merchant

    extracted = _make_extracted(merchant_slug="test-merchant", product_price=100.0)
    captured_requests = []

    def fake_run(req, session):
        captured_requests.append(req)
        merchant = session.query(Merchant).filter_by(slug="test-merchant").first()
        return {"merchant": merchant, "active_deals": [], "engine_results": {"promo": [], "loyalty": []}}

    with (
        patch.object(ProductScraper, "scrape", return_value="fake page content"),
        patch.object(ProductExtractor, "extract", return_value=extracted),
        patch.object(DealOrchestrator, "run", side_effect=fake_run),
    ):
        resolver = ProductResolver()
        resolver.resolve("https://test.com/product", db, user_tier_name="Gold")

    assert len(captured_requests) == 1
    assert captured_requests[0].user_tier_name == "Gold", (
        "user_tier_name='Gold' must be present on the TrueCostRequest passed to the deal engine"
    )
