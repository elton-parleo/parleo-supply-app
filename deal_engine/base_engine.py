from abc import ABC, abstractmethod
from typing import List

from sqlalchemy.orm import Session

from deal_engine.schemas import AppliedDealResult, TrueCostRequest
from modules.models import Deal


class BaseEngine(ABC):
    name: str

    @abstractmethod
    def evaluate(
        self,
        request: TrueCostRequest,
        deals: List[Deal],
        db: Session,
    ) -> List[AppliedDealResult]:
        """Return a list of AppliedDealResult. Never raise — catch all exceptions internally."""
        ...
