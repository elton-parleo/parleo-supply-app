import enum
import os
from typing import Callable
from sqlalchemy import Column, ForeignKey, Integer, Boolean, DateTime, Interval, create_engine, func, JSON, Text, Uuid, Enum, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.engine import URL
from sqlalchemy.orm import relationship
from modules.constants import supabase_db_host, supabase_db_password
from modules.schemas import DealType, RedemptionType

func: Callable
Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    sku = Column(Text, nullable=False)
    brand = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    star_review = Column(Text, nullable=True)
    number_of_reviews = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)
    value = Column(Integer, nullable=True)
    sale_price = Column(Integer, nullable=True)
    currency = Column(Text, nullable=False)
    link = Column(Text, nullable=False)
    image_link = Column(Text, nullable=True)
    merchant_id = Column(Integer, ForeignKey('merchants.id'), nullable=False)
    source = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Review(Base):
    __tablename__ = 'reviews'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())




class Merchant(Base):
    __tablename__ = 'merchants'
    
    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True, nullable=False)
    url = Column(Text, nullable=True)
    slug = Column(Text, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship to allow easy access: merchant.deals
    deals = relationship("Deal", back_populates="merchant")
    # Relationship: One merchant can have one or more programs
    programs = relationship("MembershipProgram", back_populates="merchant")

class MembershipProgram(Base):
    __tablename__ = 'membership_programs'
    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey('merchants.id'), nullable=False, index=True)
    program_name = Column(Text)
    program_description = Column(Text)
    
    # Relationship: One program has many tiers
    tiers = relationship("Tier", back_populates="program")
    merchant = relationship("Merchant", back_populates="programs")
    deals = relationship("Deal", back_populates="program")

class Tier(Base):
    __tablename__ = 'tiers'
    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey('membership_programs.id'), nullable=False, index=True)
    name = Column(Text)
    rank = Column(Integer) # Helps the LLM understand hierarchy (e.g., 1, 2, 3)

    program = relationship("MembershipProgram", back_populates="tiers")
    deals = relationship("Deal", back_populates="tier")

class Deal(Base):
    __tablename__ = 'deals'
    
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    redemption_method = Column(Enum(RedemptionType), nullable=False, default=RedemptionType.AUTOMATIC)

    # The actual code string (NULL if redemption_method is AUTOMATIC)
    promo_code = Column(Text)
    
    # Logic Flags
    is_evergreen = Column(Boolean, default=False) # True for the "always on" 1pt/$1
    is_stackable = Column(Boolean, default=True)  # Can this be combined with other deals?
    deal_type = Column(Enum(DealType), nullable=False)
    deal_details = Column(JSON) # The JSONB column for flexible deal logic
    
    # Timing
    valid_from = Column(DateTime, default=func.now())
    valid_until = Column(DateTime)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    merchant_id = Column(Integer, ForeignKey('merchants.id'), nullable=False, index=True)
    program_id = Column(Integer, ForeignKey('membership_programs.id'), nullable=True, index=True)
    tier_id = Column(Integer, ForeignKey('tiers.id'), nullable=True, index=True)
    
    # Relationship to allow easy access: deal.merchant
    merchant = relationship("Merchant", back_populates="deals")
    program = relationship("MembershipProgram", back_populates="deals")
    tier = relationship("Tier", back_populates="deals")


DATABASE_URL = URL.create(
    drivername="postgresql",
    username="postgres.epuofomhfngvkkamlfiz",
    host=supabase_db_host,
    database="postgres",
    port="6543",
    password=supabase_db_password
)
print("host:", supabase_db_host)
print("Connecting to database with URL:", DATABASE_URL)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=15, max_overflow=0)
Base.metadata.create_all(engine)
