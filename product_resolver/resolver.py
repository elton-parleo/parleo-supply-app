import logging
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.models import Merchant
from product_resolver.scraper import ProductScraper
from product_resolver.extractor import ProductExtractor
from product_resolver.schemas import ProductTrueCostResponse
from deal_engine.schemas import TrueCostRequest
from deal_engine.orchestrator import DealOrchestrator
from deal_engine.calculator import TrueCostCalculator

logger = logging.getLogger(__name__)


class ProductResolver:

    def __init__(self):
        self.scraper = ProductScraper()
        self.extractor = ProductExtractor()
        self.orchestrator = DealOrchestrator()
        self.calculator = TrueCostCalculator()

    def _match_merchant_from_url(
        self,
        product_url: str,
        db: Session,
    ) -> str | None:
        """
        Parse the domain from product_url and match it against Merchant.url
        in the DB. Returns the merchant slug if found, None otherwise.

        This is the highest-confidence matching method — structural URL
        data is more reliable than LLM inference.

        Examples:
          "https://www.sephora.com/product/..." → domain "sephora.com"
          "https://ulta.com/p/..."              → domain "ulta.com"
        """
        try:
            parsed = urlparse(product_url)
            domain = parsed.netloc.lower().replace("www.", "").strip()

            if not domain:
                return None

            # Match against Merchant.url — contains so that
            # "https://www.sephora.com" in DB matches domain "sephora.com"
            merchant = db.query(Merchant).filter(
                func.lower(Merchant.url).contains(domain)
            ).first()

            if merchant:
                logger.info(
                    "merchant_resolved_from_url",
                    extra={
                        "domain": domain,
                        "merchant_slug": merchant.slug,
                        "product_url": product_url,
                    },
                )
                return merchant.slug

            return None

        except Exception as e:
            logger.warning("_match_merchant_from_url failed: %s", e)
            return None

    def resolve(
        self,
        product_url: str,
        db: Session,
        user_tier_name: Optional[str] = None,
    ) -> ProductTrueCostResponse:
        # STEP A — Try domain match before any LLM call
        url_matched_slug = self._match_merchant_from_url(product_url, db)

        # STEP B — Load all known merchants (slug + domain) from the DB
        merchants = db.query(Merchant.slug, Merchant.url).order_by(Merchant.slug).all()
        known_merchants = []
        for m in merchants:
            domain = ""
            if m.url:
                domain = urlparse(m.url).netloc.lower().replace("www.", "")
            known_merchants.append({"slug": m.slug, "domain": domain})

        if not known_merchants:
            raise ValueError("No merchants found in database.")

        known_merchant_slugs = [m["slug"] for m in known_merchants]

        # STEP C — Scrape the page (ValueError bubbles up to the endpoint)
        page_content = self.scraper.scrape(product_url)

        # STEP D — Extract product details (ValueError bubbles up)
        if url_matched_slug is not None:
            logger.info(
                "merchant_forced_in_extraction",
                extra={
                    "forced_merchant_slug": url_matched_slug,
                    "product_url": product_url,
                },
            )
            extracted = self.extractor.extract(
                page_content,
                product_url,
                known_merchants,
                forced_merchant_slug=url_matched_slug,
            )
        else:
            extracted = self.extractor.extract(
                page_content,
                product_url,
                known_merchants,
                forced_merchant_slug=None,
            )

        # STEP E — Handle None merchant_slug with retry
        if extracted.merchant_slug is None and url_matched_slug is None:
            logger.warning(
                "merchant_slug_null_after_extraction_attempting_retry",
                extra={"product_url": product_url},
            )
            retry_slug = self.extractor._retry_merchant_extraction(
                product_url,
                page_content,
                known_merchants,
            )
            if retry_slug is not None:
                extracted = extracted.model_copy(
                    update={"merchant_slug": retry_slug}
                )
            else:
                logger.error(
                    "merchant_resolution_failed",
                    extra={
                        "product_url": product_url,
                        "known_merchant_count": len(known_merchant_slugs),
                    },
                )
                raise ValueError(
                    f"Could not match the product page to any known merchant "
                    f"after URL matching, LLM extraction, and retry. "
                    f"URL: {product_url}. "
                    f"Known merchants are: "
                    f"{', '.join(known_merchant_slugs)}"
                )

        # STEP F — Defensive slug validation
        if extracted.merchant_slug not in known_merchant_slugs:
            raise ValueError(
                f"Merchant '{extracted.merchant_slug}' returned by LLM is not "
                f"in the known merchant list: {', '.join(known_merchant_slugs)}"
            )

        # STEP G — Build TrueCostRequest and run the deal engine
        request = TrueCostRequest(
            merchant_slug=extracted.merchant_slug,
            product_price=extracted.product_price,
            product_category=extracted.product_category,
            brand=extracted.brand,
            user_tier_name=user_tier_name,
            user_points_balance=0,
        )
        orch_result = self.orchestrator.run(request, db)
        true_cost_result = self.calculator.calculate(request, orch_result["engine_results"])

        # STEP H — Return the full response
        return ProductTrueCostResponse(
            product_url=product_url,
            product_name=extracted.product_name,
            product_sku=extracted.product_sku,
            product_category=extracted.product_category,
            brand=extracted.brand,
            merchant_slug=extracted.merchant_slug,
            true_cost_result=true_cost_result,
        )
