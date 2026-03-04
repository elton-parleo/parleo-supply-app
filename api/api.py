from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone
from modules import models, schemas, database
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    #allow_origins=["https://parleo.com"],
    allow_origins=["*"],
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

@app.get("/api/deals/active")
def get_active_deals(db: Session = Depends(get_db)):
    # Get current timestamp in ISO format
    now = datetime.now(timezone.utc)
    
    # Query for deals where valid_until >= now
    # We also check valid_from to ensure the deal has actually started
    active_deals = db.query(models.Deal).filter(
        models.Deal.valid_until >= now,
        models.Deal.valid_from <= now
    ).all()
    print(f"Queried active deals at {now.isoformat()}, found {len(active_deals)} active deals.")
    
    return active_deals

@app.get("/api/deals/{deal_id}", response_model=schemas.DealSchema)
def get_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(models.Deal).filter(models.Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
