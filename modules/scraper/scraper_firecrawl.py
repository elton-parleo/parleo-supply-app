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

DEAL_DETAILS_SCHEMA = """
The deal_details JSON field must follow this schema. Only include fields that are relevant to the deal — omit fields that don't apply rather than setting them to null. All field names are snake_case.

─────────────────────────────────────────────
TRIGGER (all deal types)
─────────────────────────────────────────────
trigger_type (required, enum):
  purchase       – spending money at checkout
  action         – non-purchase activity (review, follow, download, etc.)
  event          – life event (birthday, anniversary, tier change, card approval)
  threshold      – cumulative spend gate (annual milestone)
  subscription   – recurring subscription order
  referral       – friend referral
  card_use       – paying with a specific co-brand card
  passive        – access-only perk; no earn trigger

trigger_action (enum, required when trigger_type is action or event):
  birthday | half_birthday | anniversary | account_creation | profile_completion |
  product_review | social_follow | social_share | social_like | app_download |
  sms_opt_in | email_opt_in | referral_completed | store_checkin | survey |
  recycling | quiz | donation | workout_tracking | card_approval | tier_achievement |
  garment_collection | trade_in | livestream_view | check_in_program |
  first_purchase | nth_purchase | purchase_category | wishlist_add |
  content_view | story_submission | consultation

trigger_social_platform (enum, required when trigger_action is social_follow/share/like):
  instagram | tiktok | facebook | pinterest | snapchat | youtube | reddit

trigger_nth_purchase (integer): fires on every Nth purchase (e.g. 3 = every 3rd order)

trigger_referral_role (enum, required when trigger_type is referral):
  referrer | referred_friend | both

trigger_referral_milestone (integer): Nth successful referral unlocking this deal (e.g. 6)

─────────────────────────────────────────────
SPEND CONDITIONS (optional on all types)
─────────────────────────────────────────────
spend_min (number): minimum order/transaction value to qualify
spend_currency (ISO 4217 string): currency for spend_min when non-USD (e.g. "CAD", "GBP")
spend_window_days (integer): rolling window in days for spend_min
spend_per_increment (number): denominator for per-dollar earning (e.g. 1, 3, 10)
spend_annual_min (number): minimum cumulative annual spend to unlock (e.g. 10000, 75000)
spend_item_count (integer): minimum number of items required in cart

─────────────────────────────────────────────
EARN (FLAT_REWARD and MULTIPLIER deal types)
─────────────────────────────────────────────
earn_type (enum, required for earn deals):
  points | percent_back | fixed_currency | stamps | coins | stars

earn_value (number, required for earn deals):
  the numeric amount earned per trigger or per spend_per_increment

earn_currency (string, required when earn_type is fixed_currency or percent_back):
  named reward currency — use "USD" for cash-equivalent
  examples: "Key Rewards", "Walgreens Cash", "Reward Dollars", "USD"

earn_multiplier (number): multiplier on top of base earn rate — PRIMARY field for MULTIPLIER deals
  examples: 1.25, 2, 3, 4, 5

earn_base_value (number): base earn rate the multiplier stacks on (when base varies by tier or card)

earn_cap (number): maximum earn per period in earn units
earn_cap_period (enum): per_transaction | daily | weekly | monthly | quarterly | annual | membership_year | lifetime

earn_limit_uses (integer): max number of times this deal can be triggered
earn_limit_period (enum): once_ever | daily | monthly | annually | per_location

multiplier_selected_categories (integer): number of bonus categories the member picks themselves
multiplier_activation_required (boolean): true if member must actively activate (e.g. choose a double-points day)
multiplier_trade_credit (boolean): true if multiplier applies to trade-in credit rather than purchase points

─────────────────────────────────────────────
DISCOUNT (DISCOUNT deal type — immediate price reduction)
─────────────────────────────────────────────
discount_type (enum, required for discount deals):
  percent_off | amount_off | bogo | free_item | tiered_percent | tiered_amount |
  special_financing | member_price | price_protection | free_trial | fee_waiver | variable

discount_percent (number 0–100): percentage off
  replaces: percent_off, discount_value (percent), percentage_off

discount_percent_max (number 0–100): upper bound for range discounts ("up to 40% off", "30–50% off")

discount_amount (number): fixed dollar amount off
  replaces: amount_off, value (fixed)

discount_amount_max (number): cap on the dollar discount ("up to $500 off", "max $100 savings")

discount_currency (ISO 4217): currency for discount_amount when non-USD

discount_tiers (array of objects, required when discount_type is tiered_percent or tiered_amount):
  each entry: { "spend_min": number, "discount_percent": number }
           or { "spend_min": number, "discount_amount": number }
  example: [{"spend_min": 120, "discount_amount": 40}, {"spend_min": 200, "discount_amount": 75}]

discount_code (string): promo code required at checkout

discount_bogo_structure (enum, required when discount_type is bogo):
  bogo_free | bogo_50 | bogo_percent

discount_financing_term_months (integer): duration of 0% or deferred-interest financing
discount_financing_options (array of objects, for tiered financing):
  each entry: { "term_months": number, "spend_min": number }

discount_scope (enum): what the discount applies to when not captured by scope fields
  sitewide | first_purchase | first_card_purchase | next_purchase | subscription_orders |
  sale_items | clearance | full_price_items | select_items | service | membership_fee | labor_only

discount_applies_to_friend (boolean): true when the discount goes to the referred friend, not the referrer

─────────────────────────────────────────────
POINTS REDEMPTION (DISCOUNT deal type — spending points for a discount or product)
─────────────────────────────────────────────
Use these when a member exchanges accumulated points/coins for a discount or free item.
These are distinct from earning — they describe the redemption side.

redemption_points_cost (number, required for redemption deals):
  points/coins/stars required to unlock the reward
  replaces: points_cost, point_cost, required_points, cost_points

redemption_value_type (enum, required for redemption deals):
  amount_off | percent_off | free_product | free_shipping | store_credit |
  voucher | gift_card | digital_event | experience | giveaway_entry | donation

redemption_discount_amount (number): dollar value unlocked
  replaces: discount_amount, value, voucher_value, credit_value (redemption context)

redemption_discount_percent (number 0–100): percentage off unlocked

redemption_product_name (string): name of the free product unlocked
  replaces: product_name, item_name, reward_item

redemption_max_order_percent (number 0–100): max % of order subtotal coverable by points

redemption_options (array of objects): tiered redemption levels for the same deal type
  each entry: { "redemption_points_cost": number, "redemption_discount_amount": number }
  use when 3+ redemption tiers exist (e.g. 100pts=$5, 200pts=$10, 500pts=$25)

─────────────────────────────────────────────
GIFT (GIFT deal type)
─────────────────────────────────────────────
gift_type (enum, required for gift deals):
  free_product | free_service | free_trial | gift_with_purchase | birthday_gift |
  anniversary_gift | tier_welcome_gift | early_access | exclusive_access |
  event_access | partner_perk | sweepstakes_entry | extended_return |
  priority_support | digital_content | insurance_protection | cash_equivalent | informational

gift_product_name (string): name of the free product
  replaces: product_name, gift_name, item_name, gift_product

gift_estimated_value (number, USD): approximate retail value of the gift

gift_service_name (string): name of the complimentary service (e.g. "Hemming", "Design Crew")

gift_return_window_days (integer): extended return window in days

gift_access_type (enum, required when gift_type is early_access or exclusive_access):
  sales | product_launches | restocks | drops | events | member_only_products | partner_offers

gift_trial_days (integer): length of free trial in days

gift_cash_value (number, USD): dollar value of a gift card or cash-equivalent gift

gift_description (string): short free-text for gifts that resist enumeration (surprise gifts, variable prizes)

gift_while_supplies_last (boolean): true when gift availability is inventory-limited

─────────────────────────────────────────────
SHIPPING (SHIPPING deal type)
─────────────────────────────────────────────
shipping_type (enum, required for shipping deals):
  standard | express | two_day | next_day | same_day | store_pickup |
  collect_near_you | large_item | returns | upgrade

shipping_cost (number): member cost — 0 means free

shipping_order_min (number): minimum order value to qualify
shipping_order_min_currency (ISO 4217): currency for shipping_order_min when non-USD

shipping_region (string or array of strings): geographic scope using ISO 3166-1 alpha-2 or descriptive strings
  examples: "US", "contiguous_US", "CA", "EU", ["US","CA"]

shipping_region_exclusions (array of strings): excluded states or territories
  example: ["AK","HI","PR","APO","FPO"]

shipping_discounted_options (array of objects): tiered delivery pricing (e.g. IKEA large-item)
  each entry: { "delivery_type": string, "member_price": number }

shipping_is_returns (boolean): true when the deal covers return shipping rather than outbound delivery

─────────────────────────────────────────────
POINTS-TO-REWARD CONVERSION (FLAT_REWARD deal type)
─────────────────────────────────────────────
Use when a program issues a named reward certificate after accumulating enough points.

conversion_points_required (number): points/stamps/coins required to unlock a reward
conversion_reward_value (number, USD): dollar value of the issued reward
conversion_reward_name (string): brand name of the reward instrument
  examples: "Kohl's Cash", "Nordstrom Note", "Star Money", "Express Cash"
conversion_auto_issue (boolean): whether reward issues automatically at threshold
conversion_issue_timing (string): when reward posts after qualifying
  examples: "within_48_hours", "next_day", "monthly_on_1st"
conversion_reward_expiry_days (integer): days until issued reward expires

─────────────────────────────────────────────
SCOPE (all deal types)
─────────────────────────────────────────────
scope_brands (array of strings): brands where the deal applies
scope_categories (array of strings): merchant or product categories
scope_channels (array of enums): in_store | online | app | bopis | phone | third_party_marketplace
scope_card_required (boolean): co-brand or store card required
scope_card_name (string): name of the required card
scope_product_description (string): free-text product scope when categories are insufficient
scope_new_customers_only (boolean): only new customers/first-time account holders qualify
scope_segment (string): verified customer segment
  examples: "verified_teacher", "verified_military", "students", "heroes"

─────────────────────────────────────────────
ELIGIBILITY (all deal types)
─────────────────────────────────────────────
Note: do NOT include scope_tiers, membership_required, valid_from, or valid_until inside
deal_details — these are captured in separate top-level Deal table columns.

eligibility_frequency (enum):
  once_ever | once_per_year | twice_per_year | quarterly | monthly | daily |
  per_order | per_location_per_month

eligibility_uses_per_period (integer): exact count when frequency alone is ambiguous
  examples: 4 (for "4x per year"), 3, 6, 12

eligibility_requires_opt_in (array of enums): marketing channels required
  email | sms | push | app

eligibility_account_standing (boolean): account must be open and in good standing

─────────────────────────────────────────────
META (all deal types)
─────────────────────────────────────────────
stacking_combinable (boolean): false when explicitly cannot combine with other promotions
stacking_notes (string): short free-text stacking rule for complex cases
exclusions (array of strings): excluded products, categories, or transaction types
exclusions_notes (string): free-text exclusion detail for complex carve-outs
notes (string): any remaining context that resists structured fields — keep brief
"""


