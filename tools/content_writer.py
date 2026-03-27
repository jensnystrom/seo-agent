"""
Content Writer Tool
Skriver SEO-optimerade artiklar via Claude (OpenRouter) och publicerar till WordPress.

Usage:
  python tools/content_writer.py --keyword "bygg din egen bastu" --url "https://villalife.se/blog/bygg-din-egen-bastu-hemmaspa-pa-budget/" --type optimize
  python tools/content_writer.py --keyword "inglasad altan" --type new
"""

import argparse
import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# OpenRouter via OpenAI-kompatibelt API
client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=os.getenv("OPENROUTER_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")

WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

SITE_NICHE = os.getenv("SITE_NICHE", "villa,hus,bostad,trädgård,renovering")


def generate_article(keyword: str, existing_content: str = "", article_type: str = "new") -> dict:
    """Genererar artikel med Claude. Returnerar dict med title, content, meta, slug."""

    if article_type == "optimize" and existing_content:
        prompt = f"""Du är en expert på svensk SEO och innehållsskrivning för villa- och husintressen.

Uppgift: Optimera och förbättra denna befintliga artikel för att ranka högre på Google för sökordet "{keyword}".

Befintligt innehåll:
{existing_content[:3000]}

Instruktioner:
- Behåll artikelns kärnbudskap men förbättra strukturen kraftigt
- Skriv en mer engagerande och klickvärd titel (inkludera "{keyword}" naturligt)
- Lägg till fler H2/H3-rubriker med relaterade sökfraser
- Expandera innehållet till minst 1200 ord om det är kortare
- Lägg till en praktisk steg-för-steg-sektion eller FAQ om det passar
- Inkludera naturliga interna länkningsmöjligheter
- Skriv en SEO-meta description (max 155 tecken) som ökar CTR
- Allt på svenska, naturlig ton, undvik keyword stuffing

Svara i exakt detta format med XML-taggar:
<title>Artikelns titel</title>
<meta>Max 155 tecken SEO-beskrivning</meta>
<slug>url-slug-pa-svenska</slug>
<content>Full HTML-artikel med h2, h3, p, ul taggar</content>"""

    else:
        prompt = f"""Du är en expert på svensk SEO och innehållsskrivning för villa- och husintressen.

Uppgift: Skriv en komplett SEO-optimerad artikel för sökordet "{keyword}".

Kontext: Villalife.se är en svensk sajt om villa, hus, bostad, trädgård och renovering.

Instruktioner:
- Skriv en engagerande titel som inkluderar "{keyword}" och lockar till klick
- Minst 1200 ord, välstrukturerat med H2 och H3-rubriker
- Börja med en introduktion som svarar direkt på sökintentet
- Inkludera praktiska tips, steg-för-steg eller konkret information
- Avsluta med en sammanfattning eller FAQ
- Naturlig svenska, undvik keyword stuffing
- Inkludera relaterade sökfraser naturligt i texten
- Skriv en SEO-meta description (max 155 tecken) som ökar CTR

Svara i exakt detta format med XML-taggar:
<title>Artikelns titel</title>
<meta>Max 155 tecken SEO-beskrivning</meta>
<slug>url-slug-pa-svenska</slug>
<content>Full HTML-artikel med h2, h3, p, ul taggar</content>"""

    print(f"✍️  Skriver artikel för: {keyword}")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8000,
        temperature=0.7,
    )

    raw = response.choices[0].message.content.strip()

    def extract_tag(text, tag):
        # Försök med closing tag
        m = re.search(rf'<{tag}>([\s\S]*?)</{tag}>', text)
        if m:
            return m.group(1).strip()
        # Fallback: allt efter opening tag (om svaret trunkerades)
        m2 = re.search(rf'<{tag}>([\s\S]*)', text)
        return m2.group(1).strip() if m2 else ""

    title = extract_tag(raw, "title")
    meta = extract_tag(raw, "meta")
    slug = extract_tag(raw, "slug")
    content = extract_tag(raw, "content")

    if not title or not content:
        raise ValueError(f"Kunde inte extrahera fält ur svaret:\n{raw[:400]}")

    return {"title": title, "meta_description": meta, "slug": slug, "content": content}


