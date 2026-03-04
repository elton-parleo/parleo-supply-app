from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime

class MerchantSchema(BaseModel):
    id: int
    name: str
    url: Optional[str] = None
    
    # This is the magic line for Pydantic v2
    model_config = ConfigDict(from_attributes=True)

class ProgramSchema(BaseModel):
    id: int
    program_name: str
    
    model_config = ConfigDict(from_attributes=True)

class DealSchema(BaseModel):
    id: int
    promo_code: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    deal_details: dict[str, Any]
    
    # Tell Pydantic these are nested models, not raw objects
    merchant: MerchantSchema
    program: Optional[ProgramSchema] = None
    
    model_config = ConfigDict(from_attributes=True)