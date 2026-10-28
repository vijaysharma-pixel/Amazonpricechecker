"""Update the two lowest returned Amazon US seller offers in a Google Sheet.

Run in TEST_MODE first. Requires .env and credentials.json in this directory.
"""
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

SHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID', '1Js7VKTDfZiBenzRa2xs9nlyC5sNwuv8dgjyKiCRJlvI')
SHEET_NAME = os.getenv('GOOGLE_SHEET_NAME', 'Sheet1')
MARKETPLACE_ID = os.getenv('AMAZON_MARKETPLACE_ID', 'ATVPDKIKX0DER')
API_BASE = os.getenv('AMAZON_API_BASE', 'https://sellingpartnerapi-na.amazon.com').rstrip('/')
TEST_MODE = False  # Set to False only after verifying first ASIN
TEST_ASIN = 'B0DDV2Z2VT'
REQUEST_DELAY_SECONDS = 2.2

EXPECTED_HEADERS = [
    'ASIN', 'seller_id1', 'item_price1', 'shipping1', 'landed_price1',
    'fulfillment1', 'seller_id2', 'item_price2', 'shipping2',
    'landed_price2', 'fulfillment2',
]
SESSION = requests.Session()


def require_env(*keys):
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        raise RuntimeError('Missing .env values: ' + ', '.join(missing))


def connect_sheet():
    if not (ROOT / 'credentials.json').is_file():
        raise RuntimeError('credentials.json is missing from the script folder')
    creds = Credentials.from_service_account_file(
        str(ROOT / 'credentials.json'),
        scopes=['https://www.googleapis.com/auth/spreadsheets'],
    )
    return gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)


def get_amazon_token():
    require_env('AMAZON_CLIENT_ID', 'AMAZON_CLIENT_SECRET', 'AMAZON_REFRESH_TOKEN')
    response = SESSION.post(
        'https://api.amazon.com/auth/o2/token',
        data={
            'grant_type': 'refresh_token',
            'client_id': os.environ['AMAZON_CLIENT_ID'],
            'client_secret': os.environ['AMAZON_CLIENT_SECRET'],
            'refresh_token': os.environ['AMAZON_REFRESH_TOKEN'],
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()['access_token']


def fetch_offers(asin, token):
    url = f'{API_BASE}/products/pricing/v0/items/{asin}/offers'
    headers = {
        'x-amz-access-token': token,
        'Accept': 'application/json',
        'User-Agent': 'AmazonPriceAutomation/1.0 (Language=Python)',
    }
    params = {
        'MarketplaceId': MARKETPLACE_ID,
        'ItemCondition': 'New',
        'CustomerType': 'Consumer',
    }
    for attempt in range(4):
        response = SESSION.get(url, headers=headers, params=params, timeout=30)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            delay = 5 * (2 ** attempt)
            print(f'  Temporary HTTP {response.status_code}; retrying in {delay}s')
            time.sleep(delay)
            continue
        response.raise_for_status()
        break

    result = response.json()
    payload = result.get('payload')
    if not isinstance(payload, dict):
        raise RuntimeError('Amazon returned no valid offer payload; no cells updated')
    status = payload.get('status')
    print('  Amazon offer status:', status)
    if status != 'Success':
        raise RuntimeError(f'Amazon offer status was {status!r}; no cells updated')
    offers = payload.get('Offers')
    if not isinstance(offers, list):
        raise RuntimeError('Amazon did not return an Offers list; no cells updated')
    summary = payload.get('Summary') or {}
    print('  Total offers reported:', summary.get('TotalOfferCount', 'unknown'))
    return offers, summary


def amount(value):
    if not isinstance(value, dict) or value.get('Amount') is None:
        return None
    try:
        number = Decimal(str(value['Amount']))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def rank_offers(raw_offers):
    valid = {}
    incomplete = False
    for offer in raw_offers:
        if not isinstance(offer, dict):
            incomplete = True
            continue
        subcondition = offer.get('SubCondition')
        if subcondition and str(subcondition).lower() != 'new':
            continue
        seller = offer.get('SellerId')
        item = amount(offer.get('ListingPrice'))
        shipping = amount(offer.get('Shipping'))
        if not seller or item is None or shipping is None:
            incomplete = True
            continue
        row = {
            'seller': str(seller),
            'item': item,
            'shipping': shipping,
            'landed': item + shipping,
            'fulfillment': 'FBA' if offer.get('IsFulfilledByAmazon') else 'FBM',
        }
        if seller not in valid or row['landed'] < valid[seller]['landed']:
            valid[seller] = row
    return sorted(valid.values(), key=lambda r: (r['landed'], r['seller'])), incomplete


def seller_values(offer):
    return [
        offer['seller'], float(offer['item']), float(offer['shipping']),
        float(offer['landed']), offer['fulfillment'],
    ]


def build_values(raw_offers, summary):
    ranked, incomplete = rank_offers(raw_offers)
    # Amazon returns at most a limited selection of offers. Avoid asserting
    # 'Inactive' when summary says offers exist but none were usable.
    total = summary.get('TotalOfferCount')
    if not ranked:
        if incomplete or total not in (0, '0'):
            raise RuntimeError('Cannot confirm zero eligible offers; preserving sheet')
        return ['Inactive'] * 10
    if len(ranked) == 1:
        if incomplete:
            raise RuntimeError('Some offers have missing price/shipping; preserving sheet')
        return seller_values(ranked[0]) + ['Not Available'] * 5
    if incomplete:
        raise RuntimeError('Some offers have missing price/shipping; ranking uncertain')
    return seller_values(ranked[0]) + seller_values(ranked[1])


def main():
    sheet = connect_sheet()
    print('Google Sheet connected.')
    if sheet.row_values(1)[:11] != EXPECTED_HEADERS:
        raise RuntimeError('Column headers A:K do not match expected layout; no cells updated')
    asins = sheet.col_values(1)[1:]
    print('ASIN rows found:', len(asins))
    token = get_amazon_token()
    cache = {}
    updated = 0
    failed = 0
    for row_index, raw_asin in enumerate(asins, start=2):
        asin = str(raw_asin).strip().upper()
        if not asin or (TEST_MODE and asin != TEST_ASIN):
            continue
        print(f'\nProcessing row {row_index}: {asin}')
        try:
            if not re.fullmatch(r'[A-Z0-9]{10}', asin):
                raise ValueError('ASIN must contain exactly 10 letters/digits')
            if asin not in cache:
                offers, summary = fetch_offers(asin, token)
                cache[asin] = build_values(offers, summary)
                time.sleep(REQUEST_DELAY_SECONDS)
            sheet.update(
                range_name=f'B{row_index}:K{row_index}',
                values=[cache[asin]],
                value_input_option='RAW',
            )
            updated += 1
            print('  Sheet updated')
        except (requests.RequestException, RuntimeError, ValueError, gspread.exceptions.GSpreadException) as exc:
            failed += 1
            print(f'  ERROR: {type(exc).__name__}: {exc}')
            print('  Existing values preserved')
    print(f'\nFinished. Rows updated: {updated}; rows with errors: {failed}')
    if TEST_MODE:
        print('TEST_MODE is True. Verify row 2 before changing it to False.')


if __name__ == '__main__':
    main()
