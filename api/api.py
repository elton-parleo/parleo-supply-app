from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from datetime import datetime, timezone
from modules import models, schemas, database
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://parleo.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = database.Session()
    try:
        yield db
    finally:
        db.close()

@app.get("/api/deals", response_model=List[schemas.DealSchema])
def get_deals(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    deals = db.query(models.Deal).offset(skip).limit(limit).all()
    return deals

@app.get("/api/deals/search", response_model=List[schemas.DealSchema])
def search_deals(category: str = None, merchant_id: int = None, db: Session = Depends(get_db)):
    query = db.query(models.Deal)
    if merchant_id:
        query = query.filter(models.Deal.merchant_id == merchant_id)
    if category:
        # Assumes PostgreSQL JSONB indexing
        query = query.filter(models.Deal.deal_details['category'].astext == category)
    return query.all()

@app.get("/api/deals/active", response_model=List[schemas.DealSchema])
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

@app.get("/api/deals/{deal_id}", response_model=schemas.DealSchema)
def get_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(models.Deal).filter(models.Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal

@app.get("/api/merchants/{merchant_slug}")
def get_merchant_by_slug(merchant_slug: str, db: Session = Depends(get_db)):
    # We use joinedload to eagerly fetch deals, programs, and tiers in one query
    merchant = db.query(models.Merchant).options(
        joinedload(models.Merchant.deals),
        joinedload(models.Merchant.programs).joinedload(models.MembershipProgram.tiers)
    ).filter(models.Merchant.slug == merchant_slug).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
        
    return merchant

@app.get("/api/merchants", response_model=List[schemas.MerchantSchema])
def get_all_merchants(db: Session = Depends(get_db)):
    return db.query(models.Merchant).all()