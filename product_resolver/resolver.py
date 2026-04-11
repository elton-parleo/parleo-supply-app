from typing import Optional

from sqlalchemy.orm import Session

from modules.models import Merchant
from product_resolver.scraper import ProductScraper
from product_resolver.extractor import ProductExtractor
from product_resolver.schemas import ProductTrueCostResponse
from deal_engine.schemas import TrueCostRequest
from deal_engine.orchestrator import DealOrchestrator
from deal_engine.calculator import TrueCostCalculator


class ProductResolver:

    def __init__(self):
        self.scraper = ProductScraper()
        self.extractor = ProductExtractor()
        self.orchestrator = DealOrchestrator()
        self.calculator = TrueCostCalculator()

    def resolve(
        self,
        product_url: str,
        db: Session,
        user_tier_name: Optional[str] = None,
    ) -> ProductTrueCostResponse:
        # STEP A — Load all known merchant slugs from the DB
        known_merchant_slugs = [
            row.slug
            for row in db.query(Merchant.slug).order_by(Merchant.slug).all()
        ]
        if not known_merchant_slugs:
            raise ValueError("No merchants found in database.")

        # STEP B — Scrape the page (ValueError bubbles up to the endpoint)
        page_content = self.scraper.scrape(product_url)
        print('111111: ', page_content)

        # STEP C — Extract product details (ValueError bubbles up)
        extracted = self.extractor.extract(
            page_content,
            product_url,
            known_merchant_slugs,
        )
        print('222222: ', extracted)


        # STEP D — Validate that the LLM returned a recognised merchant slug
        if extracted.merchant_slug is None:
            raise ValueError(
                f"Could not match the product page to any known merchant. "
                f"Known merchants are: {', '.join(known_merchant_slugs)}"
            )

        if extracted.merchant_slug not in known_merchant_slugs:
            raise ValueError(
                f"Merchant '{extracted.merchant_slug}' returned by LLM is not "
                f"in the known merchant list: {', '.join(known_merchant_slugs)}"
            )

        # STEP E — Build TrueCostRequest and run the deal engine
        request = TrueCostRequest(
            merchant_slug=extracted.merchant_slug,
            product_price=extracted.product_price,
            product_category=extracted.product_category,
            user_tier_name=user_tier_name,
            user_points_balance=0,
        )
        orch_result = self.orchestrator.run(request, db)
        true_cost_result = self.calculator.calculate(request, orch_result["engine_results"])

        # STEP F — Return the full response
        return ProductTrueCostResponse(
            product_url=product_url,
            product_name=extracted.product_name,
            product_sku=extracted.product_sku,
            product_category=extracted.product_category,
            merchant_slug=extracted.merchant_slug,
            true_cost_result=true_cost_result,
        )
