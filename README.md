# Amazon SP-API Price Checker

A Python automation project that retrieves seller offers from Amazon US using the Selling Partner API and updates Google Sheets.

## Features

- Fetches Amazon seller offers by ASIN.
- Identifies the two lowest-priced sellers based on item price plus shipping.
- Retrieves seller ID, item price, shipping, landed price, and fulfillment method.
- Updates Google Sheets automatically.
- Supports test mode and API error handling.

## Requirements

- Python 3.10+
- Amazon SP-API application credentials
- Google Cloud service account with Google Sheets API access

## Installation

1. Clone the repository.
2. Create a Python virtual environment.
3. Install dependencies using `pip install -r requirements.txt`.
4. Create a `.env` file containing your Amazon API configuration.
5. Place your Google service account credentials in `credentials.json`.
6. Share your Google Sheet with the service account email.
7. Run `python amazon_to_sheets.py`.

## Security

Never commit `.env`, `credentials.json`, or API secrets to GitHub.

## Notes

Amazon SP-API rate limits apply. Seller offer availability and prices may change between requests.