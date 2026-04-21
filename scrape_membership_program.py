
import json
from modules.database import Session
from loguru import logger

from modules.scraper.scraper_firecrawl import extract_membership_program_info, make_schema_strict, scrape_and_extract_info, extract_deal_info
from etl.load import DataLoader
from modules.schemas import MerchantProgramDealSchema


if __name__ == "__main__":
    update_program = True
    parse_deals_only = True
    # get all merchants 
    # contruct json {slug: url} from merchant objects
    
    """merchants = 
        {
            "glossier": "https://www.glossier.com/pages/glossier-membership-program",
            "jcrew": "https://www.jcrew.com/company/rewards?intcmp=homepage_toppromobanner2_10__rewards_&om_i=builderNewHP_p1",
            "madewell": "https://www.madewell.com/insider",
            "west-elm": "https://www.westelm.com/pages/the-key-rewards/",
            "kohls": "https://www.kohls.com/rewards",
            "sephora": "https://www.sephora.com/BeautyInsider",
            "costco": "https://www.costco.com/executive-rewards.html",
            "wayfair": "https://www.wayfair.com/wayfair-rewards",
            "bed-bath-and-beyond": "https://www.bedbathandbeyond.com/welcome-rewards-plus",
            "shein-us": "https://m.shein.com/us/bonus-point-program-a-371.html",
            "levis-us": "https://www.levi.com/US/en_US/red-tab-program",
            "gap": "https://www.gap.com/customer-service/encore-program?cid=1099008",
            "old-navy": "https://oldnavy.gap.com/browse/info.do?cid=1095422",
            "urban-outfitters": "https://www.urbanoutfitters.com/uo-rewards",
            "american-eagle-outfitters": "https://www.ae.com/us/en/content/help/real-rewards-faq",
            "victorias-secret": "https://www.victoriassecret.com/us/rewards",
            "pacsun": "https://www.pacsun.com/rewards/",
            "express": "https://www.express.com/g/insider/program-benefits",
            "tillys": "https://www.tillys.com/rewards-landing.html",
            "true-religion": "https://www.truereligion.com/true-rewards",
            "dsw": "https://www.dsw.com/customer-service/vip-rewards",
            "famous-footwear": "https://www.famousfootwear.com/rewards",
            "lush": "https://www.lush.com/us/en_us/l/club",
            "moxielash": "https://www.moxielash.com/pages/rewards",
            "dimebeautyco": "https://dimebeautyco.com/pages/rewards-loyalty",
            "lancome-usa": "https://www.lancome-usa.com/rewards",
            "tarte": "https://tartecosmetics.com/pages/tarte-vip-rewards",
            "rei": "https://www.rei.com/membership",
            "adidas": "https://www.adidas.com/us/adiclub",
            "asos": "https://www.asos.com/discover/asos-world/",
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
            "hm-us": "https://www2.hm.com/en_us/member/info.html",
            "ikea-us": "https://www.ikea.com/us/en/ikea-family",
            "pacifica-beauty": "https://www.pacificabeauty.com/pages/pacifica-beauty-rewards-program",
            "nordstrom": "https://www.nordstrom.com/browse/nordy-club",
            "dicks-sporting-goods": "https://www.dickssportinggoods.com/s/scorecard-benefits",
            "princess-polly-usa": "https://us.princesspolly.com/pages/rewards",
            "the-body-shop-uk": "https://www.thebodyshop.com/pages/lybc/love-your-body-club",
            "macys": "https://www.macys.com/p/credit-service/benefits/",
            "crate-and-barrel": "https://www.crateandbarrel.com/rewards",
            "nike": "https://www.nike.com/membership",
            "walgreens": "https://www.walgreens.com/mywalgreens",
            "ulta-beauty": "https://www.ulta.com/rewards",
            "target": "https://www.target.com/circle",
            "best-buy": "https://www.bestbuy.com/site/misc/my-best-buy/pcmcat309300050007.c",
            "the-north-face": "https://www.thenorthface.com/en-us/xplr-pass",
            "amazon": "https://www.amazon.com/prime",
            "walmart": "https://www.walmart.com/plus",
            "annmarie-skin-care": "https://shop.annmariegianni.com/pages/loyalty-program",
            "sally-beauty": "https://www.sallybeauty.com/rewards/",
            "kiehls-us": "https://www.kiehls.com/my-kiehls-rewards.html",
            "home-depot": "https://www.homedepot.com/proxtra",
            "lowes": "https://www.lowes.com/l/about/mylowes-rewards",
            "gamestop": "https://www.gamestop.com/pro/",
            "pottery-barn": "https://www.potterybarn.com/pages/the-key-rewards/",
            "barnes-and-noble": "https://www.barnesandnoble.com/membership",
            "staples": "https://www.staples.com/rewards",
            "office-depot": "https://www.officedepot.com/l/rewards",
            "michaels": "https://www.michaels.com/rewards",
            "petco": "https://www.petco.com/vitalcare",
            "chewy": "https://www.chewy.com/app/membership/sign-up",
            "our-place": "https://fromourplace.com/pages/dirty-dishes-club",
            "hydro-flask": "https://www.hydroflask.com/house-of-hydro-rewards",
            "starbucks": "https://www.starbucks.com/rewards",
            "dunkin": "https://www.dunkindonuts.com/en/dunkinrewards",
            "chipotle": "https://www.chipotle.com/rewards",
            "panera-bread": "https://www.panerabread.com/mypanera",
            "hellofresh": "https://www.hellofresh.com/pages/refer-a-friend",
            "thirdlove": "https://www.thirdlove.com/pages/rewards",
            "loop-earplugs": "https://www.loopearplugs.com/pages/rewards",
            "pampers": "https://www.pampers.com/en-us/rewards",
            "huel": "https://huel.com/pages/huel-plus",
            "brooklinen": "https://www.brooklinen.com/pages/rewards",
            "meundies": "https://www.meundies.com/membership",
            "ruggable": "https://ruggable.com/pages/rewards",
            "the-realreal": "https://www.therealreal.com/first-look/subscription"
        }"""
    
    merchants = {
            #"sephora": "https://www.sephora.com/beauty/beauty-offers",
            "ulta-beauty": "https://www.ulta.com/promotion/coupon",
            "sally-beauty": "https://www.sallybeauty.com/deals/",
            "pacifica-beauty": "https://www.pacificabeauty.com/pages/deals-coupons-promo-codes",
            "kiehls-us": "https://www.kiehls.com/offers.html"
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
            if parse_deals_only:
                extracted_data = extract_deal_info(markdown_data, merchant_slug, strict_schema, existing_program)
            else:
                extracted_data = extract_membership_program_info(markdown_data, merchant_slug, strict_schema, existing_program)
            logger.info(f"Results: {extracted_data}")

            data_dict = json.loads(extracted_data)

            # Validate and map to Pydantic objects
            validated_data = MerchantProgramDealSchema(**data_dict)
            with Session() as session:
                logger.info(f'Upserting data for {merchant_slug}...')
                loader = DataLoader(session)
                loader.upsert_membership_program(validated_data, url=url)

