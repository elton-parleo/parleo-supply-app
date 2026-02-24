from modules.models import Product, Merchant

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