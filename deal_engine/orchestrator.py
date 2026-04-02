import logging
from datetime import datetime, timezone
from typing import List

from sqlalchemy.orm import Session, joinedload

from deal_engine.base_engine import BaseEngine
from deal_engine.loyalty_engine import LoyaltyEngine
from deal_engine.promo_engine import PromoEngine
from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal, Merchant

logger = logging.getLogger(__name__)


class DealOrchestrator:

    def __init__(self):
        self.engines: List[BaseEngine] = [PromoEngine(), LoyaltyEngine()]

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

        # STEP 2 — Run each engine; catch all exceptions per engine
        engine_results: dict[str, List[AppliedDealResult]] = {}
        for engine in self.engines:
            try:
                results = engine.evaluate(request, active_deals, db)
                engine_results[engine.name] = results
            except Exception as exc:
                logger.warning("Engine %s failed: %s", engine.name, exc)
                engine_results[engine.name] = []

        # STEP 3 — Return raw results; Calculator handles combination logic
        return {
            "merchant": merchant,
            "active_deals": active_deals,
            "engine_results": engine_results,
        }
