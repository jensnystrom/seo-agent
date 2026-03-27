"""
Agent Runner — Villalife SEO
Claude kör som autonom agent via OpenRouter.

Arkitektur:
  - Claude använder enkla tools (GSC, WP läs, logga)
  - Claude skriver artiklar i sin textrespons med XML-taggar
  - Vi parsar texten och publicerar via WP API
  - Inga stora JSON-strängar i tool calls

Usage:
  python tools/agent_runner.py
  python tools/agent_runner.py --dry-run
"""

import argparse
import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from agent_tools import (
    TOOL_DEFINITIONS, execute_tool,
    publish_article, log_to_dashboard, log_published_content
)

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=os.getenv("OPENROUTER_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
MAX_ITERATIONS = 25

# Enklare tools utan publish_article (artiklar skrivs i textrespons)
AGENT_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] not in ("publish_article", "log_published_content")]
AGENT_TOOLS.append({
    "name": "publish_written_article",
    "description": "Publicerar artikeln du precis skrivit i XML-format. Kalla DIREKT efter <article>-taggar.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "Sökfrasen artikeln är optimerad för"},
            "update_url": {"type": "string", "description": "URL till befintlig artikel att uppdatera. Tom om ny."},
            "category_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Lista med WordPress kategori-ID:n från get_wp_categories"
            },
            "featured_media_id": {
                "type": "integer",
                "description": "Media ID från generate_and_upload_image"
            }
        },
        "required": ["keyword"]
    }
})

SYSTEM_PROMPT = """Du är en autonom SEO-agent för Villalife.se — en svensk sajt om villa, hus, bostad, trädgård och renovering.

## Ditt dagliga uppdrag per artikel:
1. Hämta GSC-data och välj 3 artiklar med störst potential
2. Hämta WordPress-kategorier (get_wp_categories)
3. Generera bild med Grok (generate_and_upload_image)
4. Skriv artikeln i din respons med XML-taggar
5. Kalla publish_written_article med kategori-ID och media-ID
6. Logga i dashboarden

## KRITISKT — Så här skriver och publicerar du:

STEG 1: Generera bild och hämta kategorier (tool calls)

STEG 2: Skriv artikeln med dessa exakta taggar:
<article>
<title>Artikelns titel</title>
<meta>SEO meta description max 155 tecken</meta>
<slug>url-slug-pa-svenska</slug>
<content>
<h2>Rubrik</h2>
<p>Innehåll med <a href="/relaterad-artikel">internlänk</a> och <a href="https://extern.se" rel="nofollow">externlänk</a>...</p>
</content>
</article>

STEG 3: Kalla OMEDELBART publish_written_article med category_id och featured_media_id.
Avsluta ALDRIG ett svar med <article>-taggar utan att kalla publish_written_article.

## Riktlinjer för innehåll:
- Svenska, naturlig och hjälpsam ton, minst 1200 ord
- H2/H3-rubriker med relaterade sökfraser
- Minst 2-3 internlänkar till andra sidor på villalife.se
- Minst 1 externlänk till auktoritativ källa (rel="nofollow")
- Praktiska tips och konkret information
- Undvik keyword stuffing

## Prioriteringsordning:
1. Quick wins (position 11-30)
2. CTR-problem
3. Content gaps (31-60)
4. Keyword gaps — nya artiklar"""


