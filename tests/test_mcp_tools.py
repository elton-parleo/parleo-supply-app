"""
MCP tool tests.

All tests are fully offline — no real HTTP, DB, or LLM calls are made.
Tools are extracted from a fresh FastMCP instance and called directly.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from fastmcp import FastMCP

from deal_mcp.tools.product_tools import register_product_tools
from deal_mcp.formatting import format_true_cost_response, format_error


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_mcp() -> FastMCP:
    """Return a fresh FastMCP instance with product tools registered."""
    mcp = FastMCP(name="test-server")
    register_product_tools(mcp)
    return mcp


def _get_tool_fn(mcp: FastMCP, name: str):
    """Extract the raw callable registered under *name* from the MCP instance.

    Uses the public async get_tool() API (FastMCP 2.x) and returns .fn,
    which is the original unwrapped Python function.
    """
    tool = asyncio.run(mcp.get_tool(name))
    return tool.fn


def _make_product_response(
    product_price: float = 100.0,
    true_cost: float = 80.0,
    total_savings: float = 20.0,
) -> MagicMock:
    """Build a minimal ProductTrueCostResponse mock."""
    applied_deal = MagicMock()
    applied_deal.deal_title = "10% off"
    applied_deal.deal_type = "DISCOUNT"
    applied_deal.saving_amount = 20.0
    applied_deal.saving_pct = 0.2
    applied_deal.points_earned = None
    applied_deal.is_stackable = True

    tc = MagicMock()
    tc.product_price = product_price
    tc.true_cost = true_cost
    tc.total_savings = total_savings
    tc.total_points_earned = 0
    tc.applied_deals = [applied_deal]
    tc.available_deals = []
    tc.confidence = 0.95
    tc.user_tier_name = None

    result = MagicMock()
    result.product_name = "Fancy Cream"
    result.product_sku = "SKU-001"
    result.product_category = "skincare"
    result.merchant_slug = "sephora"
    result.product_url = "https://www.sephora.com/product/xyz"
    result.true_cost_result = tc
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — get_product_true_cost: happy path returns formatted dict
# ─────────────────────────────────────────────────────────────────────────────

def test_get_product_true_cost_happy_path():
    mcp = _make_mcp()
    tool_fn = _get_tool_fn(mcp, "get_product_true_cost")
    mock_result = _make_product_response()

    with patch("deal_mcp.tools.product_tools.ProductResolver") as MockResolver, \
         patch("deal_mcp.tools.product_tools.get_db_session") as mock_db_ctx:

        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
        MockResolver.return_value.resolve.return_value = mock_result

        result = tool_fn(product_url="https://www.sephora.com/product/xyz")

    assert isinstance(result["true_cost"], float), "true_cost must be a float"
    assert "error" not in result, "Happy path must not contain an error key"
    assert isinstance(result["deals_applied"], list), "deals_applied must be a list"
    assert result["true_cost"] == 80.0
    assert result["total_savings"] == 20.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — get_product_true_cost: unsupported merchant raises ValueError
# ─────────────────────────────────────────────────────────────────────────────

def test_get_product_true_cost_unsupported_merchant():
    mcp = _make_mcp()
    tool_fn = _get_tool_fn(mcp, "get_product_true_cost")

    with patch("deal_mcp.tools.product_tools.ProductResolver") as MockResolver, \
         patch("deal_mcp.tools.product_tools.get_db_session") as mock_db_ctx:

        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
        MockResolver.return_value.resolve.side_effect = ValueError(
            "does not match any merchant"
        )

        result = tool_fn(product_url="https://www.unknown-store.com/product/xyz")

    assert result["error"] is True, "ValueError must return error=True"
    assert "does not match any merchant" in result["message"]


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — get_product_true_cost: unexpected exception returns error dict
# ─────────────────────────────────────────────────────────────────────────────

def test_get_product_true_cost_unexpected_exception():
    mcp = _make_mcp()
    tool_fn = _get_tool_fn(mcp, "get_product_true_cost")

    with patch("deal_mcp.tools.product_tools.ProductResolver") as MockResolver, \
         patch("deal_mcp.tools.product_tools.get_db_session") as mock_db_ctx:

        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
        MockResolver.return_value.resolve.side_effect = Exception("connection timeout")

        result = tool_fn(product_url="https://www.sephora.com/product/xyz")

    assert result["error"] is True, "Unexpected exception must return error=True"
    assert "connection timeout" in result.get("detail", "")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — list_supported_merchants: returns merchant list
# ─────────────────────────────────────────────────────────────────────────────

def test_list_supported_merchants_happy_path():
    mcp = _make_mcp()
    tool_fn = _get_tool_fn(mcp, "list_supported_merchants")

    merchant_a = MagicMock()
    merchant_a.name = "Sephora"
    merchant_a.slug = "sephora"
    merchant_a.url = "https://www.sephora.com"

    merchant_b = MagicMock()
    merchant_b.name = "Ulta Beauty"
    merchant_b.slug = "ulta"
    merchant_b.url = "https://www.ulta.com"

    mock_db = MagicMock()
    mock_db.query.return_value.order_by.return_value.all.return_value = [
        merchant_a, merchant_b
    ]

    with patch("deal_mcp.tools.product_tools.get_db_session") as mock_db_ctx:
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = tool_fn()

    assert len(result["merchants"]) == 2, "Two merchants must be returned"
    assert result["total"] == 2
    slugs = {m["slug"] for m in result["merchants"]}
    assert slugs == {"sephora", "ulta"}


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — list_supported_merchants: DB error returns error dict
# ─────────────────────────────────────────────────────────────────────────────

def test_list_supported_merchants_db_error():
    mcp = _make_mcp()
    tool_fn = _get_tool_fn(mcp, "list_supported_merchants")

    with patch("deal_mcp.tools.product_tools.get_db_session") as mock_db_ctx:
        mock_db_ctx.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB unavailable")
        )
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = tool_fn()

    assert result["error"] is True, "DB error must return error=True"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — format_true_cost_response: savings_pct computed correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_format_true_cost_response_savings_pct():
    mock_response = _make_product_response(
        product_price=100.0,
        true_cost=80.0,
        total_savings=20.0,
    )

    result = format_true_cost_response(mock_response)

    assert result["savings_pct"] == 20.0, (
        "savings_pct must be 20.0 for total_savings=20 on product_price=100"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — format_true_cost_response: zero product_price does not divide by zero
# ─────────────────────────────────────────────────────────────────────────────

def test_format_true_cost_response_zero_price():
    mock_response = _make_product_response(
        product_price=0.0,
        true_cost=0.0,
        total_savings=0.0,
    )

    result = format_true_cost_response(mock_response)

    assert result["savings_pct"] == 0, (
        "savings_pct must be 0 when product_price is 0 (no ZeroDivisionError)"
    )
