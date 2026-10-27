from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDefinition:
    slug: str
    name: str
    parent_slug: str | None = None


CATEGORIES = (
    CategoryDefinition("food_drink", "Food and drink"),
    CategoryDefinition("fast_food", "Fast food", "food_drink"),
    CategoryDefinition("fried_chicken", "Fried chicken", "fast_food"),
    CategoryDefinition("bubble_tea", "Bubble tea", "food_drink"),
    CategoryDefinition("coffee", "Coffee", "food_drink"),
    CategoryDefinition("restaurants", "Restaurants", "food_drink"),
    CategoryDefinition("burgers", "Burgers", "food_drink"),
    CategoryDefinition("japanese_food", "Japanese food", "food_drink"),
    CategoryDefinition("korean_food", "Korean food", "food_drink"),
    CategoryDefinition("chinese_food", "Chinese food", "food_drink"),
    CategoryDefinition("bakeries", "Bakeries", "food_drink"),
    CategoryDefinition("dessert", "Dessert", "food_drink"),
    CategoryDefinition("retail", "Retail"),
    CategoryDefinition("groceries", "Supermarket", "retail"),
    CategoryDefinition("pharmacy", "Pharmacy", "retail"),
    CategoryDefinition("convenience", "Convenience store", "retail"),
    CategoryDefinition("electronics", "Electronics", "retail"),
    CategoryDefinition("stationery", "Stationery", "retail"),
    CategoryDefinition("hardware", "Hardware", "retail"),
    CategoryDefinition("florists", "Florists", "retail"),
    CategoryDefinition("pet_supplies", "Pet supplies", "retail"),
    CategoryDefinition("clothing", "Clothing", "retail"),
    CategoryDefinition("household", "Household goods", "retail"),
    CategoryDefinition("services", "Services"),
    CategoryDefinition("banking", "ATM and banking", "services"),
    # An ATM is a two-minute stop and a bank branch is a queue, so the two are
    # told apart. ATMs keep `banking` as a second category, so a request for
    # banking still finds every cash machine it found before.
    CategoryDefinition("atm", "ATMs", "services"),
    CategoryDefinition("parcel", "Parcel collection", "services"),
    CategoryDefinition("post_office", "Post offices", "services"),
    CategoryDefinition("printing", "Printing", "services"),
    CategoryDefinition("haircuts", "Haircuts and barbers", "services"),
    CategoryDefinition("optical", "Optical shops", "services"),
    CategoryDefinition("repairs", "Repairs", "services"),
)

CATEGORY_ALIASES = {
    "grocery": "groceries",
    "supermarket": "groceries",
    "groceries": "groceries",
    "medicine": "pharmacy",
    "chemist": "pharmacy",
    "pharmacy": "pharmacy",
    "post": "parcel",
    "postal": "parcel",
    "parcel": "parcel",
    "parcel collection": "parcel",
    "parcel locker": "parcel",
    "electronics": "electronics",
    "bank": "banking",
    "banking": "banking",
    "atm": "atm",
    "atms": "atm",
    "cash machine": "atm",
    "post office": "post_office",
    "post offices": "post_office",
    "post a letter": "post_office",
    "send a letter": "post_office",
    "stamps": "post_office",
    "buy stamps": "post_office",
    "fast food": "fast_food",
    "fried chicken": "fried_chicken",
    "bubble tea": "bubble_tea",
    "coffee": "coffee",
    "cafe": "coffee",
    "restaurant": "restaurants",
    "restaurants": "restaurants",
    "japanese food": "japanese_food",
    "korean food": "korean_food",
    "chinese food": "chinese_food",
    "burger": "burgers",
    "burgers": "burgers",
    "bakery": "bakeries",
    "bread": "bakeries",
    "dessert": "dessert",
    "flowers": "florists",
    "florist": "florists",
    "stationery": "stationery",
    "printer ink": "stationery",
    "pet food": "pet_supplies",
    "pet supplies": "pet_supplies",
    "hardware": "hardware",
    "clothes": "clothing",
    "clothing": "clothing",
    "printing": "printing",
    "print shop": "printing",
    "haircut": "haircuts",
    "barber": "haircuts",
    "optician": "optical",
    "optical": "optical",
    "convenience": "convenience",
    "convenience store": "convenience",
}


