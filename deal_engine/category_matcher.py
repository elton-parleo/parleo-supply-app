import json
import logging

from modules.ChatClient import ChatClient

logger = logging.getLogger(__name__)

CATEGORY_MATCH_SYSTEM_PROMPT = """You are a product category classification assistant.

Given a product_category string and a list of deal_categories, determine which (if any)
of the deal_categories semantically match the product.

Rules:
- A match exists when the product is plausibly a member of, or closely related to, a
  deal category (e.g. "moisturiser" matches "skincare"; "sneakers" matches "footwear").
- Exact string equality is not required — use semantic understanding.
- A deal category that is a broad parent of the product always matches
  (e.g. "electronics" matches "wireless headphones").
- A deal category that is a narrow child does NOT match a broader product category
  (e.g. "gaming mice" does NOT match "electronics").
- If deal_categories is empty, return an empty matches list.
- If product_category is empty or null, return an empty matches list.

You must respond with valid JSON only — no markdown, no explanation.

Response format:
{
  "matches": ["<matching_deal_category>", ...],
  "reasoning": "<one-sentence explanation>"
}

Examples:

User: product_category: "moisturiser"\ndeal_categories: ["skincare", "haircare"]
Assistant: {"matches": ["skincare"], "reasoning": "A moisturiser is a skincare product."}

User: product_category: "wireless headphones"\ndeal_categories: ["electronics", "gaming mice"]
Assistant: {"matches": ["electronics"], "reasoning": "Wireless headphones are an electronics product; gaming mice is too narrow."}

User: product_category: "running shoes"\ndeal_categories: ["apparel"]
Assistant: {"matches": [], "reasoning": "Running shoes are footwear, not apparel."}

User: product_category: "lipstick"\ndeal_categories: ["skincare"]
Assistant: {"matches": [], "reasoning": "Lipstick is a makeup product, not skincare."}
"""


class CategoryMatcher:
    def __init__(self):
        self.client = ChatClient(system_prompt=CATEGORY_MATCH_SYSTEM_PROMPT)

    def matches(self, product_category: str, scope_categories: list[str]) -> bool:
        """Return True when the product semantically matches at least one scope category.

        Returns False on any error — never raises.
        """
        try:
            return self._llm_match(product_category, scope_categories)
        except Exception as e:
            logger.warning(
                "CategoryMatcher.matches failed for product='%s' scope=%s: %s",
                product_category,
                scope_categories,
                e,
            )
            return False

    def _llm_match(self, product_category: str, scope_categories: list[str]) -> bool:
        try:
            user_prompt = (
                f'product_category: "{product_category}"\n'
                f"deal_categories: {json.dumps(scope_categories)}"
            )
            response_text = self.client.generate(user_prompt=user_prompt)
            parsed = json.loads(response_text)
            matches = parsed.get("matches", [])
            logger.debug(
                "category_match_result",
                extra={
                    "product_category": product_category,
                    "scope_categories": scope_categories,
                    "matches": matches,
                    "reasoning": parsed.get("reasoning", ""),
                },
            )
            return len(matches) > 0
        except json.JSONDecodeError as e:
            logger.warning(
                "CategoryMatcher: LLM returned invalid JSON for "
                "product='%s' scope=%s: %s",
                product_category,
                scope_categories,
                e,
            )
            return False
        except Exception as e:
            logger.warning(
                "CategoryMatcher: unexpected error for "
                "product='%s' scope=%s: %s",
                product_category,
                scope_categories,
                e,
            )
            return False

    # v2 upgrade point — implement _taxonomy_match in next iteration
    # def _taxonomy_match(self, product_category, scope_categories) -> bool | None:
    #     raise NotImplementedError
