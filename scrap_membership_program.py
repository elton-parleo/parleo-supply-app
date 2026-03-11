
import json
from modules.database import Session
from loguru import logger

from modules.scraper.scraper_firecrawl import extract_membership_program_info, make_schema_strict, scrape_and_extract_info
from etl.load import DataLoader
from modules.schemas import ProgramSchema


if __name__ == "__main__":
    merchants = {
        "lululemon": "https://shop.lululemon.com/membership",
        "neiman-marcus": "https://www.neimanmarcus.com/my/Loyalty",
        "saks-fifth-avenue": "https://www.saksfifthavenue.com/saksfirst",
        "williams-sonoma": "https://www.williams-sonoma.com/pages/the-key-rewards/",
        "sur-la-table": "https://www.surlatable.com/perks/",
        "fabletics": "https://www.fabletics.com/vip-program",
        "academy-sports-+-outdoors": "https://www.academy.com/myacademy",
        "mac-cosmetics": "https://www.maccosmetics.com/mac-lover",
        "charlotte-tilbury": "https://www.charlottetilbury.com/us/loyalty-landing-page",
        "glossier": "https://www.glossier.com/pages/glossier-membership-program",
        "bloomingdale-s": "https://www.glossier.com/pages/membership?srsltid=AfmBOooCwrMjWVO3bXc0mCQa_csRCHgufej0G2pv3fReBNHJn3aRmD16",
        "j-crew": "https://www.jcrew.com/company/rewards?intcmp=homepage_toppromobanner2_10__rewards_&om_i=builderNewHP_p1",
        "madewell": "https://www.madewell.com/insider",
        "west-elm": "https://www.westelm.com/pages/the-key-rewards/",
        "crate---barrel": "https://www.crateandbarrel.com/rewards"
    }
    
    for merchant_slug, url in merchants.items():

        markdown_data = scrape_and_extract_info(url)
        logger.info(f"Markdown Data: {markdown_data}")

        if markdown_data:
            # Get the schema as a dictionary
            program_schema = ProgramSchema.model_json_schema()
            strict_schema = make_schema_strict(program_schema)
            extracted_data = extract_membership_program_info(markdown_data, merchant_slug, strict_schema)
            logger.info(f"Results: {extracted_data}")

            data_dict = json.loads(extracted_data)

            # Validate and map to Pydantic objects
            validated_data = ProgramSchema(**data_dict)
            with Session() as session:
                loader = DataLoader(session)
                loader.upsert_membership_program(validated_data, url=url)