# The noun for ONE unnamed place of each kind. `CategoryDefinition.name` is a
# heading for a group ("Bakeries", "ATM and banking") and reads as a mistake
# when it stands in for a single shop, so the two are kept apart rather than
# one being derived from the other.
UNNAMED_LABELS = {
    "food_drink": "Food and drink place",
    "fast_food": "Fast food place",
    "fried_chicken": "Fried chicken shop",
    "bubble_tea": "Bubble tea shop",
    "coffee": "Coffee shop",
    "restaurants": "Restaurant",
    "burgers": "Burger place",
    "japanese_food": "Japanese restaurant",
    "korean_food": "Korean restaurant",
    "chinese_food": "Chinese restaurant",
    "bakeries": "Bakery",
    "dessert": "Dessert shop",
    "retail": "Shop",
    "groceries": "Supermarket",
    "pharmacy": "Pharmacy",
    "convenience": "Convenience store",
    "electronics": "Electronics shop",
    "stationery": "Stationery shop",
    "hardware": "Hardware shop",
    "florists": "Florist",
    "pet_supplies": "Pet shop",
    "clothing": "Clothes shop",
    "household": "Household goods shop",
    "services": "Service point",
    "banking": "Bank",
    "atm": "ATM",
    "parcel": "Parcel point",
    "post_office": "Post office",
    "printing": "Print shop",
    "haircuts": "Barber or salon",
    "optical": "Optical shop",
    "repairs": "Repair shop",
}


def unnamed_label(slug: str) -> str:
    """What to call a place of this kind that OSM gives no name for.

    Falls back to the group heading rather than to the raw slug: a new category
    added without a noun here reads awkwardly, which is a far smaller failure
    than printing "pet_supplies" at somebody.
    """
    if slug in UNNAMED_LABELS:
        return UNNAMED_LABELS[slug]
    definition = next((item for item in CATEGORIES if item.slug == slug), None)
    return definition.name if definition else slug.replace("_", " ").capitalize()


BRAND_ALIASES = {
    "7 eleven": ("7-eleven", "7-Eleven"),
    "7eleven": ("7-eleven", "7-Eleven"),
    "cheers": ("cheers", "Cheers"),
    "cold storage": ("cold-storage", "Cold Storage"),
    "cs fresh": ("cold-storage", "Cold Storage"),
    "dbs": ("dbs-posb", "DBS/POSB"),
    "fairprice": ("fairprice", "FairPrice"),
    "fairprice finest": ("fairprice", "FairPrice"),
    "fairprice xtra": ("fairprice", "FairPrice"),
    "guardian": ("guardian", "Guardian"),
    "guardian health beauty": ("guardian", "Guardian"),
    "jollibee": ("jollibee", "Jollibee"),
    "kentucky fried chicken": ("kfc", "KFC"),
    "kfc": ("kfc", "KFC"),
    "koi": ("koi-the", "KOI Thé"),
    "koi the": ("koi-the", "KOI Thé"),
    "liho": ("liho-tea", "LiHO Tea"),
    "liho tea": ("liho-tea", "LiHO Tea"),
    "mcdonalds": ("mcdonalds", "McDonald's"),
    "mcdonald s": ("mcdonalds", "McDonald's"),
    "macdonald": ("mcdonalds", "McDonald's"),
    "mcd": ("mcdonalds", "McDonald's"),
    "mr coconut": ("mr-coconut", "Mr Coconut"),
    "ocbc": ("ocbc", "OCBC"),
    "ocbc bank": ("ocbc", "OCBC"),
    "popeyes": ("popeyes", "Popeyes"),
    "posb": ("dbs-posb", "DBS/POSB"),
    "dbs posb": ("dbs-posb", "DBS/POSB"),
    "dbs bank": ("dbs-posb", "DBS/POSB"),
    "singpost": ("singpost", "SingPost"),
    "singpost popstation": ("singpost", "SingPost"),
    "singapore post": ("singpost", "SingPost"),
    "singapore post limited": ("singpost", "SingPost"),
    "starbucks": ("starbucks", "Starbucks"),
    "subway": ("subway", "Subway"),
    "texas chicken": ("texas-chicken", "Texas Chicken"),
    "toast box": ("toast-box", "Toast Box"),
    "uob": ("uob", "UOB"),
    "united overseas bank": ("uob", "UOB"),
    "watsons": ("watsons", "Watsons"),
    "watson": ("watsons", "Watsons"),
}