def wp_api_get(endpoint: str) -> list:
    """Gör GET-anrop mot WP REST API, returnerar lista eller tom lista."""
    base = WP_URL.rstrip("/")
    url = f"{base}/wp-json/wp/v2/{endpoint}"
    resp = requests.get(url, timeout=15)
    if resp.status_code == 200 and resp.text.strip():
        return resp.json()
    return []


def get_existing_content(wp_url_path: str) -> str:
    """Hämtar befintligt innehåll från WordPress via slug."""
    slug = wp_url_path.rstrip("/").split("/")[-1]
    posts = wp_api_get(f"posts?slug={slug}")
    if posts:
        return posts[0].get("content", {}).get("rendered", "")
    return ""


def get_post_id_by_slug(slug: str) -> int | None:
    """Hittar WordPress post ID via slug."""
    posts = wp_api_get(f"posts?slug={slug}&per_page=1")
    if posts:
        return posts[0]["id"]
    return None


def publish_to_wordpress(article: dict, update_id: int = None) -> str:
    """Publicerar eller uppdaterar artikel i WordPress. Returnerar URL."""
    # Application Password: ta bort mellanslag
    password = WP_APP_PASSWORD.replace(" ", "")
    auth = (WP_USERNAME, password)

    payload = {
        "title": article["title"],
        "content": article["content"],
        "status": "publish",
        "slug": article.get("slug", ""),
        "meta": {
            "_yoast_wpseo_metadesc": article.get("meta_description", ""),
        }
    }

    if update_id:
        url = f"{WP_URL}/wp-json/wp/v2/posts/{update_id}"
        resp = requests.post(url, json=payload, auth=auth)
        action = "Uppdaterad"
    else:
        url = f"{WP_URL}/wp-json/wp/v2/posts"
        resp = requests.post(url, json=payload, auth=auth)
        action = "Publicerad"

    resp.raise_for_status()
    post = resp.json()
    post_url = post.get("link", "")
    print(f"✓ {action}: {post_url}")
    return post_url


def log_to_dashboard(keyword: str, title: str, url: str, action: str):
    """Loggar till Google Sheets dashboard."""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from sheets_dashboard import log_activity, log_content
        log_activity("Content Writer", action, url, "✓", title)
        log_content(title, url, keyword, "Ny artikel" if action == "Publicerad" else "Optimerad")
    except Exception as e:
        print(f"  (Dashboard-loggning misslyckades: {e})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True, help="Sökfras att optimera för")
    parser.add_argument("--url", default="", help="Befintlig URL att optimera (lämna tom för ny artikel)")
    parser.add_argument("--type", choices=["new", "optimize"], default="new")
    args = parser.parse_args()

    existing_content = ""
    update_id = None

    if args.type == "optimize" and args.url:
        print(f"📥 Hämtar befintligt innehåll från: {args.url}")
        existing_content = get_existing_content(args.url)
        slug = args.url.rstrip("/").split("/")[-1]
        update_id = get_post_id_by_slug(slug)
        if update_id:
            print(f"   Post ID: {update_id}")

    article = generate_article(args.keyword, existing_content, args.type)

    print(f"\n📄 Titel: {article['title']}")
    print(f"   Meta:  {article['meta_description']}")
    print(f"   Slug:  {article['slug']}")
    print(f"   Ord:   ~{len(article['content'].split())}")

    post_url = publish_to_wordpress(article, update_id)

    action = "Optimerad" if args.type == "optimize" else "Publicerad"
    log_to_dashboard(args.keyword, article["title"], post_url, action)

    print(f"\n✅ Klar! {post_url}")


if __name__ == "__main__":
    main()
