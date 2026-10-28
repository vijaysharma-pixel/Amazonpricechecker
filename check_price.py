
import os
import csv
from decimal import Decimal
import requests
from dotenv import load_dotenv

load_dotenv()

ASIN = "B0DDV2Z2VT"
MARKETPLACE = "ATVPDKIKX0DER"

BASE_URL = "https://sellingpartnerapi-na.amazon.com"


def get_access_token():
    url = "https://api.amazon.com/auth/o2/token"

    response = requests.post(
        url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": os.environ[
                "AMAZON_REFRESH_TOKEN"
            ],
            "client_id": os.environ[
                "AMAZON_CLIENT_ID"
            ],
            "client_secret": os.environ[
                "AMAZON_CLIENT_SECRET"
            ],
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_offers(token):
    url = (
        BASE_URL
        + f"/products/pricing/v0/items/{ASIN}/offers"
    )

    response = requests.get(
        url,
        headers={
            "x-amz-access-token": token,
            "Accept": "application/json",
        },
        params={
            "MarketplaceId": MARKETPLACE,
            "ItemCondition": "New",
            "CustomerType": "Consumer",
        },
        timeout=30,
    )

    response.raise_for_status()
    return response.json()["payload"]


def money(value):
    return Decimal(str(value or 0))


def main():
    print("Connecting to Amazon SP-API...")

    token = get_access_token()
    data = get_offers(token)

    offers = []

    for offer in data.get("Offers", []):
        price = offer.get("ListingPrice", {})
        shipping = offer.get("Shipping", {})

        item_price = money(price.get("Amount"))
        ship_price = money(shipping.get("Amount"))

        offers.append({
            "seller_id": offer.get(
                "SellerId", "Not provided"
            ),
            "item_price": item_price,
            "shipping": ship_price,
            "landed_price": item_price + ship_price,
            "fulfillment": (
                "FBA"
                if offer.get("IsFulfilledByAmazon")
                else "FBM"
            ),
        })

    offers.sort(
        key=lambda x: x["landed_price"]
    )

    print(f"\nASIN: {ASIN}")
    print(f"Offers returned: {len(offers)}")

    if len(offers) >= 2:
        print("\nLOWEST SELLER")
        print(offers[0])

        print("\nSECOND LOWEST SELLER")
        print(offers[1])

    else:
        print(
            "\nFewer than two offers returned."
        )

    with open(
        "amazon_prices.csv",
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "seller_id",
                "item_price",
                "shipping",
                "landed_price",
                "fulfillment",
            ],
        )
        writer.writeheader()
        writer.writerows(offers)

    print("\nSaved to amazon_prices.csv")


if __name__ == "__main__":
    main()
