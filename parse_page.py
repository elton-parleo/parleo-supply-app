import json
from loguru import logger
from modules.database import Session
from etl.transform import DataTransformer
from etl.load import DataLoader

def run_etl(file_path, merchant_name, source):
    # --- EXTRACT ---
    logger.info(f"Extracting data from {file_path}...")
    with open(file_path, 'r') as f:
        raw_data = json.load(f)

    transformer = DataTransformer()
    
    with Session() as session:
        loader = DataLoader(session)
        merchant = loader.get_or_create_merchant(merchant_name)

        # --- TRANSFORM & LOAD ---
        logger.info(f"Transforming and Loading {len(raw_data)} items...")
        for raw_item in raw_data:
            clean_item = transformer.transform_item(raw_item)
            loader.upsert_product(clean_item, merchant.id, source)

        try:
            session.commit()
            logger.info("ETL Pipeline completed successfully.")
        except Exception as e:
            session.rollback()
            logger.error(f"ETL Pipeline failed: {e}")

if __name__ == "__main__":
    print("done")
    #for i in range(0, 4):
    #    run_etl(f'scraper/data/sephora_gift_p{i}.json', merchant_name='Sephora', source='scraper')
