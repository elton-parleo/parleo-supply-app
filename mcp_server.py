import logging
import os

from fastmcp import FastMCP

from deal_mcp.tools.product_tools import register_product_tools

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Deal Finder",
    instructions="""
    You are connected to the Deal Finder, a tool that finds the true
    cost of products after applying all eligible deals, promo codes, and
    loyalty program perks.

    Before calling get_product_true_cost:
    - Make sure you have a full product page URL (not a search page)
    - Ask the user for their membership tier if relevant (e.g. "Are you a
      Gold member or do you have a loyalty account with this store?")
    - If unsure whether a merchant is supported, call list_supported_merchants first

    When presenting results:
    - Lead with the true_cost and total_savings
    - List deals_applied in plain language
    - Mention total_points_earned if > 0
    - Flag low confidence scores (< 0.7) to the user
    - If error=True is returned, explain the issue and suggest alternatives
    """,
)

register_product_tools(mcp)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    logger.info(f"Starting Deal Finder MCP server on port {port}")
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
    )

# v2 OAuth upgrade note:
# To add OAuth, replace mcp.run() with FastMCP's OAuth configuration:
#   from fastmcp.auth import OAuthProvider
#   mcp = FastMCP(name="...", auth=OAuthProvider(...))
# No changes to tool definitions or formatting are needed.
# The auth_context will be injected into tools automatically by FastMCP.
