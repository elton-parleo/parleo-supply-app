import json

from modules.ChatClient import ChatClient
from product_resolver.schemas import ExtractedProduct


class ProductExtractor:

    def _build_system_prompt(self, known_merchant_slugs: list[str]) -> str:
        slugs_formatted = "\n".join(f"  - {s}" for s in known_merchant_slugs)
        return f"""You are a product data extraction assistant.
Given the text content of a product webpage, extract the following fields
and return ONLY a valid JSON object with no extra text, no markdown, no explanation.

You must identify the merchant and select the matching slug from this exact list:
{slugs_formatted}

If the merchant of this product page does not appear in the list above,
set merchant_slug to null.

Return this JSON structure:
{{
  "merchant_slug": "<slug from the list above, or null if not found>",
  "product_name": "<full product name>",
  "product_sku": "<SKU or product ID if present, otherwise null>",
  "product_category": "<product category, e.g. 'skincare', 'lipstick', 'foundation', otherwise null>",
  "product_price": <numeric price as a float, no currency symbol>,
  "currency": "<3-letter currency code, e.g. USD>",
  "extraction_confidence": <float 0.0 to 1.0 reflecting how confident you are in these values>
}}

Rules:
- merchant_slug MUST be an exact string from the list above, or null. Do not invent slugs.
- product_price must be a number (float), not a string.
- If you cannot determine a field with confidence, set it to null.
- Return ONLY the JSON object. No preamble, no explanation, no markdown fences.
"""

    def extract(
        self,
        page_content: str,
        product_url: str,
        known_merchant_slugs: list[str],
    ) -> ExtractedProduct:
        """
        Send page_content to the LLM with the known merchant slug list seeded
        into the system prompt. Parse the returned JSON into ExtractedProduct.
        Raises ValueError if JSON is invalid or if required fields are missing.
        """
        system_prompt = self._build_system_prompt(known_merchant_slugs)
        client = ChatClient(system_prompt=system_prompt)

        user_prompt = (
            f"Product URL: {product_url}\n\n"
            f"Page content:\n{page_content[:12000]}"
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