def extract_article_from_text(text: str) -> dict | None:
    """Extraherar artikel från Claude's textrespons. Hanterar varianter av taggnamn."""
    def tag(*names):
        for name in names:
            m = re.search(rf'<{name}[^>]*>([\s\S]*?)</{name}>', text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        # Fallback: allt efter första matchande tag
        for name in names:
            m2 = re.search(rf'<{name}[^>]*>([\s\S]*)', text, re.IGNORECASE)
            if m2:
                return m2.group(1).strip()
        return ""

    title = tag("title")
    content = tag("content")
    if not title or not content:
        return None
    return {
        "title": title,
        "meta_description": tag("meta", "meta_description"),
        "slug": tag("slug"),
        "content": content,
    }


def run_agent(dry_run: bool = False) -> str:
    print(f"\n{'='*50}")
    print(f"VILLALIFE SEO AGENT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if dry_run:
        print("[DRY RUN] Simulerar utan publicering\n")

    messages = [
        {
            "role": "user",
            "content": f"""Kör dagens SEO-arbete för Villalife.se.
Datum: {datetime.now().strftime('%Y-%m-%d')}
{"OBS: DRY RUN — analysera och planera men publicera INTE." if dry_run else ""}

Börja med att hämta GSC-data och beskriv din strategi."""
        }
    ]

    iteration = 0
    final_response = ""
    pending_publish = None
    articles_published = 0
    planning_done = False

    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"\n[Iteration {iteration}]")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"]
                }
            } for t in AGENT_TOOLS],
            tool_choice="auto",
            max_tokens=8000,
        )

        msg = response.choices[0]
        assistant_content = msg.message.content or ""

        # Spara assistentens textrespons i historiken
        messages.append({
            "role": "assistant",
            "content": assistant_content,
            **({"tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in (msg.message.tool_calls or [])
            ]} if msg.message.tool_calls else {})
        })

        # Kolla om Claude skrev en artikel i textresponsen
        if "<article>" in assistant_content:
            pending_publish = extract_article_from_text(assistant_content)
            if pending_publish:
                print(f"  📝 Artikel redo: {pending_publish['title'][:60]}")

        # Klar?
        if msg.finish_reason == "stop" or not msg.message.tool_calls:
            # Om agenten bara planerat utan att agera — skicka follow-up
            if articles_published == 0 and not planning_done:
                planning_done = True
                print(f"  (Agent planerade — skickar follow-up)")
                messages.append({
                    "role": "user",
                    "content": "Bra analys! Nu kör du faktiskt arbetet. Skriv och publicera de 3 artiklarna direkt. Börja med artikel 1 nu."
                })
                continue

            # Om en artikel är redo men inte publicerad — auto-publicera
            if pending_publish and not dry_run:
                print(f"  (Auto-publicerar pending artikel: {pending_publish['title'][:50]})")
                result = publish_article(
                    title=pending_publish["title"],
                    content=pending_publish["content"],
                    meta_description=pending_publish["meta_description"],
                    slug=pending_publish["slug"],
                )
                print(f"  {result}")
                if "✓" in result:
                    articles_published += 1
                    url = result.replace("✓ Publicerad: ", "").replace("✓ Uppdaterad: ", "").strip()
                    log_published_content(pending_publish["title"], url, "auto-publicerad")
                pending_publish = None

            final_response = assistant_content
            print(f"\n✅ Klar efter {iteration} iterationer ({articles_published} artiklar publicerade)")
            if final_response:
                print(f"\n{final_response[:500]}")
            break

        # Kör tool calls
        tool_results = []
        for tc in msg.message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                result = f"FEL: Ogiltigt JSON i tool call: {e}"
                tool_results.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue

            print(f"  → {name}({', '.join(f'{k}={repr(str(v))[:50]}' for k,v in args.items())})")

            if name == "publish_written_article":
                if dry_run:
                    result = f"[DRY RUN] Skulle publicera: {pending_publish['title'] if pending_publish else 'ingen artikel redo'}"
                elif pending_publish:
                    result = publish_article(
                        title=pending_publish["title"],
                        content=pending_publish["content"],
                        meta_description=pending_publish["meta_description"],
                        slug=pending_publish["slug"],
                        update_url=args.get("update_url", ""),
                        category_ids=args.get("category_ids", []),
                        featured_media_id=args.get("featured_media_id", 0),
                    )
                    if "✓" in result:
                        articles_published += 1
                        url = result.replace("✓ Publicerad: ", "").replace("✓ Uppdaterad: ", "").strip()
                        log_published_content(
                            title=pending_publish["title"],
                            url=url,
                            keyword=args.get("keyword", ""),
                            content_type="Optimerad" if args.get("update_url") else "Ny artikel"
                        )
                    pending_publish = None
                else:
                    result = "FEL: Ingen artikel redo att publicera. Skriv artikeln först."
            else:
                result = execute_tool(name, args)

            print(f"     {str(result)[:100]}{'...' if len(str(result)) > 100 else ''}")
            tool_results.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

        messages.extend(tool_results)

    else:
        print(f"⚠️  Max iterationer nådda")

    return final_response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_agent(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
