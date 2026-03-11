import os

from firecrawl import Firecrawl
from modules.ChatClient import ChatClient
from loguru import logger

def scrape_and_extract_info(url: str):
    app = Firecrawl(api_key=os.getenv("FIRECRAWL_API_KEY"))
    
    data = app.scrape(
        url,
        only_main_content=False,
        max_age=172800000,
        parsers=["pdf"],
        formats=["markdown"]
    )

    return data.markdown if hasattr(data, 'markdown') else ""

def extract_membership_program_info(markdown_data: str, company_name: str, program_schema: dict):
    system_prompt = "You crawl the web and extract information."

    deal_table = f"""
    class DealType(enum.Enum):
        MULTIPLIER = "MULTIPLIER"       # e.g., 4x points
        FLAT_REWARD = "FLAT_REWARD"     # e.g., 1 pt per $1
        DISCOUNT = "DISCOUNT"           # e.g., 20% off
        SHIPPING = "SHIPPING"           # e.g., Free 2-day shipping
        GIFT = "GIFT"      # e.g., Free sample at checkout

    class RedemptionType(enum.Enum):
        AUTOMATIC = "AUTOMATIC"      # No action needed (e.g., Sephora 1pt/$1)
        PROMO_CODE = "PROMO_CODE"    # Requires a string at checkout (e.g., 'SAVE20')
        ACTIVATED = "ACTIVATED"      # Must "clip" or "load" in-app (e.g., Starbucks Star Days)
        
    class Deal(Base):
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
    """

    client = ChatClient(system_prompt=system_prompt)
    user_prompt = f"You are given the following markdown data of the details and perk of {company_name} membership program webpage: {markdown_data}. Please codify it into a structured json to be stored in the Deal table. {deal_table}. "

    logger.info(f"Generating structured deal info for {company_name}...")
    result = client.generate(
        user_prompt=user_prompt,
        schema=program_schema,
    )

    return result


def make_schema_strict(schema: dict):
    """
    Recursively enforces strict mode requirements for OpenAI:
    1. Sets additionalProperties to False.
    2. Ensures every property is listed in the required array.
    """
    # 1. Handle object properties
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["required"] = list(schema["properties"].keys())
            
            # Recurse into each property to handle nested objects
            for prop_name, prop_schema in schema["properties"].items():
                make_schema_strict(prop_schema)
                
    # 2. Handle array items
    elif schema.get("type") == "array" and "items" in schema:
        make_schema_strict(schema["items"])
        
    # 3. Handle definitions ($defs)
    if "$defs" in schema:
        for def_name in schema["$defs"]:
            make_schema_strict(schema["$defs"][def_name])
            
    return schema