import logging
from datetime import datetime, timezone
from typing import List

from sqlalchemy.orm import Session, joinedload

from deal_engine.base_engine import BaseEngine
from deal_engine.loyalty_discount_engine import LoyaltyDiscountEngine
from deal_engine.loyalty_points_engine import LoyaltyPointsEngine
from deal_engine.promo_engine import PromoEngine
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal, Merchant
from modules.schemas import DealType

logger = logging.getLogger(__name__)


class DealOrchestrator:

    def __init__(self):
        # Stage 1: price-reduction engines — run first with original product_price
        self.stage_1_engines: List[BaseEngine] = [
            PromoEngine(),
            LoyaltyDiscountEngine(),   # member discounts reduce price in stage 1
        ]
        # Stage 2: price-dependent engines — run with the preliminary discounted price
        self.stage_2_engines: List[BaseEngine] = [
            LoyaltyPointsEngine(),     # points calculated on post-discount price
        ]

    def _compute_preliminary_price(
        self,
        product_price: float,
        stage_1_results: List[AppliedDealResult],
    ) -> float:
        """
        Compute a best-estimate discounted price from stage 1 results.
        Used ONLY to give stage 2 engines a better price basis.
        The calculator remains the authoritative source of true_cost.

        Mirrors the calculator's conflict resolution approach:
          Option 1: best single non-stackable deal (alone, nothing stacked)
          Option 2: all stackable deals applied cumulatively
        Returns the option that yields the lowest price.

        If stage_1_results is empty: returns product_price unchanged.
        On any exception: logs warning, returns product_price unchanged.
        """
        try:
            if not stage_1_results:
                return product_price

            # STEP 1 — Filter to deals that actually reduce price
            discount_results = [
                d for d in stage_1_results
                if d.saving_amount > 0
            ]

            if not discount_results:
                return product_price

            non_stackable = [d for d in discount_results if not d.is_stackable]
            stackable = [d for d in discount_results if d.is_stackable]

            # STEP 2 — Option 1: best non-stackable deal alone
            if non_stackable:
                best = max(non_stackable, key=lambda d: d.saving_amount)
                option_1_price = max(0.0, product_price - best.saving_amount)
            else:
                option_1_price = None

            # STEP 3 — Option 2: stackable deals applied cumulatively
            if stackable:
                running_price = product_price
                for deal in sorted(stackable, key=lambda d: d.saving_amount, reverse=True):
                    saving = deal.saving_pct * running_price
                    running_price = max(0.0, running_price - saving)
                option_2_price = running_price
            else:
                option_2_price = None

            # STEP 4 — Pick the option that yields the lowest price
            candidates = [p for p in [option_1_price, option_2_price] if p is not None]

            if not candidates:
                return product_price

            return min(candidates)

        except Exception as e:
            logger.warning(
                "_compute_preliminary_price failed: %s. Returning original product_price.",
                e,
            )
            return product_price

    def run(self, request: TrueCostRequest, db: Session) -> dict:
        """
        Returns a dict with keys:
          merchant:       Merchant ORM object (or None if not found)
          active_deals:   List[Deal]
          engine_results: dict[str, List[AppliedDealResult]]  keyed by engine name
        """
        # STEP 1 — Load merchant and active deals
        merchant = db.query(Merchant).filter(Merchant.slug == request.merchant_slug).first()
        if merchant is None:
            return {"merchant": None, "active_deals": [], "engine_results": {}}

        now = datetime.now(timezone.utc)
        active_deals: List[Deal] = (
            db.query(Deal)
            .filter(Deal.merchant_id == merchant.id)
            .filter(
                ((Deal.valid_until >= now) & (Deal.valid_from <= now))
                | (Deal.is_evergreen == True)  # noqa: E712
            )
            .options(joinedload(Deal.tier))
            .all()
        )
        
        # STEP 2 — Run stage 1 engines (price-reduction engines)
        engine_results: dict[str, List[AppliedDealResult]] = {}
        stage_1_results: List[AppliedDealResult] = []
        engines_failed: List[str] = []

        for engine in self.stage_1_engines:
            try:
                results = engine.evaluate(request, active_deals, db)
                engine_results[engine.name] = results
                stage_1_results.extend(results)
            except Exception as exc:
                logger.warning("Stage 1 engine %s failed: %s", engine.name, exc)
                engine_results[engine.name] = []
                engines_failed.append(engine.name)

        # STEP 3 — Compute preliminary discounted price for stage 2
        preliminary_discounted_price = self._compute_preliminary_price(
            request.product_price,
            stage_1_results,
        )
        logger.debug(
            "preliminary_discounted_price computed",
            extra={
                "original_price": request.product_price,
                "preliminary_price": preliminary_discounted_price,
                "stage_1_deal_count": len(stage_1_results),
            },
        )
        logger.info(
            "stage_1_complete",
            extra={
                "engines": [e.name for e in self.stage_1_engines],
                "deal_count": len(stage_1_results),
                "preliminary_price": preliminary_discounted_price,
                "original_price": request.product_price,
            },
        )

        # STEP 4 — Build stage 2 request with updated product_price
        stage_2_request = request.model_copy(
            update={"product_price": preliminary_discounted_price}
        )

        # STEP 5 — Run stage 2 engines using the preliminary discounted price
        stage_2_results: List[AppliedDealResult] = []

        for engine in self.stage_2_engines:
            try:
                results = engine.evaluate(stage_2_request, active_deals, db)
                engine_results[engine.name] = results
                stage_2_results.extend(results)
            except Exception as exc:
                logger.warning("Stage 2 engine %s failed: %s", engine.name, exc)
                engine_results[engine.name] = []
                engines_failed.append(engine.name)

        logger.info(
            "stage_2_complete",
            extra={
                "engines": [e.name for e in self.stage_2_engines],
                "deal_count": len(stage_2_results),
                "price_used": preliminary_discounted_price,
            },
        )

        # STEP 6 — Return results; Calculator handles combination and true_cost
        return {
            "merchant": merchant,
            "active_deals": active_deals,
            "engine_results": engine_results,
        }
