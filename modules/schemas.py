from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class DealType(str, Enum):
    MULTIPLIER = "MULTIPLIER"
    FLAT_REWARD = "FLAT_REWARD"
    DISCOUNT = "DISCOUNT"
    SHIPPING = "SHIPPING"
    GIFT = "GIFT"

class RedemptionType(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    PROMO_CODE = "PROMO_CODE"
    ACTIVATED = "ACTIVATED"

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid')

class MerchantSchema(BaseSchema):
    id: int
    name: str
    slug: str
    url: Optional[str] = None

class TierSchema(BaseSchema):
    id: Optional[int] = Field(None, description="ID of the tier, only used for upsert logic to an existing tier. Optional.")
    name: str
    rank: int = Field(..., description="Hierarchy level, e.g., 1 for base, 2 for silver, etc.")
    
class DealBaseSchema(BaseSchema):
    id: Optional[int] = Field(None, description="ID of the deal, only used for upsert logic to an existing deal. Optional.")
    title: str = Field(..., description="The name or short description of the deal")
    redemption_method: RedemptionType
    valid_from: Optional[datetime] = Field(...)
    valid_until: Optional[datetime] = Field(...)
    promo_code: Optional[str] = Field(...)
    is_evergreen: bool = Field(False, description="True if the deal is always active")
    is_stackable: bool = Field(True, description="True if the deal can be combined with others")
    deal_type: DealType = Field(...)
    tier_name: Optional[str] = Field(None, description="The name of the tier this deal belongs to, if applicable")

    # Tell Pydantic these are nested models, not raw objects
    #merchant: MerchantSchema
    #program: Optional[ProgramSchema] = None

class DealStringSchema(DealBaseSchema):
    deal_details: str = Field(..., description="A JSON-formatted string containing the deal's specific logic (e.g., {'points': 4, 'threshold': 100}).")

class DealJsonSchema(DealBaseSchema):
    deal_details: Any = Field(..., description="A JSON object containing the deal's specific logic (e.g., {'points': 4, 'threshold': 100}).")

class ProgramSchema(BaseSchema):
    merchant_id: Optional[int] = Field(None, description="ID of the merchant, only used for upsert logic to an existing merchant. Optional.")
    merchant_name: str
    merchant_slug: str
    program_id: Optional[int] = Field(None, description="ID of the program, only used for upsert logic to an existing program. Optional.")
    program_name: str
    tiers: List[TierSchema] = Field(default_factory=list)
    deals: List[DealStringSchema]