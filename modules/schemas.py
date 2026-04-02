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
    name: str = Field(...)
    slug: str = Field(...)
    url: Optional[str] = Field(None)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "name": "Sephora",
                    "slug": "sephora",
                    "url": "https://www.sephora.com"
                },
                {
                    "id": 2,
                    "name": "Ulta Beauty",
                    "slug": "ulta-beauty",
                    "url": "https://www.ulta.com"
                }
            ]
        }
    }

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
    #program: Optional[MerchantProgramDealSchema] = None

class DealStringSchema(DealBaseSchema):
    deal_details: str = Field(..., description="A JSON-formatted string containing the deal's specific logic (e.g., {'points': 4, 'threshold': 100}).")

class DealJsonSchema(DealBaseSchema):
    deal_details: Any = Field(..., description="A JSON object containing the deal's specific logic (e.g., {'points': 4, 'threshold': 100}).")
    tier: Optional[TierSchema] = None
    tier_id: Optional[int] = Field(None, description="ID of the tier, only used for upsert logic to an existing tier. Optional.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "title": "4x points on beauty products",
                    "redemption_method": "AUTOMATIC",
                    "valid_from": "2024-01-01T00:00:00Z",
                    "valid_until": "2024-12-31T23:59:59Z",
                    "promo_code": None,
                    "is_evergreen": False,
                    "is_stackable": True,
                    "deal_type": "MULTIPLIER",
                    "tier_name": "Gold",
                    "deal_details": {
                        "points_multiplier": 4,
                        "applicable_categories": ["makeup", "skincare"]
                    }
                },
                {
                    "id": 2,
                    "title": "$10 off orders over $50",
                    "redemption_method": "PROMO_CODE",
                    "valid_from": "2024-02-01T00:00:00Z",
                    "valid_until": "2024-02-28T23:59:59Z",
                    "promo_code": "SAVE10",
                    "is_evergreen": False,
                    "is_stackable": False,
                    "deal_type": "FLAT_REWARD",
                    "tier_name": None,
                    "deal_details": {
                        "discount_amount": 10,
                        "minimum_order_value": 50
                    }
                }
            ]
        }
    )

class MerchantProgramDealSchema(BaseSchema):

    merchant_id: Optional[int] = Field(None, description="ID of the merchant, only used for upsert logic to an existing merchant. Optional.")
    merchant_name: str
    merchant_slug: str
    program_id: Optional[int] = Field(None, description="ID of the program, only used for upsert logic to an existing program. Optional.")
    program_name: str
    program_description: str = Field(..., description="A brief description of the membership program.")
    tiers: List[TierSchema] = Field(default_factory=list)
    deals: List[DealStringSchema]

class ProgramSchema(BaseSchema):
    program_name: str
    program_description: Optional[str] = Field(None, description="A brief description of the membership program.")
    tiers: List[TierSchema] = Field(default_factory=list)

class MerchantDetailSchema(MerchantSchema):
    # These names must match the relationship names in your SQLAlchemy 'Merchant' model
    deals: List[DealJsonSchema] = []
    programs: List[ProgramSchema] = []

    model_config = {
        "from_attributes": True, # Crucial for SQLAlchemy compatibility
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "name": "Sephora",
                    "slug": "sephora",
                    "url": "https://www.sephora.com",
                    "deals": [
                        {
                            "id": 10,
                            "title": "10% Off",
                            "redemption_method": "AUTOMATIC",
                            "valid_from": "2024-01-01T00:00:00Z",
                            "valid_until": "2024-12-31T23:59:59Z",
                            "promo_code": None,
                            "is_evergreen": True,
                            "is_stackable": False,
                            "deal_type": "PERCENTAGE",
                            "deal_details": {"percent": 10},
                            "tier_name": "Insider"
                        }
                    ],
                    "programs": [
                        {
                            "program_name": "Beauty Insider",
                            "tiers": [
                                {"name": "Insider", "rank": 1},
                                {"name": "VIB", "rank": 2}
                            ],
                        }
                    ]
                }
            ]
        }
    }