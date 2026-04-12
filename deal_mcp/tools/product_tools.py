import logging
from typing import Any

from fastmcp import FastMCP

from deal_mcp.lifespan import get_db_session
from deal_mcp.formatting import format_true_cost_response, format_error
from product_resolver.resolver import ProductResolver

logger = logging.getLogger(__name__)


def register_product_tools(mcp: FastMCP) -> None:
    """
    Register all product-related tools on the MCP server instance.
    Called once at server startup.

    v2 OAuth note: when OAuth is implemented, add an `auth_context`
    parameter here to receive the authenticated user's tier and account
    info, eliminating the need for the caller to pass user_tier_name manually.
    """

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "title": "Get product true cost",
        }
    )
    def get_product_true_cost(
        product_url: str,
        user_tier_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Calculate the true cost of a product after applying all eligible
        deals, promo codes, and loyalty perks for the merchant.

        Given a product page URL, this tool:
        1. Crawls the product page to extract name, price, and category
        2. Identifies the merchant and matches it to known merchants
        3. Finds all active deals: promo codes, discounts, loyalty perks
        4. Applies the optimal combination of deals
        5. Returns the true cost and a full savings breakdown

        Use this tool when a user asks:
        - "How much will this actually cost me?"
        - "Are there any deals on this product?"
        - "What's the best price I can get on this?"
        - "Apply my loyalty benefits to this product"
        - "Is there a promo code for this?"

        Args:
            product_url: Full URL of the product page to evaluate.
                         Must be a publicly accessible product page.
                         Examples:
                           https://www.sephora.com/product/xyz
                           https://www.ulta.com/p/abc
            user_tier_name: Optional membership tier name for the user.
                            Used to unlock tier-specific loyalty deals.
                            Examples: "Gold", "VIB", "Platinum", "Insider"
                            If not provided, only public deals are applied.
                            v2: this will be populated automatically via OAuth.

        Returns:
            A dict containing:
            - product_name, merchant, product_category
            - base_price: original price before deals
            - true_cost: final price after best deal combination
            - total_savings: amount saved in dollars
            - savings_pct: percentage saved
            - total_points_earned: loyalty points earned on this purchase
            - deals_applied: list of deals included in the true cost
            - deals_available_but_not_used: valid deals not applied
              (e.g. lost to conflict resolution)
            - confidence: 0.0–1.0 score reflecting extraction reliability

        Errors:
            Returns a dict with error=True and a message field.
            Common errors:
            - Merchant not supported (not in our database)
            - Page could not be scraped (login-required or bot-blocked)
            - Price could not be extracted from the page
        """
        try:
            resolver = ProductResolver()
            with get_db_session() as db:
                result = resolver.resolve(
                    product_url=product_url,
                    db=db,
                    user_tier_name=user_tier_name,
                )
            return format_true_cost_response(result)

        except ValueError as e:
            logger.warning(f"get_product_true_cost ValueError: {e}")
            return format_error(
                message=str(e),
                detail=(
                    "This usually means the merchant is not supported or "
                    "the product page could not be read. Try a direct "
                    "product page URL rather than a search or category page."
                ),
            )
        except Exception as e:
            logger.error(f"get_product_true_cost unexpected error: {e}", exc_info=True)
            return format_error(
                message="An unexpected error occurred while calculating true cost.",
                detail=str(e),
            )

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "title": "List supported merchants",
        }
    )
    def list_supported_merchants() -> dict[str, Any]:
        """
        Returns a list of all merchants supported by the deal engine.

        Use this tool when a user asks:
        - "Which stores do you support?"
        - "Does this work with [merchant name]?"
        - "What merchants are available?"
        - Before calling get_product_true_cost, if unsure whether the
          merchant is supported.

        Returns:
            A dict with a 'merchants' list, each entry containing:
            - name: display name of the merchant
            - slug: internal identifier
            - url: merchant website URL
        """
        try:
            from modules.models import Merchant
            with get_db_session() as db:
                merchants = db.query(Merchant).order_by(Merchant.name).all()
                return {
                    "merchants": [
                        {
                            "name": m.name,
                            "slug": m.slug,
                            "url": m.url,
                        }
                        for m in merchants
                    ],
                    "total": len(merchants),
                }
        except Exception as e:
            logger.error(f"list_supported_merchants error: {e}", exc_info=True)
            return format_error(message="Could not retrieve merchant list.")
