from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from modules.schemas import DealJsonSchema, DealType, RedemptionType, MerchantDetailSchema  # noqa: F401


class TrueCostRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merchant_slug: str
    product_price: float
    product_category: Optional[str] = None
    user_tier_name: Optional[str] = None
    user_points_balance: Optional[int] = 0


class AppliedDealResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deal_id: int
    deal_title: str
    deal_type: DealType
    redemption_method: RedemptionType
    saving_amount: float
    saving_pct: float
    points_earned: Optional[int] = None
    is_stackable: bool
    applied: bool
    not_applied_reason: Optional[str] = None


class TrueCostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merchant_slug: str
    product_price: float
    true_cost: float
    total_savings: float
    total_points_earned: int
    applied_deals: List[AppliedDealResult]
    available_deals: List[AppliedDealResult]
    confidence: float
    user_tier_name: Optional[str]
