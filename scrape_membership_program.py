
import json
from modules.database import Session
from loguru import logger

from modules.scraper.scraper_firecrawl import extract_membership_program_info, make_schema_strict, scrape_and_extract_info
from etl.load import DataLoader
from modules.schemas import MerchantProgramDealSchema


if __name__ == "__main__":
    update_program = False
    # get all merchants 
    # contruct json {slug: url} from merchant objects
    
    """merchants = {
        "foot-locker": "https://www.footlocker.com/flx",
        "lululemon": "https://shop.lululemon.com/membership",
        "neiman-marcus": "https://www.neimanmarcus.com/my/Loyalty",
        "saks-fifth-avenue": "https://www.saksfifthavenue.com/saksfirst",
        "williams-sonoma": "https://www.williams-sonoma.com/pages/the-key-rewards/",
        "sur-la-table": "https://www.surlatable.com/perks/",
        "fabletics": "https://www.fabletics.com/vip-program",
        "academy-sports-outdoors": "https://www.academy.com/myacademy",
        "mac-cosmetics": "https://www.maccosmetics.com/mac-lover",
        "charlotte-tilbury": "https://www.charlottetilbury.com/us/loyalty-landing-page",
        "glossier": "https://www.glossier.com/pages/glossier-membership-program",
        "jcrew": "https://www.jcrew.com/company/rewards?intcmp=homepage_toppromobanner2_10__rewards_&om_i=builderNewHP_p1",
        "madewell": "https://www.madewell.com/insider",
        "west-elm": "https://www.westelm.com/pages/the-key-rewards/",
        "crate-and-barrel": "https://www.crateandbarrel.com/rewards",
        "sephora": "https://www.sephora.com/BeautyInsider",
        "nike": "https://www.nike.com/membership",
        "ulta-beauty": "https://www.ulta.com/rewards",
        "target": "https://www.target.com/circle",
        "best-buy": "https://www.bestbuy.com/site/misc/my-best-buy/pcmcat309300050007.c",
        "the-north-face": "https://www.thenorthface.com/en-us/xplr-pass",
        "adidas": "https://www.adidas.com/us/adiclub",
        "asos": "https://www.asos.com/discover/asos-world/",
        "hm-us": "https://www2.hm.com/en_us/member/info.html",
        "ikea-us": "https://www.ikea.com/us/en/ikea-family",
        "walgreens": "https://www.walgreens.com/mywalgreens",
        "nordstrom": "https://www.nordstrom.com/browse/nordy-club",
        "dicks-sporting-goods": "https://www.dickssportinggoods.com/s/scorecard-benefits",
        "princess-polly-usa": "https://us.princesspolly.com/pages/rewards",
        "the-body-shop-uk": "https://www.thebodyshop.com/pages/lybc/love-your-body-club",
        "macys": "https://www.macys.com/p/credit-service/benefits/",
        "rei": "https://www.rei.com/membership",
        "Amazon": "https://www.amazon.com/prime",
        "Walmart": "https://www.walmart.com/plus",
        "Kohl's": "https://www.kohls.com/rewards",
        "Costco": "https://www.costco.com/executive-rewards.html",
        "Wayfair": "https://www.wayfair.com/wayfair-rewards",
        "Bed Bath & Beyond": "https://www.bedbathandbeyond.com/welcome-rewards-plus",
        "Shein": "https://m.shein.com/us/bonus-point-program-a-371.html",
        "Levi's": "https://www.levi.com/US/en_US/red-tab-program",
        "Gap": "https://www.gap.com/customer-service/encore-program?cid=1099008",
        "Old Navy": "https://oldnavy.gap.com/browse/info.do?cid=1095422",
        "Urban Outfitters": "https://www.urbanoutfitters.com/uo-rewards",
        "American Eagle": "https://www.ae.com/us/en/content/help/real-rewards-faq",
        "Victoria's Secret": "https://www.victoriassecret.com/us/rewards",
        "PacSun": "https://www.pacsun.com/rewards/",
        "Express": "https://www.express.com/g/insider/program-benefits",
        "Tillys": "https://www.tillys.com/rewards-landing.html",
        "True Religion": "https://www.truereligion.com/true-rewards",
        "DSW": "https://www.dsw.com/customer-service/vip-rewards",
        "Famous Footwear": "https://www.famousfootwear.com/rewards",
        "Lush": "https://www.lush.com/us/en_us/l/club",
        "MoxieLash": "https://www.moxielash.com/pages/rewards",
        "DIME Beauty": "https://dimebeautyco.com/pages/rewards-loyalty",
        "Lancôme": "https://www.lancome-usa.com/rewards",
        "Tarte": "https://tartecosmetics.com/pages/tarte-vip-rewards",
        "Pacifica": "https://www.pacificabeauty.com/pages/pacifica-beauty-rewards-program",
        "Annmarie Skin Care": "https://shop.annmariegianni.com/pages/loyalty-program",
        "Sally Beauty": "https://www.sallybeauty.com/rewards/",
        "Kiehl's": "https://www.kiehls.com/my-kiehls-rewards.html",
        "Home Depot": "https://www.homedepot.com/proxtra",
        "Lowe's": "https://www.lowes.com/l/about/mylowes-rewards",
        "GameStop": "https://www.gamestop.com/pro/",
        "Pottery Barn": "https://www.potterybarn.com/pages/the-key-rewards/",
        "Barnes & Noble": "https://www.barnesandnoble.com/membership",
        "Staples": "https://www.staples.com/rewards",
        "Office Depot": "https://www.officedepot.com/l/rewards",
        "Michaels": "https://www.michaels.com/rewards",
        "Petco": "https://www.petco.com/vitalcare",
        "Chewy": "https://www.chewy.com/app/membership/sign-up",
        "Our Place": "https://fromourplace.com/pages/dirty-dishes-club",
        "Hydro Flask": "https://www.hydroflask.com/house-of-hydro-rewards",
        "Starbucks": "https://www.starbucks.com/rewards",
        "Dunkin'": "https://www.dunkindonuts.com/en/dunkinrewards",
        "Chipotle": "https://www.chipotle.com/rewards",
        "Panera Bread": "https://www.panerabread.com/mypanera",
        "HelloFresh": "https://www.hellofresh.com/pages/refer-a-friend",
        "ThirdLove": "https://www.thirdlove.com/pages/rewards",
        "Loop Earplugs": "https://www.loopearplugs.com/pages/rewards",
        "Pampers": "https://www.pampers.com/en-us/rewards",
        "Huel": "https://huel.com/pages/huel-plus",
        "Brooklinen": "https://www.brooklinen.com/pages/rewards",
        "MeUndies": "https://www.meundies.com/membership",
        "Ruggable": "https://ruggable.com/pages/rewards",
        "The RealReal": "https://www.therealreal.com/first-look/subscription"
        }"""
    
    merchants = {
        "Home Depot": "https://www.homedepot.com/proxtra",
        "Lowe's": "https://www.lowes.com/l/about/mylowes-rewards",
        "GameStop": "https://www.gamestop.com/pro/",
        "Pottery Barn": "https://www.potterybarn.com/pages/the-key-rewards/",
        "Barnes & Noble": "https://www.barnesandnoble.com/membership",
        "Staples": "https://www.staples.com/rewards",
        "Office Depot": "https://www.officedepot.com/l/rewards",
        "Michaels": "https://www.michaels.com/rewards",
        "Petco": "https://www.petco.com/vitalcare",
        "Chewy": "https://www.chewy.com/app/membership/sign-up",
        "Our Place": "https://fromourplace.com/pages/dirty-dishes-club",
        "Hydro Flask": "https://www.hydroflask.com/house-of-hydro-rewards",
        "Starbucks": "https://www.starbucks.com/rewards",
        "Dunkin'": "https://www.dunkindonuts.com/en/dunkinrewards",
        "Chipotle": "https://www.chipotle.com/rewards",
        "Panera Bread": "https://www.panerabread.com/mypanera",
        "HelloFresh": "https://www.hellofresh.com/pages/refer-a-friend",
        "ThirdLove": "https://www.thirdlove.com/pages/rewards",
        "Loop Earplugs": "https://www.loopearplugs.com/pages/rewards",
        "Pampers": "https://www.pampers.com/en-us/rewards",
        "Huel": "https://huel.com/pages/huel-plus",
        "Brooklinen": "https://www.brooklinen.com/pages/rewards",
        "MeUndies": "https://www.meundies.com/membership",
        "Ruggable": "https://ruggable.com/pages/rewards",
        "The RealReal": "https://www.therealreal.com/first-look/subscription"
    }
    
    for merchant_slug, url in merchants.items():

        markdown_data = scrape_and_extract_info(url)
        logger.info(f"Markdown Data: {markdown_data}")

        if markdown_data:
            # Get the schema as a dictionary
            program_schema = MerchantProgramDealSchema.model_json_schema()
            strict_schema = make_schema_strict(program_schema)

            existing_program = None
            if update_program:
                with Session() as session:
                    loader = DataLoader(session)
                    existing_program = loader.get_membership_program(merchant_slug)    
            extracted_data = extract_membership_program_info(markdown_data, merchant_slug, strict_schema, existing_program)
            logger.info(f"Results: {extracted_data}")

            data_dict = json.loads(extracted_data)

            # Validate and map to Pydantic objects
            validated_data = MerchantProgramDealSchema(**data_dict)
            with Session() as session:
                loader = DataLoader(session)
                loader.upsert_membership_program(validated_data, url=url)

