"""
GSC Fetch Tool
Hämtar performance-data från Google Search Console för villalife.se
Output: .tmp/gsc_pages.json, .tmp/gsc_queries.json
"""

import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

SERVICE_ACCOUNT_FILE = os.getenv("GSC_SERVICE_ACCOUNT_FILE")
SITE_URL = os.getenv("GSC_SITE_URL")
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
DAYS_BACK = 90
OUTPUT_DIR = ".tmp"


def get_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("searchconsole", "v1", credentials=creds)


def fetch_data(service, dimensions, row_limit=5000):
    end_date = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "orderBy": [{"fieldName": "clicks", "sortOrder": "DESCENDING"}],
    }

    response = (
        service.searchanalytics()
        .query(siteUrl=SITE_URL, body=body)
        .execute()
    )
    return response.get("rows", [])


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    service = get_service()

    # Hämta per sida
    print("Hämtar siddata...")
    page_rows = fetch_data(service, dimensions=["page"])
    pages = [
        {
            "page": r["keys"][0],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr": round(r["ctr"] * 100, 2),
            "position": round(r["position"], 1),
        }
        for r in page_rows
    ]

    # Hämta per query
    print("Hämtar sökfraser...")
    query_rows = fetch_data(service, dimensions=["query"])
    queries = [
        {
            "query": r["keys"][0],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr": round(r["ctr"] * 100, 2),
            "position": round(r["position"], 1),
        }
        for r in query_rows
    ]

    # Hämta query + sida kombinerat (för content gaps)
    print("Hämtar query+sida kombinationer...")
    combo_rows = fetch_data(service, dimensions=["query", "page"], row_limit=10000)
    combos = [
        {
            "query": r["keys"][0],
            "page": r["keys"][1],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr": round(r["ctr"] * 100, 2),
            "position": round(r["position"], 1),
        }
        for r in combo_rows
    ]

    # Spara
    with open(f"{OUTPUT_DIR}/gsc_pages.json", "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    with open(f"{OUTPUT_DIR}/gsc_queries.json", "w", encoding="utf-8") as f:
        json.dump(queries, f, ensure_ascii=False, indent=2)

    with open(f"{OUTPUT_DIR}/gsc_combos.json", "w", encoding="utf-8") as f:
        json.dump(combos, f, ensure_ascii=False, indent=2)

    # Summering
    total_clicks = sum(p["clicks"] for p in pages)
    total_impressions = sum(p["impressions"] for p in pages)
    avg_position = round(sum(p["position"] for p in pages) / len(pages), 1) if pages else 0

    print(f"\n--- GSC Summering ({DAYS_BACK} dagar) ---")
    print(f"Sidor med data:    {len(pages)}")
    print(f"Unika sökfraser:   {len(queries)}")
    print(f"Totala klick:      {total_clicks}")
    print(f"Totala visningar:  {total_impressions}")
    print(f"Snittposition:     {avg_position}")
    print(f"\nSparat till {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
