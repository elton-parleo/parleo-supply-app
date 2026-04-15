from pydantic import BaseModel, ConfigDict, HttpUrl
from typing import Optional

from deal_engine.schemas import TrueCostResponse


class ProductResolverRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_url: HttpUrl
    user_tier_name: Optional[str] = None   # e.g. "Gold", "VIB", "Insider"


class ExtractedProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Optional[str] because the LLM is instructed to return null when the
    # merchant is not in the known-slug list; the resolver validates this.
    merchant_slug: Optional[str] = None
    brand: Optional[str] = None
    # e.g. "MAC", "NARS", "Rare Beauty", "Charlotte Tilbury"
    product_name: str
    product_sku: Optional[str] = None
    product_category: Optional[str] = None
    product_price: float
    currency: str = "USD"
    extraction_confidence: float


class ProductTrueCostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_url: str
    product_name: str
    product_sku: Optional[str]
    product_category: Optional[str]
    brand: Optional[str] = None
    merchant_slug: str
    true_cost_result: TrueCostResponse
