import json

from sqlalchemy import func

from modules.models import Deal, MembershipProgram, Product, Merchant, Review, Tier
from modules.schemas import MerchantProgramDealSchema

class DataLoader:
    def __init__(self, session):
        self.session = session

    def get_or_create_merchant(self, name):
        merchant = self.session.query(Merchant).filter_by(name=name).first()
        if not merchant:
            merchant = Merchant(name=name)
            self.session.add(merchant)
            self.session.flush()
        return merchant

    def upsert_product(self, clean_data, merchant_id, source):
        product = self.session.query(Product).filter_by(sku=clean_data['sku']).first()
        
        if product:
            for key, value in clean_data.items():
                setattr(product, key, value)
            product.merchant_id = merchant_id
            product.source = source
        else:
            product = Product(**clean_data, merchant_id=merchant_id, source=source)
            self.session.add(product)

    def get_products(self, limit=None, without_reviews=False):
        query = self.session.query(Product)
        
        if without_reviews:
            query = query.outerjoin(Review).filter(Review.id.is_(None))
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def upsert_review(self, product_id, content):
        review = self.session.query(Review).filter_by(product_id=product_id).first()
        if review:
            review.content = content
        else:
            review = Review(product_id=product_id, content=content)
            self.session.add(review)

    def get_membership_program(self, merchant_slug) -> MerchantProgramDealSchema:
        merchant = self.session.query(Merchant).filter_by(slug=merchant_slug).first()
        if not merchant:
            merchant = Merchant(slug=merchant_slug)
            self.session.add(merchant)
            self.session.flush()
        
        program = self.session.query(MembershipProgram).filter_by(
            merchant_id=merchant.id
        ).first()
        if not program:
            return None
        
        tiers = self.session.query(Tier).filter_by(program_id=program.id).all()
        deals = self.session.query(Deal).filter_by(program_id=program.id).all()
        
        return MerchantProgramDealSchema(
            merchant_id=merchant.id,
            merchant_name=merchant.name,
            merchant_slug=merchant.slug,
            program_id=program.id,
            program_name=program.program_name,
            program_description=program.program_description,
            tiers=[{"id": t.id, "name": t.name, "rank": t.rank} for t in tiers],
            deals=[{"id": d.id, "title": d.title, "tier_name": next((t.name for t in tiers if t.id == d.tier_id), None), "deal_details": json.dumps(d.deal_details), "redemption_method": d.redemption_method, "promo_code": d.promo_code, "is_evergreen": d.is_evergreen, "is_stackable": d.is_stackable, "valid_from": d.valid_from, "valid_until": d.valid_until, "deal_type": d.deal_type} for d in deals]
        )

    def upsert_membership_program(self, data: MerchantProgramDealSchema, url: str=None):
        """
        Upserts a full membership program structure into the database.
        Assumes data is already a validated Pydantic object.
        """
        # 1. Get or create Merchant
        merchant = self.session.query(Merchant).filter_by(slug=data.merchant_slug).first()
        if merchant:
            merchant.updated_at = func.now() # Update timestamp if merchant already exists
        else:
            merchant = Merchant(name=data.merchant_name, slug=data.merchant_slug, url=url)
            merchant.updated_at = func.now()
            self.session.add(merchant)
            self.session.flush()

        # 2. Get or create Membership Program
        program = self.session.get(MembershipProgram, data.program_id) if data.program_id else None # look up by ID if provided
        if not program: # fallback to lookup by merchant_id + program_name if ID not provided or not found
            program = self.session.query(MembershipProgram).filter_by(
                merchant_id=merchant.id, program_name=data.program_name
            ).first()
        
        if program: # if found, update fields
            program.program_name = data.program_name
            program.program_description = data.program_description
        else: # If not found, create new
            program = MembershipProgram(merchant_id=merchant.id, program_name=data.program_name, program_description=data.program_description)
            self.session.add(program)
            self.session.flush()

        # 3. Handle Tiers
        # Note: We clear old tiers if we want a fresh sync, or we can update based on rank
        tier_map = {}
        for t_data in data.tiers:
            if t_data.id: # Update existing tier
                tier = self.session.get(Tier, t_data.id)
                if tier:
                    tier.name = t_data.name
                    tier.rank = t_data.rank
            else: # Create new tier
                tier = Tier(program_id=program.id, name=t_data.name, rank=t_data.rank)
                self.session.add(tier)
            
            self.session.flush()
            tier_map[t_data.name] = tier.id

        # 4. Handle Deals
        for d_data in data.deals:
            # Parse the stringified JSON into a real dict
            try:
                details_dict = json.loads(d_data.deal_details)
            except json.JSONDecodeError:
                details_dict = {}

            if d_data.id is not None: # Update existing deal
                deal = self.session.get(Deal, d_data.id)
                if deal:
                    deal.title = d_data.title
                    deal.tier_id = tier_map.get(d_data.tier_name)
                    deal.redemption_method = d_data.redemption_method
                    deal.promo_code = d_data.promo_code
                    deal.is_evergreen = d_data.is_evergreen
                    deal.is_stackable = d_data.is_stackable
                    deal.valid_from = d_data.valid_from
                    deal.valid_until = d_data.valid_until
                    deal.deal_type = d_data.deal_type
                    deal.deal_details = details_dict
                    deal.updated_at = func.now() # Update timestamp if deal already exists
            else: # Create new deal
                deal = Deal(
                    merchant_id=merchant.id,
                    program_id=program.id,
                    tier_id=tier_map.get(d_data.tier_name),
                    title=d_data.title,
                    redemption_method=d_data.redemption_method,
                    promo_code=d_data.promo_code,
                    is_evergreen=d_data.is_evergreen,
                    is_stackable=d_data.is_stackable,
                    valid_from=d_data.valid_from,
                    valid_until=d_data.valid_until,
                    deal_type=d_data.deal_type,
                    deal_details=details_dict
                )
                self.session.add(deal)
        
        self.session.commit()