FRIED_CHICKEN_BRANDS = {"kfc", "jollibee", "popeyes", "texas-chicken"}
BUBBLE_TEA_TERMS = {
    "bubble tea",
    "bubble_tea",
    "boba",
    "koi",
    "liho",
    "gong cha",
    "chicha",
    "itea",
    "playmade",
    "each a cup",
    "mr coconut",
}

NEAR_MISS_SUBSTITUTES = {
    "fried_chicken": ("fast_food",),
    "bubble_tea": ("coffee",),
    "groceries": ("convenience",),
    "pharmacy": ("convenience",),
}


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def canonical_brand(*values: str | None) -> tuple[str | None, str | None]:
    for value in values:
        if not value:
            continue
        normalized = normalize_text(value)
        if normalized in BRAND_ALIASES:
            return BRAND_ALIASES[normalized]
    return None, None


# Cuisine values that put a place in a food category on their own. OSM's
# `cuisine` is the most specific food tag there is, so it is read before the
# broad amenity: an `amenity=cafe` tagged `cuisine=bubble_tea` is a bubble tea
# shop, and counting it as coffee sent people for a latte to a LiHO.
JAPANESE_CUISINES = frozenset({
    "japanese", "sushi", "ramen", "udon", "soba", "teppanyaki", "donburi",
    "yakitori", "tonkatsu", "izakaya", "tempura", "beef_bowl", "katsu",
    "japanese_curry", "okonomiyaki",
})
KOREAN_CUISINES = frozenset({"korean", "korean_bbq", "korean_fried_chicken"})
CHINESE_CUISINES = frozenset({
    "chinese", "cantonese", "dim_sum", "hainanese", "teochew", "hakka",
    "sichuan", "szechuan", "hokkien", "fujian", "hongkong", "hong_kong",
    "taiwanese", "shanghai", "hunan", "chicken_rice", "dumpling", "zi_char",
})
FRIED_CHICKEN_CUISINES = frozenset({"fried_chicken", "wings", "korean_fried_chicken"})
DESSERT_CUISINES = frozenset({
    "dessert", "ice_cream", "donut", "confectionery", "frozen_yogurt", "cake",
    "crepe", "waffle", "chocolate",
})
COFFEE_CUISINES = frozenset({"coffee_shop", "coffee", "cafe", "breakfast", "brunch", "kopitiam"})
# What a cafe can sell instead of coffee. A cafe tagged only with these is not
# where somebody goes for a coffee.
NOT_COFFEE_CAFE_CUISINES = frozenset({
    "bubble_tea", "juice", "milkshake", "smoothie", "tea", "snacks", *DESSERT_CUISINES,
})


def cuisine_list(value: str | None) -> tuple[str, ...]:
    """OSM `cuisine` as its separate values, in the order they were tagged."""
    return tuple(dict.fromkeys(
        item.strip().replace(" ", "_")
        for item in re.split(r"[;,]", (value or "").casefold())
        if item.strip()
    ))


