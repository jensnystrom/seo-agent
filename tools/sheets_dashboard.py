"""
Google Sheets Dashboard Tool
Skapar och uppdaterar live-dashboarden för Villalife SEO Agent.

Funktioner:
  setup()           — Skapar sheetet och alla flikar första gången
  log_activity()    — Loggar vad agenten gjort
  log_content()     — Lägger till artikel i content pipeline
  update_content()  — Uppdaterar status på en artikel
  log_gsc_snapshot()— Sparar veckovis GSC-snapshot
  log_opportunity() — Lägger till audit-möjlighet i kön
"""

import json
import os
from datetime import datetime

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SERVICE_ACCOUNT_FILE = os.getenv("GSC_SERVICE_ACCOUNT_FILE")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TABS = {
    "log":         "📋 Aktivitetslogg",
    "pipeline":    "✍️ Content Pipeline",
    "gsc":         "📈 GSC Data",
    "queue":       "🎯 Optimeringsköen",
}


def get_client():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet():
    client = get_client()
    return client.open_by_key(SHEET_ID)


def setup():
    """Skapar alla flikar med rätt headers. Körs en gång."""
    client = get_client()
    sh = client.open_by_key(SHEET_ID)

    existing = [ws.title for ws in sh.worksheets()]

    # --- Aktivitetslogg ---
    tab = TABS["log"]
    if tab not in existing:
        ws = sh.add_worksheet(title=tab, rows=1000, cols=6)
    else:
        ws = sh.worksheet(tab)
    ws.update(values=[["Tidpunkt", "Agent", "Åtgärd", "URL/Sökfras", "Status", "Notering"]], range_name="A1:F1")
    _format_header(ws, "A1:F1")

    # --- Content Pipeline ---
    tab = TABS["pipeline"]
    if tab not in existing:
        ws = sh.add_worksheet(title=tab, rows=500, cols=8)
    else:
        ws = sh.worksheet(tab)
    ws.update(values=[["Publicerad", "Typ", "Titel", "URL", "Sökfras", "Status", "Klick", "Position"]], range_name="A1:H1")
    _format_header(ws, "A1:H1")

    # --- GSC Data ---
    tab = TABS["gsc"]
    if tab not in existing:
        ws = sh.add_worksheet(title=tab, rows=500, cols=6)
    else:
        ws = sh.worksheet(tab)
    ws.update(values=[["Datum", "Klick", "Visningar", "Snitt CTR %", "Snitt Position", "Antal sidor"]], range_name="A1:F1")
    _format_header(ws, "A1:F1")

    # --- Optimeringskön ---
    tab = TABS["queue"]
    if tab not in existing:
        ws = sh.add_worksheet(title=tab, rows=500, cols=7)
    else:
        ws = sh.worksheet(tab)
    ws.update(values=[["Prioritet", "Typ", "URL/Sökfras", "Position", "Visningar", "CTR %", "Status"]], range_name="A1:G1")
    _format_header(ws, "A1:G1")

    print(f"✓ Dashboard klar: https://docs.google.com/spreadsheets/d/{SHEET_ID}")


def _format_header(ws, range_str):
    ws.format(range_str, {
        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    })


def log_activity(agent: str, action: str, target: str = "", status: str = "✓", note: str = ""):
    sh = get_sheet()
    ws = sh.worksheet(TABS["log"])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([ts, agent, action, target, status, note])


def log_content(title: str, url: str, keyword: str, content_type: str = "Ny artikel"):
    sh = get_sheet()
    ws = sh.worksheet(TABS["pipeline"])
    date = datetime.now().strftime("%Y-%m-%d")
    ws.append_row([date, content_type, title, url, keyword, "Publicerad", "", ""])


def update_content_metrics(url: str, clicks: int, position: float):
    sh = get_sheet()
    ws = sh.worksheet(TABS["pipeline"])
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row[3] == url:
            ws.update(f"G{i}:H{i}", [[clicks, position]])
            return


def log_gsc_snapshot(clicks: int, impressions: int, ctr: float, position: float, pages: int):
    sh = get_sheet()
    ws = sh.worksheet(TABS["gsc"])
    date = datetime.now().strftime("%Y-%m-%d")
    ws.append_row([date, clicks, impressions, round(ctr, 2), round(position, 1), pages])


def load_opportunities_to_queue():
    """Läser audit_opportunities.json och fyller optimeringskön."""
    path = ".tmp/audit_opportunities.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sh = get_sheet()
    ws = sh.worksheet(TABS["queue"])

    rows = []
    priority = 1

    for item in data.get("quick_wins", []):
        rows.append([priority, "QUICK WIN", item["page"],
                     item["position"], item["impressions"], item["ctr"], "Väntar"])
        priority += 1

    for item in data.get("ctr_issues", []):
        rows.append([priority, "CTR ISSUE", item["page"],
                     item["position"], item["impressions"], item["ctr"], "Väntar"])
        priority += 1

    for item in data.get("content_gaps", []):
        rows.append([priority, "CONTENT GAP", item["page"],
                     item["position"], item["impressions"], item["ctr"], "Väntar"])
        priority += 1

    for item in data.get("new_content", []):
        rows.append([priority, "NY ARTIKEL", item["query"],
                     item["position"], item["impressions"], 0, "Väntar"])
        priority += 1

    if rows:
        ws.append_rows(rows)

    print(f"✓ {len(rows)} möjligheter inlagda i kön")


def log_gsc_from_file():
    """Läser gsc_pages.json och loggar snapshot."""
    path = ".tmp/gsc_pages.json"
    with open(path, "r", encoding="utf-8") as f:
        pages = json.load(f)

    total_clicks = sum(p["clicks"] for p in pages)
    total_imp = sum(p["impressions"] for p in pages)
    avg_ctr = sum(p["ctr"] for p in pages) / len(pages) if pages else 0
    avg_pos = sum(p["position"] for p in pages) / len(pages) if pages else 0

    log_gsc_snapshot(total_clicks, total_imp, avg_ctr, avg_pos, len(pages))
    print(f"✓ GSC snapshot loggad: {total_clicks} klick, {total_imp} visningar")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"

    if cmd == "setup":
        setup()
        log_gsc_from_file()
        load_opportunities_to_queue()
        log_activity("System", "Dashboard initierad", "villalife.se", "✓", "Första körningen")
    elif cmd == "snapshot":
        log_gsc_from_file()
    elif cmd == "queue":
        load_opportunities_to_queue()
