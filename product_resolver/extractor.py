import json
import logging
from urllib.parse import urlparse

from modules.ChatClient import ChatClient
from product_resolver.schemas import ExtractedProduct

logger = logging.getLogger(__name__)


class ProductExtractor:

    def _build_system_prompt(
        self,
        known_merchants: list[dict],
        forced_merchant_slug: str | None = None,
    ) -> str:
        merchant_lines = "\n".join(
            f"  - {m['slug']} ({m['domain']})"
            for m in known_merchants
        )

        if forced_merchant_slug is not None:
            merchant_section = (
                f'The merchant for this product has already been identified as:\n'
                f'"{forced_merchant_slug}"\n\n'
                f'Set merchant_slug to exactly "{forced_merchant_slug}" in your response.\n'
                f'Do not attempt to identify the merchant yourself.\n'
            )
        else:
            merchant_section = (
                f"You must identify the merchant and select the matching slug from\n"
                f"this exact list (slug and its domain shown for reference):\n"
                f"{merchant_lines}\n\n"
                f"To identify the merchant:\n"
                f"  1. First check the product URL domain — it is the most reliable signal.\n"
                f"  2. If the URL domain matches a merchant domain in the list, use that slug.\n"
                f"  3. If unsure from the URL, check the page content for the merchant name.\n\n"
                f"If the merchant does not appear in the list above, set merchant_slug to null.\n"
                f"However, if you are at least 70% confident about the merchant match,\n"
                f"return the slug — a best guess from the known list is better than null\n"
                f"for recognised merchants.\n"
            )

        return f"""You are a product data extraction assistant.
Given the text content of a product webpage, extract the following fields
and return ONLY a valid JSON object with no extra text, no markdown, no explanation.

{merchant_section}
Return this JSON structure:
{{
  "merchant_slug": "<slug from the list above, or null if not found>",
  "brand": "<brand name of the product, e.g. 'MAC', 'NARS', null if unknown>",
  "product_name": "<full product name>",
  "product_sku": "<SKU or product ID if present, otherwise null>",
  "product_category": "<product category, e.g. 'skincare', 'lipstick', 'foundation', otherwise null>",
  "product_price": <numeric price as a float, no currency symbol>,
  "currency": "<3-letter currency code, e.g. USD>",
  "extraction_confidence": <float 0.0 to 1.0 reflecting how confident you are in these values>
}}

Rules:
- merchant_slug MUST be an exact string from the list above, or null. Do not invent slugs.
- brand should be the manufacturer or product line brand, not the merchant/retailer name.
  For example, on a Sephora page selling MAC lipstick, brand is "MAC", not "Sephora".
- If brand cannot be determined, set to null.
- product_price must be a number (float), not a string.
- If you cannot determine a field with confidence, set it to null.
- Return ONLY the JSON object. No preamble, no explanation, no markdown fences.
"""

    def extract(
        self,
        page_content: str,
        product_url: str,
        known_merchants: list[dict],
        forced_merchant_slug: str | None = None,
    ) -> ExtractedProduct:
        """
        Send page_content to the LLM with the known merchant list seeded
        into the system prompt. Parse the returned JSON into ExtractedProduct.
        Raises ValueError if JSON is invalid or if required fields are missing.

        known_merchants: list of {"slug": str, "domain": str} dicts.
        forced_merchant_slug: if provided, skip LLM merchant identification and
            instruct the model to use this slug directly.
        """
        system_prompt = self._build_system_prompt(known_merchants, forced_merchant_slug)
        client = ChatClient(system_prompt=system_prompt)

        domain = urlparse(product_url).netloc.lower().replace("www.", "")

        user_prompt = (
            f"Product URL: {product_url}\n"
            f"URL domain: {domain}\n\n"
            f"Use the URL domain to identify the merchant from the list "
            f"in your instructions.\n\n"
            f"Page content (use for product name, price, category, brand "
            f"— not for merchant identification):\n"
            f"{page_content}"
        )

        response_text = client.generate(user_prompt=user_prompt)

        try:
            parsed = json.loads(response_text)
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"LLM returned invalid JSON: {response_text}")

        # Required field validation
        if "product_price" not in parsed or parsed["product_price"] is None:
            raise ValueError(
                f"LLM response missing required field 'product_price': {parsed}"
            )
        if "merchant_slug" not in parsed:
            raise ValueError(
                f"LLM response missing required field 'merchant_slug': {parsed}"
            )

        return ExtractedProduct(**parsed)

    def _retry_merchant_extraction(
        self,
        product_url: str,
        page_content: str,
        known_merchants: list[dict],
    ) -> str | None:
        """
        Focused retry when the main extraction returned merchant_slug=None.
        Uses a simpler prompt with a single-field output to maximise
        reliability. Returns the matched slug string or None.
        Never raises — returns None on any failure.
        """
        try:
            merchant_lines = "\n".join(
                f"  - {m['slug']} ({m['domain']})"
                for m in known_merchants
            )

            domain = urlparse(product_url).netloc.lower().replace("www.", "")

            system_prompt = (
                "You are a merchant identification assistant.\n"
                "Given a product URL and a list of known merchants with their domains,\n"
                "identify which merchant slug matches the URL.\n\n"
                "Return ONLY the slug string — no JSON, no explanation, no punctuation.\n"
                "If none of the merchants match, return the exact word: null\n"
            )

            user_prompt = (
                f"Product URL: {product_url}\n"
                f"URL domain: {domain}\n\n"
                f"Known merchants:\n{merchant_lines}\n\n"
                f"Which slug matches this URL? Return only the slug or null."
            )

            client = ChatClient(system_prompt=system_prompt)
            response_text = client.generate(user_prompt=user_prompt)

            result = response_text.strip().lower()

            # Validate the returned slug is in the known list
            known_slugs = [m["slug"] for m in known_merchants]
            if result == "null" or result not in known_slugs:
                logger.warning(
                    "_retry_merchant_extraction: LLM returned '%s' "
                    "which is not in known slugs",
                    result,
                )
                return None

            logger.info(
                "merchant_resolved_by_retry",
                extra={
                    "product_url": product_url,
                    "merchant_slug": result,
                },
            )
            return result

        except Exception as e:
            logger.warning("_retry_merchant_extraction failed: %s", e)
            return None
