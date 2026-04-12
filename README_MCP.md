# Honey Deal Finder — MCP Connector

## Overview
Honey Deal Finder helps you find the true cost of any product by
automatically applying all eligible promo codes, category discounts,
and loyalty program perks. Paste a product URL and get back the real
price you'll pay after every available deal.

## Tools

### get_product_true_cost
Calculates the true cost of a product from its URL.
- **Input:** Product page URL, optional membership tier name
- **Output:** Base price, true cost, total savings, deals applied, points earned
- **Read-only:** Yes — this tool never modifies any data

### list_supported_merchants
Returns all merchants supported by the deal engine.
- **Input:** None
- **Output:** List of merchant names, slugs, and URLs
- **Read-only:** Yes

## How to Connect
1. Add this connector URL in Claude: [your Railway MCP URL]/mcp
2. No authentication required for public deal data
3. Optionally provide your membership tier when prompted for loyalty deals

## Supported Merchants
Call the list_supported_merchants tool or visit [your API URL]/api/merchants

## Data & Privacy
- **Data collected:** Product URLs you submit, membership tier names if provided
- **Data retention:** Requests are not stored — each call is stateless
- **Third-party services:** Product pages are crawled via Firecrawl;
  category matching uses OpenAI API
- **No personal data stored:** We do not store user identities, purchase
  history, or loyalty account details
- **Privacy policy:** [your privacy policy URL]

## Rate Limiting
[describe your rate limits here]

## Authentication
No authentication required for v1.
OAuth 2.0 support is planned for v2 to enable automatic loyalty tier
detection without manual input.

## Support
[your support contact or URL]
