from loguru import logger
from modules.database import Session
from modules.ChatClient import ChatClient
from scraper.fetch_metadata import fetch_metadata
from etl.load import DataLoader

def get_urls(limit):
    url_dict = {}
    with Session() as session:
        loader = DataLoader(session)
        products = loader.get_products(limit=limit)
        if products:
            url_dict = {product.id: product.link for product in products}
    return url_dict

def store_reviews(product_id, review_content):
    with Session() as session:
        loader = DataLoader(session)
        loader.upsert_review(product_id, review_content)
        session.commit()

def generate_review(url: str) -> str:
    logger.info(f"Fetching metadata from {url}...")
    product_json = fetch_metadata(url)

    logger.info("Generating review...")
    SYSTEM_PROMPT = (
        "You are an expert review writer."
    )
    client = ChatClient(system_prompt=SYSTEM_PROMPT)

    result = client.generate(
        user_prompt=f"Using only the metadata below, please write a one-page review of the product described in the JSON data as if you had purchased and used it. Please be personable and witty. Here is the metadata: {product_json}"
    )

    return result

if __name__ == "__main__":
    urls = get_urls(limit=5)
    for product_id, each_url in urls.items():
        review = generate_review(each_url)
        logger.info(f"Review for {each_url}:\n{review}\n\n")
        store_reviews(product_id=product_id, review_content=review)
