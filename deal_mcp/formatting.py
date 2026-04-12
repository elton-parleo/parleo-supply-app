from typing import Any

from product_resolver.schemas import ProductTrueCostResponse


def format_true_cost_response(result: ProductTrueCostResponse) -> dict[str, Any]:
    """
    Convert ProductTrueCostResponse into a flat, Claude-readable dict.
    Avoids deeply nested structures that are hard for Claude to parse.
    """
    tc = result.true_cost_result

    applied = [
        {
            "title": d.deal_title,
            "type": d.deal_type,
            "saving_amount": round(d.saving_amount, 2),
            "saving_pct": round(d.saving_pct * 100, 1),
            "points_earned": d.points_earned,
            "stackable": d.is_stackable,
        }
        for d in tc.applied_deals
    ]

    available = [
        {
            "title": d.deal_title,
            "type": d.deal_type,
            "saving_amount": round(d.saving_amount, 2),
            "reason_not_applied": d.not_applied_reason,
        }
        for d in tc.available_deals
    ]

    return {
        "product_name": result.product_name,
        "product_sku": result.product_sku,
        "product_category": result.product_category,
        "merchant": result.merchant_slug,
        "product_url": result.product_url,
        "base_price": round(tc.product_price, 2),
        "true_cost": round(tc.true_cost, 2),
        "total_savings": round(tc.total_savings, 2),
        "savings_pct": round(
            (tc.total_savings / tc.product_price * 100)
            if tc.product_price else 0,
            1,
        ),
        "total_points_earned": tc.total_points_earned,
        "confidence": tc.confidence,
        "user_tier": tc.user_tier_name,
        "deals_applied": applied,
        "deals_available_but_not_used": available,
        "currency": "USD",
    }


def format_error(message: str, detail: str | None = None) -> dict[str, Any]:
    return {
        "error": True,
        "message": message,
        "detail": detail,
    }
