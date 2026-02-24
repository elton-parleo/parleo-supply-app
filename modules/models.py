import os
from typing import Callable
from sqlalchemy import Column, ForeignKey, Integer, Boolean, DateTime, Interval, create_engine, func, JSON, Text, Uuid, Enum, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.engine import URL
from modules.constants import supabase_db_host, supabase_db_password

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

class Merchant(Base):
    __tablename__ = 'merchants'
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

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
