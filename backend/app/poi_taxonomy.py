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
    CategoryDefinition("parcel", "Parcel collection", "services"),
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
    "atm": "banking",
    "fast food": "fast_food",
    "fried chicken": "fried_chicken",
    "bubble tea": "bubble_tea",
    "coffee": "coffee",
    "cafe": "coffee",
    "restaurant": "restaurants",
    "restaurants": "restaurants",
    "japanese food": "japanese_food",
    "korean food": "korean_food",
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
    "banking": "ATM or bank",
    "parcel": "Parcel point",
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
    "popeyes": ("popeyes", "Popeyes"),
    "posb": ("dbs-posb", "DBS/POSB"),
    "singpost": ("singpost", "SingPost"),
    "singpost popstation": ("singpost", "SingPost"),
    "starbucks": ("starbucks", "Starbucks"),
    "subway": ("subway", "Subway"),
    "texas chicken": ("texas-chicken", "Texas Chicken"),
    "toast box": ("toast-box", "Toast Box"),
    "uob": ("uob", "UOB"),
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


def infer_categories(tags: dict[str, str]) -> tuple[str, ...]:
    name = tags.get("name") or ""
    brand_slug, _ = canonical_brand(tags.get("brand"), tags.get("operator"), name)
    amenity = tags.get("amenity", "").casefold()
    shop = tags.get("shop", "").casefold()
    cuisine = tags.get("cuisine", "").casefold()
    combined = " ".join((normalize_text(name), normalize_text(cuisine)))
    categories: list[str] = []

    if amenity == "fast_food":
        categories.append("fast_food")
    if amenity in {"restaurant", "food_court"}:
        categories.append("restaurants")
    if brand_slug in FRIED_CHICKEN_BRANDS or "fried chicken" in combined:
        categories.extend(("fried_chicken", "fast_food"))
    if "bubble_tea" in cuisine or any(term in combined for term in BUBBLE_TEA_TERMS):
        categories.append("bubble_tea")
    if amenity == "cafe" or shop in {"coffee", "tea"}:
        categories.append("coffee")
    cuisines = set(re.split(r"[;,]", cuisine))
    if "burger" in cuisines:
        categories.append("burgers")
    if cuisines & {"japanese", "sushi", "ramen", "udon", "teppanyaki"}:
        categories.append("japanese_food")
    if "korean" in cuisines:
        categories.append("korean_food")
    if "chinese" in cuisines:
        categories.append("chinese_food")
    if shop in {"bakery", "pastry"} or "bakery" in cuisines:
        categories.append("bakeries")
    if cuisines & {"dessert", "ice_cream", "donut", "confectionery"} or shop == "confectionery":
        categories.append("dessert")
    if shop == "supermarket":
        categories.append("groceries")
    if amenity == "pharmacy" or shop in {"chemist", "pharmacy"}:
        categories.append("pharmacy")
    if shop == "convenience":
        categories.append("convenience")
    if amenity in {"atm", "bank"}:
        categories.append("banking")
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
    if shop in {"copyshop", "printing"} or amenity == "printer":
        categories.append("printing")
    if shop in {"hairdresser", "barber"}:
        categories.append("haircuts")
    if shop in {"optician", "medical_supply"}:
        categories.append("optical")
    if shop in {"repair", "car_repair", "bicycle_repair", "mobile_phone_repair"}:
        categories.append("repairs")
    if amenity in {"parcel_locker", "parcel_pickup"} or tags.get("parcel_pickup") == "yes":
        categories.append("parcel")

    return tuple(dict.fromkeys(categories))
