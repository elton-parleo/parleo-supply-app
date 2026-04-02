from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from datetime import datetime, timezone
from modules import models, schemas, database
from fastapi.middleware.cors import CORSMiddleware
from deal_engine.schemas import TrueCostRequest, TrueCostResponse
from deal_engine.orchestrator import DealOrchestrator
from deal_engine.calculator import TrueCostCalculator

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = database.Session()
    try:
        yield db
    finally:
        db.close()

def create_response_example(data):
    return {
                200: {
                    "content": {
                        "application/json": {
                            "example": data
                        }
                    }
                }
            }

@app.get("/api/deals", response_model=List[schemas.DealJsonSchema], 
         summary="Retrieves a list of deals and promotions", 
         description="Returns a paginated list of all deals across merchants. Use this endpoint for bulk retrieval or indexing, not for search.",
         responses=create_response_example(schemas.DealJsonSchema.model_config["json_schema_extra"]["examples"]))
def get_deals(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    deals = db.query(models.Deal).offset(skip).limit(limit).all()
    return deals

@app.get("/api/deals/search", response_model=List[schemas.DealJsonSchema], 
         summary="Searches for deals and promotions based on category or merchant", 
         description="Searches for deals based on category or merchant ID.",
         responses=create_response_example(schemas.DealJsonSchema.model_config["json_schema_extra"]["examples"]))
def search_deals(category: str = None, merchant_id: int = None, db: Session = Depends(get_db)):
    query = db.query(models.Deal)
    if merchant_id:
        query = query.filter(models.Deal.merchant_id == merchant_id)
    if category:
        # Assumes PostgreSQL JSONB indexing
        query = query.filter(models.Deal.deal_details['category'].astext == category)
    return query.all()

@app.api_route("/api/deals/active", 
         methods=["GET", "HEAD"],
         response_model=List[schemas.DealJsonSchema], 
         summary="Retrieves a list of active deals and promotions", 
         description="Returns a list of currently active deals across merchants. A deal is considered active if the current date is between valid_from and valid_until, or if it is marked as evergreen.",
         responses=create_response_example(schemas.DealJsonSchema.model_config["json_schema_extra"]["examples"]))
def get_active_deals(limit: int = 50, db: Session = Depends(get_db)):
    # Get current timestamp in ISO format
    now = datetime.now(timezone.utc)
    
    # Query for deals where valid_until >= now
    # We also check valid_from to ensure the deal has actually started
    active_deals = db.query(models.Deal).filter(
        (models.Deal.valid_until >= now) & (models.Deal.valid_from <= now) |
        (models.Deal.is_evergreen == True)
    ).limit(limit).all()
    
    return active_deals

@app.get("/api/deals/{deal_id}", response_model=schemas.DealJsonSchema, 
         summary="Retrieves a specific deal or promotion", 
         description="Retrieves a specific deal by its ID. Use this endpoint for detailed information about a single deal, not for search or listing.",
         responses=create_response_example(schemas.DealJsonSchema.model_config["json_schema_extra"]["examples"][0]))
def get_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(models.Deal).filter(models.Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal

@app.get("/api/merchants/programs", #response_model=List[schemas.MerchantDetailSchema], 
         summary="Retrieves all merchants with their loyalty programs and deals", 
         description="Returns a list of all merchants, each with their associated loyalty programs, tiers, and deals. Use this endpoint for bulk retrieval or indexing, not for search.",
         #responses=create_response_example(schemas.MerchantDetailSchema.model_config["json_schema_extra"]["examples"])
         )
def get_merchants_with_programs(db: Session = Depends(get_db)):
    merchants = db.query(models.Merchant).options(
        joinedload(models.Merchant.deals).joinedload(models.Deal.tier),
        joinedload(models.Merchant.programs).joinedload(models.MembershipProgram.tiers)
    ).all()
    return merchants

@app.get("/api/merchants/{merchant_slug}", response_model=schemas.MerchantDetailSchema,
         summary="Retrieves a specific merchant", 
         description="Retrieves a specific merchant by its slug, including all associated deals and programs. Use this endpoint for detailed information about a single merchant, not for search or listing.",
         responses=create_response_example(schemas.MerchantDetailSchema.model_config["json_schema_extra"]["examples"][0])
         )
def get_merchant_by_slug(merchant_slug: str, db: Session = Depends(get_db)):
    # We use joinedload to eagerly fetch deals, programs, and tiers in one query
    merchant = db.query(models.Merchant).options(
        joinedload(models.Merchant.deals).joinedload(models.Deal.tier),
        joinedload(models.Merchant.programs).joinedload(models.MembershipProgram.tiers)
    ).filter(models.Merchant.slug == merchant_slug).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
        
    return merchant

@app.post(
    "/api/deals/true-cost",
    response_model=TrueCostResponse,
    summary="Calculate the true cost of a cart after applying all eligible deals",
    description=(
        "Given a merchant and product price, finds all active deals for that merchant, "
        "applies the best combination of promo and loyalty deals, and returns the "
        "true cost after savings. Pass user_tier_name to include loyalty perks. "
        "Pass product_category to enable category-specific deal matching.\n\n"
        "**Example request:**\n"
        "```json\n"
        '{"merchant_slug": "sephora", "product_price": 120.00, "user_tier_name": "VIB", '
        '"user_points_balance": 500, "product_category": "skincare"}\n'
        "```"
    ),
    responses=create_response_example({
        "merchant_slug": "sephora",
        "product_price": 120.00,
        "true_cost": 98.00,
        "total_savings": 22.00,
        "total_points_earned": 490,
        "confidence": 1.0,
        "user_tier_name": "VIB",
        "applied_deals": [
            {
                "deal_id": 2,
                "deal_title": "$10 off orders over $50",
                "deal_type": "FLAT_REWARD",
                "redemption_method": "PROMO_CODE",
                "saving_amount": 10.00,
                "saving_pct": 0.0833,
                "points_earned": None,
                "is_stackable": False,
                "applied": True,
                "not_applied_reason": None,
            },
            {
                "deal_id": 5,
                "deal_title": "4x points on all purchases",
                "deal_type": "MULTIPLIER",
                "redemption_method": "AUTOMATIC",
                "saving_amount": 0.0,
                "saving_pct": 0.0,
                "points_earned": 480,
                "is_stackable": True,
                "applied": True,
                "not_applied_reason": None,
            },
        ],
        "available_deals": [],
    }),
)
def calculate_true_cost(
    request: TrueCostRequest,
    db: Session = Depends(get_db),
):
    orchestrator = DealOrchestrator()
    calculator = TrueCostCalculator()

    orch_result = orchestrator.run(request, db)

    if orch_result["merchant"] is None:
        raise HTTPException(status_code=404, detail=f"Merchant '{request.merchant_slug}' not found")

    response = calculator.calculate(request, orch_result["engine_results"])
    return response


@app.get("/api/merchants", response_model=List[schemas.MerchantSchema],
         summary="Retrieves a list of all merchants", 
         description="Returns a list of all merchants. Use this endpoint for bulk retrieval or indexing, not for search.",
         responses=create_response_example([schemas.MerchantSchema.model_config["json_schema_extra"]["examples"]]))
def get_all_merchants(db: Session = Depends(get_db)):
    return db.query(models.Merchant).all()