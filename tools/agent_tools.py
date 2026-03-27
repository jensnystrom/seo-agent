"""
Agent Tools — Villalife SEO
Alla verktyg som Claude-agenten kan anropa.
Varje funktion är deterministisk. Claude bestämmer när och hur de används.
"""

import json
import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

WP_URL = os.getenv("WP_URL", "").rstrip("/")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "").replace(" ", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GSC_SERVICE_ACCOUNT_FILE = os.getenv("GSC_SERVICE_ACCOUNT_FILE")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GSC_SITE_URL = os.getenv("GSC_SITE_URL")


# ── GSC ───────────────────────────────────────────────────────────────────────

def get_gsc_top_opportunities(limit: int = 30) -> str:
    """
    Hämtar de bästa SEO-möjligheterna från Google Search Console.
    Returnerar sidor/queries sorterade efter potential.
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from datetime import timedelta

        creds = service_account.Credentials.from_service_account_file(
            GSC_SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
        )
        service = build("searchconsole", "v1", credentials=creds)

        end_date = datetime.today().strftime("%Y-%m-%d")
        start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")

        # Sidor med hög potential
        pages_resp = service.searchanalytics().query(
            siteUrl=GSC_SITE_URL,
            body={
                "startDate": start_date, "endDate": end_date,
                "dimensions": ["page"],
                "rowLimit": 100,
                "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}]
            }
        ).execute()

        pages = pages_resp.get("rows", [])

        # Queries utan dedikerad sida (content gaps)
        queries_resp = service.searchanalytics().query(
            siteUrl=GSC_SITE_URL,
            body={
                "startDate": start_date, "endDate": end_date,
                "dimensions": ["query"],
                "rowLimit": 200,
                "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}]
            }
        ).execute()

        queries = queries_resp.get("rows", [])

        # Bygg sammanfattning för agenten
        result = {
            "quick_wins": [],      # pos 11-30, hög exponering
            "content_gaps": [],    # pos 31-60, hög exponering
            "ctr_issues": [],      # låg CTR trots bra position
            "keyword_gaps": [],    # queries med 0 klick
        }

        for r in pages:
            pos = r["position"]
            imp = r["impressions"]
            ctr = r["ctr"] * 100
            url = r["keys"][0]

            if 11 <= pos <= 30 and imp >= 50:
                result["quick_wins"].append({
                    "url": url, "position": round(pos, 1),
                    "impressions": imp, "clicks": r["clicks"], "ctr": round(ctr, 1)
                })
            elif 31 <= pos <= 60 and imp >= 100:
                result["content_gaps"].append({
                    "url": url, "position": round(pos, 1),
                    "impressions": imp, "clicks": r["clicks"], "ctr": round(ctr, 1)
                })
            elif pos <= 20 and ctr < 2.0 and imp >= 30:
                result["ctr_issues"].append({
                    "url": url, "position": round(pos, 1),
                    "impressions": imp, "clicks": r["clicks"], "ctr": round(ctr, 1)
                })

        for q in queries:
            if q["clicks"] == 0 and q["impressions"] >= 50 and q["position"] > 20:
                result["keyword_gaps"].append({
                    "query": q["keys"][0],
                    "impressions": q["impressions"],
                    "position": round(q["position"], 1)
                })

        # Begränsa per kategori
        for k in result:
            result[k] = sorted(result[k],
                key=lambda x: x.get("impressions", 0), reverse=True)[:limit//4]

        summary = f"""GSC-DATA (senaste 90 dagarna):
Quick Wins ({len(result['quick_wins'])} st) — nära sida 1, optimera innehåll:
{json.dumps(result['quick_wins'][:10], ensure_ascii=False, indent=2)}

Content Gaps ({len(result['content_gaps'])} st) — rankar men för långt ner:
{json.dumps(result['content_gaps'][:10], ensure_ascii=False, indent=2)}

CTR-problem ({len(result['ctr_issues'])} st) — rankar men ingen klickar:
{json.dumps(result['ctr_issues'][:5], ensure_ascii=False, indent=2)}

Keyword Gaps ({len(result['keyword_gaps'])} st) — sökfraser utan bra artikel:
{json.dumps(result['keyword_gaps'][:10], ensure_ascii=False, indent=2)}"""

        return summary

    except Exception as e:
        return f"FEL vid GSC-hämtning: {e}"


# ── WordPress ─────────────────────────────────────────────────────────────────

def get_post_content(url: str) -> str:
    """Hämtar befintligt innehåll från en WordPress-artikel via URL."""
    try:
        slug = url.rstrip("/").split("/")[-1]
        resp = requests.get(f"{WP_URL}/wp-json/wp/v2/posts?slug={slug}", timeout=15)
        posts = resp.json() if resp.status_code == 200 and resp.text.strip() else []
        if posts:
            content = posts[0].get("content", {}).get("rendered", "")
            title = posts[0].get("title", {}).get("rendered", "")
            return f"TITEL: {title}\n\nINNEHÅLL:\n{content[:3000]}"
        return "Ingen artikel hittades för denna URL."
    except Exception as e:
        return f"FEL: {e}"


def publish_article(title: str, content: str, meta_description: str,
                    slug: str, update_url: str = "",
                    category_ids: list = None, featured_media_id: int = 0) -> str:
    """
    Publicerar eller uppdaterar en artikel på WordPress.
    """
    try:
        auth = (WP_USERNAME, WP_APP_PASSWORD)
        payload = {
            "title": title,
            "content": content,
            "status": "publish",
            "slug": slug,
            "meta": {"_yoast_wpseo_metadesc": meta_description},
        }
        if category_ids:
            payload["categories"] = category_ids
        if featured_media_id:
            payload["featured_media"] = featured_media_id

        if update_url:
            slug_from_url = update_url.rstrip("/").split("/")[-1]
            posts = requests.get(
                f"{WP_URL}/wp-json/wp/v2/posts?slug={slug_from_url}", timeout=15
            ).json()
            if posts:
                post_id = posts[0]["id"]
                resp = requests.post(
                    f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                    json=payload, auth=auth, timeout=30
                )
                resp.raise_for_status()
                return f"✓ Uppdaterad: {resp.json().get('link', '')}"

        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            json=payload, auth=auth, timeout=30
        )
        resp.raise_for_status()
        return f"✓ Publicerad: {resp.json().get('link', '')}"

    except Exception as e:
        return f"FEL vid publicering: {e}"


# ── Google Sheets ─────────────────────────────────────────────────────────────

def log_to_dashboard(agent_action: str, target: str,
                     status: str = "✓", note: str = "") -> str:
    """Loggar en agent-händelse till Google Sheets dashboard."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            GSC_SERVICE_ACCOUNT_FILE,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.worksheet("📋 Aktivitetslogg")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        ws.append_row([ts, "Claude Agent", agent_action, target, status, note])
        return "✓ Loggat"
    except Exception as e:
        return f"FEL vid loggning: {e}"


def log_published_content(title: str, url: str, keyword: str,
                           content_type: str = "Ny artikel") -> str:
    """Lägger till en publicerad artikel i Content Pipeline-fliken."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            GSC_SERVICE_ACCOUNT_FILE,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.worksheet("✍️ Content Pipeline")
        date = datetime.now().strftime("%Y-%m-%d")
        ws.append_row([date, content_type, title, url, keyword, "Publicerad", "", ""])
        return "✓ Loggat i pipeline"
    except Exception as e:
        return f"FEL: {e}"


# ── Bildgenerering ────────────────────────────────────────────────────────────

def generate_and_upload_image(prompt: str, article_title: str) -> str:
    """
    Genererar en bild via Grok API och laddar upp till WordPress.
    Returnerar WordPress media ID och URL.
    """
    try:
        # Generera bild via Grok
        resp = requests.post(
            "https://api.x.ai/v1/images/generations",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-imagine-image",
                "prompt": f"{prompt}. Photorealistic, professional, Swedish villa and home context.",
                "n": 1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        image_url = resp.json()["data"][0]["url"]

        # Ladda ner bilden
        img_data = requests.get(image_url, timeout=30).content
        slug = re.sub(r'[^a-z0-9]+', '-', article_title.lower())[:50]
        filename = f"{slug}.jpg"

        # Ladda upp till WordPress media library
        auth = (WP_USERNAME, WP_APP_PASSWORD)
        upload_resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "image/jpeg",
            },
            data=img_data,
            auth=auth,
            timeout=30,
        )
        upload_resp.raise_for_status()
        media = upload_resp.json()
        return json.dumps({"id": media["id"], "url": media["source_url"]})

    except Exception as e:
        return f"FEL vid bildgenerering: {e}"


# ── WordPress kategorier ───────────────────────────────────────────────────────

def get_wp_categories() -> str:
    """Hämtar alla WordPress-kategorier med ID och namn."""
    try:
        resp = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?per_page=100", timeout=15)
        cats = resp.json()
        result = [{"id": c["id"], "name": c["name"], "slug": c["slug"]} for c in cats]
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"FEL: {e}"


# ── Tool-definitioner för Anthropic API ──────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_gsc_top_opportunities",
        "description": "Hämtar SEO-möjligheter från Google Search Console. Returnerar quick wins, content gaps, CTR-problem och keyword gaps. Använd detta som första steg för att förstå vad som behöver göras.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max antal resultat per kategori (default 30)",
                    "default": 30
                }
            }
        }
    },
    {
        "name": "get_post_content",
        "description": "Hämtar befintligt innehåll från en WordPress-artikel. Använd detta innan du optimerar en artikel för att förstå vad som redan finns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL till artikeln"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "publish_article",
        "description": "Publicerar eller uppdaterar en artikel på WordPress. Skriv alltid artiklar på svenska med minst 1200 ord, tydliga H2/H3-rubriker och SEO-optimerad meta description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Artikelns titel"},
                "content": {"type": "string", "description": "HTML-innehåll med h2, h3, p, ul taggar"},
                "meta_description": {"type": "string", "description": "SEO meta description, max 155 tecken"},
                "slug": {"type": "string", "description": "URL-slug på svenska med bindestreck"},
                "update_url": {"type": "string", "description": "URL till befintlig artikel om vi uppdaterar, annars tom"}
            },
            "required": ["title", "content", "meta_description", "slug"]
        }
    },
    {
        "name": "log_to_dashboard",
        "description": "Loggar en händelse till Google Sheets dashboard. Använd efter varje viktig åtgärd.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_action": {"type": "string", "description": "Vad agenten gjorde"},
                "target": {"type": "string", "description": "URL eller sökfras"},
                "status": {"type": "string", "description": "✓ eller ✗"},
                "note": {"type": "string", "description": "Kort notering"}
            },
            "required": ["agent_action", "target"]
        }
    },
    {
        "name": "log_published_content",
        "description": "Lägger till en publicerad artikel i Content Pipeline i dashboarden.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string"},
                "keyword": {"type": "string"},
                "content_type": {"type": "string", "description": "Ny artikel eller Optimerad"}
            },
            "required": ["title", "url", "keyword"]
        }
    },
    {
        "name": "get_wp_categories",
        "description": "Hämtar alla WordPress-kategorier med ID och namn. Kalla detta innan du publicerar för att välja rätt kategori-ID.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "generate_and_upload_image",
        "description": "Genererar en relevant bild med Grok AI och laddar upp till WordPress. Returnerar media ID och URL. Kalla detta för varje artikel för att skapa en featured image.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Bildprompt på engelska, beskriv vad bilden ska föreställa"},
                "article_title": {"type": "string", "description": "Artikelns titel — används som filnamn"}
            },
            "required": ["prompt", "article_title"]
        }
    }
]


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Kör ett verktyg baserat på namn och input från Claude."""
    tools_map = {
        "get_gsc_top_opportunities": get_gsc_top_opportunities,
        "get_post_content": get_post_content,
        "publish_article": publish_article,
        "log_to_dashboard": log_to_dashboard,
        "log_published_content": log_published_content,
        "get_wp_categories": get_wp_categories,
        "generate_and_upload_image": generate_and_upload_image,
    }
    fn = tools_map.get(tool_name)
    if not fn:
        return f"Okänt verktyg: {tool_name}"
    return fn(**tool_input)