def extract_membership_program_info(markdown_data: str, company_name: str, program_schema: dict, existing_program: dict = None):
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
    user_prompt += f"\n\nPopulate the deal_details JSON field for each deal strictly according to the following schema. Only include fields relevant to each specific deal — omit inapplicable fields entirely rather than setting them to null. Choose the correct field group based on the deal's deal_type.\n{DEAL_DETAILS_SCHEMA}"
    if existing_program:
        user_prompt += f"Here is the existing structured data we have for {company_name}: {existing_program}. If the markdown data contains updates to the existing program, please update the structured data accordingly. If there are no changes, return the existing structured data as is. Only return None for fields that are completely missing from the markdown data or existing program."

    logger.info(f"Generating structured deal info for {company_name}...")
    result = client.generate(
        user_prompt=user_prompt,
        schema=program_schema,
    )

    return result


def extract_deal_info(markdown_data: str, company_name: str, program_schema: dict, existing_program: dict = None):
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
    user_prompt = (
        f"You are given the following markdown data of a {company_name} webpage: {markdown_data}. "
        f"Your task is to extract every deal or promotion present on this page and codify each one into a structured entry for the Deal table. {deal_table}. "
        f"\n\nFor each deal, populate the deal_details JSON field strictly according to the following schema. "
        f"Only include fields relevant to each specific deal — omit inapplicable fields entirely rather than setting them to null. "
        f"Choose the correct field group based on the deal's deal_type.\n{DEAL_DETAILS_SCHEMA}"
    )
    if existing_program:
        user_prompt += (
            f"\n\nHere is the existing structured program data we have for {company_name}: {existing_program}. "
            f"Merge the newly extracted deals into the existing program's deals list: "
            f"update any deal whose title or deal_details clearly match an existing entry, and append genuinely new deals. "
            f"Do not remove deals that are not mentioned on this page — preserve them as-is. "
            f"Return the full updated program object in the same schema."
        )

    logger.info(f"Extracting and merging deal info for {company_name}...")
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