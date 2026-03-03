from modules.models import Product, Merchant, Review

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