def infer_categories(tags: dict[str, str]) -> tuple[str, ...]:
    name = tags.get("name") or ""
    brand_slug, _ = canonical_brand(tags.get("brand"), tags.get("operator"), name)
    amenity = tags.get("amenity", "").casefold()
    shop = tags.get("shop", "").casefold()
    cuisine = tags.get("cuisine", "").casefold()
    cuisines = frozenset(cuisine_list(cuisine))
    combined = " ".join((normalize_text(name), normalize_text(cuisine)))
    categories: list[str] = []

    if amenity == "fast_food":
        categories.append("fast_food")
    if amenity in {"restaurant", "food_court"}:
        categories.append("restaurants")
    if (
        brand_slug in FRIED_CHICKEN_BRANDS
        or "fried chicken" in combined
        or cuisines & FRIED_CHICKEN_CUISINES
        # "chicken" on a restaurant is as often chicken rice; on a fast food
        # counter it is the fried kind.
        or (amenity == "fast_food" and "chicken" in cuisines)
    ):
        categories.extend(("fried_chicken", "fast_food"))
    is_bubble_tea = "bubble_tea" in cuisines or any(term in combined for term in BUBBLE_TEA_TERMS)
    if is_bubble_tea:
        categories.append("bubble_tea")
    if shop in {"coffee", "tea"}:
        categories.append("coffee")
    elif amenity == "cafe":
        # Cuisine first: a cafe is coffee unless what it says it sells is
        # something else (bubble tea, juice, dessert) and never coffee.
        sells_something_else = is_bubble_tea or bool(
            cuisines and cuisines <= NOT_COFFEE_CAFE_CUISINES
        )
        if not sells_something_else or cuisines & COFFEE_CUISINES:
            categories.append("coffee")
    if "burger" in cuisines:
        categories.append("burgers")
    if cuisines & JAPANESE_CUISINES:
        categories.append("japanese_food")
    if cuisines & KOREAN_CUISINES:
        categories.append("korean_food")
    if cuisines & CHINESE_CUISINES:
        categories.append("chinese_food")
    if shop in {"bakery", "pastry"} or cuisines & {"bakery", "pastry", "bread"}:
        categories.append("bakeries")
    if cuisines & DESSERT_CUISINES or shop == "confectionery":
        categories.append("dessert")
    if shop == "supermarket":
        categories.append("groceries")
    if amenity == "pharmacy" or shop in {"chemist", "pharmacy"}:
        categories.append("pharmacy")
    if shop == "convenience":
        categories.append("convenience")
    if amenity == "atm":
        categories.extend(("atm", "banking"))
    if amenity == "bank":
        categories.append("banking")
        if tags.get("atm") == "yes":
            categories.append("atm")
    if amenity == "post_office":
        # A post office counter takes parcels too, so it also answers a parcel
        # errand - after its own category.
        categories.extend(("post_office", "parcel"))
    if shop in {"electronics", "computer", "mobile_phone", "appliance"}:
        categories.append("electronics")
    if shop in {"stationery", "copyshop"}:
        categories.append("stationery")
    if shop in {"hardware", "doityourself"}:
        categories.append("hardware")
    if shop in {"florist", "garden_centre"}:
        categories.append("florists")
    if shop in {"pet", "pet_grooming"}:
        categories.append("pet_supplies")
    if shop in {"clothes", "shoes", "fashion", "department_store"}:
        categories.append("clothing")
    if shop in {"houseware", "furniture", "interior_decoration", "variety_store"}:
        categories.append("household")
    if shop in {"copyshop", "printing"} or amenity == "printer" or tags.get("craft") == "printer":
        categories.append("printing")
    if shop in {"hairdresser", "barber"}:
        categories.append("haircuts")
    # Opticians only. `shop=medical_supply` sells mobility aids and dressings,
    # not spectacles, and used to fill the optical category with them.
    if shop == "optician":
        categories.append("optical")
    if shop in {"repair", "car_repair", "bicycle_repair", "mobile_phone_repair"}:
        categories.append("repairs")
    if amenity in {"parcel_locker", "parcel_pickup"} or tags.get("parcel_pickup") == "yes":
        categories.append("parcel")

    return tuple(dict.fromkeys(categories))


