"""
Villalife SEO Orchestrator
Koordinerar alla agenter i rätt ordning.

Dagligt flöde:
  1. Hämta färsk GSC-data
  2. Kör audit → uppdatera optimeringskön
  3. Välj top-N uppgifter ur kön
  4. Skriv/optimera artiklar
  5. Logga allt till dashboard
  6. Skicka weekly report (måndagar)

Usage:
  python tools/orchestrator.py           # kör fullt dagligt flöde
  python tools/orchestrator.py --dry-run # visa vad som SKULLE köras
  python tools/orchestrator.py --report  # skicka weekly report direkt
"""

import argparse
import os
import subprocess
import sys
import json
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Hur många artiklar per körning
ARTICLES_PER_RUN = int(os.getenv("ARTICLES_PER_RUN", "3"))

# Prioritetsordning för typer
PRIORITY_ORDER = ["QUICK WIN", "CTR ISSUE", "CONTENT GAP", "NY ARTIKEL"]


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run_tool(script: str, args: list = [], dry_run: bool = False) -> bool:
    """Kör ett tool-script. Returnerar True om det lyckades."""
    cmd = [sys.executable, f"tools/{script}"] + args
    if dry_run:
        log(f"[DRY RUN] Skulle köra: {' '.join(cmd)}")
        return True
    log(f"→ Kör: {script} {' '.join(args)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        log(f"  ✗ Misslyckades (exit {result.returncode})")
        return False
    return True


def get_queue_items(limit: int) -> list:
    """Hämtar top-N items ur Google Sheets-kön."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            os.getenv("GSC_SERVICE_ACCOUNT_FILE"),
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        ws = sh.worksheet("🎯 Optimeringsköen")
        rows = ws.get_all_records()

        # Filtrera bort redan behandlade
        pending = [r for r in rows if r.get("Status") == "Väntar"]

        # Sortera efter prioritetsordning sedan Visningar
        def sort_key(r):
            try:
                prio = PRIORITY_ORDER.index(r.get("Typ", ""))
            except ValueError:
                prio = 99
            return (prio, -int(r.get("Visningar", 0)))

        pending.sort(key=sort_key)
        return pending[:limit]

    except Exception as e:
        log(f"  ✗ Kunde inte läsa kön: {e}")
        return []


def mark_done(url_or_query: str):
    """Markerar en item i kön som Behandlad."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            os.getenv("GSC_SERVICE_ACCOUNT_FILE"),
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        ws = sh.worksheet("🎯 Optimeringsköen")
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row[2] == url_or_query:
                ws.update(values=[["Behandlad"]], range_name=f"G{i}")
                break
    except Exception as e:
        log(f"  ✗ Kunde inte markera som klar: {e}")


def process_item(item: dict, dry_run: bool = False) -> bool:
    """Kör content_writer för ett queue-item."""
    item_type = item.get("Typ", "")
    target = item.get("URL/Sökfras", "")

    if item_type in ("QUICK WIN", "CONTENT GAP"):
        args = ["--keyword", _url_to_keyword(target), "--url", target, "--type", "optimize"]
    elif item_type == "CTR ISSUE":
        args = ["--keyword", _url_to_keyword(target), "--url", target, "--type", "optimize"]
    else:  # NY ARTIKEL
        args = ["--keyword", target, "--type", "new"]

    success = run_tool("content_writer.py", args, dry_run)
    if success and not dry_run:
        mark_done(target)
    return success


def _url_to_keyword(url: str) -> str:
    """Konverterar URL-slug till läsbar sökfras."""
    slug = url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ")


def send_weekly_report(dry_run: bool = False):
    """Skickar weekly email-rapport via Resend."""
    if dry_run:
        log("[DRY RUN] Skulle skicka weekly report")
        return

    try:
        import resend
        import gspread
        from google.oauth2.service_account import Credentials

        resend.api_key = os.getenv("RESEND_API_KEY")

        # Hämta data från sheets
        creds = Credentials.from_service_account_file(
            os.getenv("GSC_SERVICE_ACCOUNT_FILE"),
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))

        # GSC-data (senaste 2 rader för jämförelse)
        gsc_ws = sh.worksheet("📈 GSC Data")
        gsc_rows = gsc_ws.get_all_values()
        latest = gsc_rows[-1] if len(gsc_rows) > 1 else []
        prev = gsc_rows[-2] if len(gsc_rows) > 2 else []

        # Pipeline (senaste 7 dagarna)
        pipe_ws = sh.worksheet("✍️ Content Pipeline")
        pipe_rows = pipe_ws.get_all_records()
        week_date = datetime.now().strftime("%Y-%m-%d")[:8]  # YYYY-MM
        recent = [r for r in pipe_rows if str(r.get("Publicerad", "")).startswith(week_date[:7])]

        # Kön
        queue_ws = sh.worksheet("🎯 Optimeringskön")
        queue_rows = queue_ws.get_all_records()
        pending = len([r for r in queue_rows if r.get("Status") == "Väntar"])

        # Bygg email
        clicks = latest[1] if latest else "?"
        prev_clicks = prev[1] if prev else "?"
        week_num = datetime.now().isocalendar()[1]

        articles_html = "".join(
            f"<tr><td>{r.get('Publicerad','')}</td><td>{r.get('Typ','')}</td><td><a href='{r.get('URL','')}'>{r.get('Titel','')}</a></td></tr>"
            for r in recent[-10:]
        )

        html = f"""
        <div style="font-family:monospace;max-width:600px;margin:0 auto;padding:20px">
        <h2 style="border-bottom:2px solid #333">Villalife Weekly — vecka {week_num}</h2>

        <h3>Trafik</h3>
        <table style="width:100%">
          <tr><td>Klick denna period:</td><td><b>{clicks}</b> (förra: {prev_clicks})</td></tr>
          <tr><td>Artiklar publicerade:</td><td><b>{len(recent)}</b></td></tr>
          <tr><td>I kön (Väntar):</td><td><b>{pending}</b></td></tr>
        </table>

        <h3>Publicerat nyligen</h3>
        <table style="width:100%;border-collapse:collapse">
          <tr style="background:#eee"><th>Datum</th><th>Typ</th><th>Artikel</th></tr>
          {articles_html or '<tr><td colspan=3>Inget publicerat denna period</td></tr>'}
        </table>

        <p style="margin-top:20px;color:#666;font-size:12px">
        <a href="https://docs.google.com/spreadsheets/d/{os.getenv('GOOGLE_SHEET_ID')}">Öppna dashboard</a>
        </p>
        </div>
        """

        resend.Emails.send({
            "from": "Villalife Agent <onboarding@resend.dev>",
            "to": os.getenv("REPORT_EMAIL_TO"),
            "subject": f"Villalife Weekly — vecka {week_num}",
            "html": html,
        })
        log("✓ Weekly report skickad")

    except Exception as e:
        log(f"✗ Kunde inte skicka rapport: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Visa vad som skulle köras")
    parser.add_argument("--report", action="store_true", help="Skicka weekly report direkt")
    parser.add_argument("--articles", type=int, default=ARTICLES_PER_RUN, help="Antal artiklar per körning")
    args = parser.parse_args()

    log("=" * 50)
    log("VILLALIFE SEO ORCHESTRATOR")
    log("=" * 50)

    if args.report:
        send_weekly_report(args.dry_run)
        return

    # --- Steg 1: Hämta färsk GSC-data ---
    log("\n[1/4] Hämtar GSC-data...")
    run_tool("gsc_fetch.py", dry_run=args.dry_run)

    # --- Steg 2: Kör audit ---
    log("\n[2/4] Kör audit...")
    run_tool("gsc_audit.py", dry_run=args.dry_run)

    # --- Steg 3: Uppdatera kön i dashboard ---
    log("\n[3/4] Uppdaterar dashboard...")
    if not args.dry_run:
        try:
            from sheets_dashboard import log_activity, log_gsc_from_file
            log_gsc_from_file()
            log_activity("Orchestrator", "Daglig körning startad", "villalife.se", "✓")
        except Exception as e:
            log(f"  ✗ Dashboard-fel: {e}")

    # --- Steg 4: Behandla queue-items ---
    log(f"\n[4/4] Behandlar upp till {args.articles} artiklar...")
    items = get_queue_items(args.articles)

    if not items:
        log("  Inga items i kön — kör audit för att fylla på")
    else:
        for i, item in enumerate(items, 1):
            log(f"\n  [{i}/{len(items)}] {item.get('Typ')} → {item.get('URL/Sökfras', '')[:60]}")
            process_item(item, args.dry_run)

    # --- Skicka weekly report på måndagar ---
    if datetime.now().weekday() == 0:  # 0 = måndag
        log("\n📧 Måndag — skickar weekly report...")
        send_weekly_report(args.dry_run)

    log("\n✅ Orchestrator klar!")


if __name__ == "__main__":
    main()