# Adjectives for a cuisine, used to name a place OSM gives no name for.
CUISINE_ADJECTIVES = {
    "chinese": "Chinese", "cantonese": "Cantonese", "japanese": "Japanese",
    "korean": "Korean", "indian": "Indian", "thai": "Thai", "italian": "Italian",
    "malay": "Malay", "malaysian": "Malaysian", "indonesian": "Indonesian",
    "vietnamese": "Vietnamese", "western": "Western", "french": "French",
    "mexican": "Mexican", "turkish": "Turkish", "seafood": "Seafood",
    "taiwanese": "Taiwanese", "singaporean": "Singaporean", "local": "Local",
    "peranakan": "Peranakan", "filipino": "Filipino", "american": "American",
    "mediterranean": "Mediterranean", "spanish": "Spanish", "greek": "Greek",
    "barbecue": "Barbecue", "vegetarian": "Vegetarian", "vegan": "Vegan",
    "hainanese": "Hainanese", "muslim": "Muslim", "halal": "Halal",
    "asian": "Asian", "regional": "Local", "international": "International",
}
# Cuisines that name the place outright rather than describe it.
CUISINE_NOUNS = {
    "bubble_tea": "Bubble tea shop", "juice": "Juice bar", "ice_cream": "Ice cream shop",
    "dessert": "Dessert shop", "coffee_shop": "Coffee shop", "chicken_rice": "Chicken rice stall",
    "noodle": "Noodle shop", "noodles": "Noodle shop", "burger": "Burger place",
    "sandwich": "Sandwich shop", "donut": "Doughnut shop", "hotpot": "Hotpot restaurant",
    "hot_pot": "Hotpot restaurant", "steak_house": "Steakhouse", "kebab": "Kebab shop",
    "pizza": "Pizza place", "sushi": "Sushi restaurant", "ramen": "Ramen shop",
}
GENERIC_PLACE_NAMES = frozenset(normalize_text(item) for item in (
    *UNNAMED_LABELS.values(), "ATM or bank", "Shopping mall", "Shopping centre",
    "Shopping center", "Mall", "Market", "Wet market", "Food court", "Foodcourt",
    "Coffee shop", "Coffeeshop", "Hawker centre", "Hawker center", "Food centre",
    "Minimart", "Mini mart", "Restaurant", "Cafe", "Café", "ATM", "Bank",
    "Post office", "Shop", "Store", "Eating house", "Canteen", "Western",
    "Chicken rice", "Bubble tea", "Kiosk", "Stall",
))


def is_generic_name(value: str | None) -> bool:
    """True for a name that says what a place is but not which one it is."""
    return not value or normalize_text(value) in GENERIC_PLACE_NAMES


def derived_display_name(
    tags: dict[str, str], categories: tuple[str, ...], canonical_name: str | None = None,
) -> str:
    """The best name a person can read for one place, from its own tags.

    Its own name first, then what the tags say it is - "UOB ATM", "Chinese
    restaurant", "Food court" - and the category's bare noun ("Restaurant")
    only when nothing more is tagged. A bank's name stands for an ATM poorly:
    "UOB" reads as a branch, so an ATM carries the word.
    """
    amenity = (tags.get("amenity") or "").casefold()
    own_name = (tags.get("name") or "").strip()
    named = bool(own_name) and not is_generic_name(own_name)
    brand_label = (
        canonical_name
        or (tags.get("brand") or "").strip()
        or (tags.get("operator") or "").strip()
        or (tags.get("network") or "").strip()
    )
    if amenity == "atm":
        if named and "atm" in normalize_text(own_name).split():
            return own_name
        label = canonical_name or (own_name if named else "") or brand_label
        return f"{label} ATM" if label else unnamed_label("atm")
    if amenity == "post_office":
        # "Bedok Central Post Office" says which one; "SingPost" does not.
        if named and canonical_brand(own_name)[0] is None:
            return own_name
        return f"{canonical_name} post office" if canonical_name else unnamed_label("post_office")
    if canonical_name:
        return canonical_name
    if named:
        return own_name
    if amenity == "bank" and brand_label:
        return brand_label if "bank" in normalize_text(brand_label).split() else f"{brand_label} bank"
    if amenity == "food_court":
        return "Food court"
    cuisines = cuisine_list(tags.get("cuisine"))
    for item in cuisines:
        if item in CUISINE_NOUNS:
            return CUISINE_NOUNS[item]
    adjective = next((CUISINE_ADJECTIVES[item] for item in cuisines if item in CUISINE_ADJECTIVES), None)
    if adjective and amenity in {"restaurant", "fast_food", "cafe"}:
        noun = {"restaurant": "restaurant", "fast_food": "food stall", "cafe": "cafe"}[amenity]
        return f"{adjective} {noun}"
    if brand_label and amenity == "pharmacy":
        return brand_label
    if own_name:
        return own_name
    return unnamed_label(categories[0]) if categories else "Place"
