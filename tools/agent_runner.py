"""
Agent Runner — Villalife SEO
Kör Claude som en riktig agent med tool use.
Claude bestämmer själv strategi, ordning och antal artiklar baserat på data.

Usage:
  python tools/agent_runner.py
  python tools/agent_runner.py --dry-run
"""

import argparse
import os
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from agent_tools import TOOL_DEFINITIONS, execute_tool

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=os.getenv("OPENROUTER_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")

MAX_ITERATIONS = 20  # Säkerhetsgräns för agentic loop

SYSTEM_PROMPT = """Du är en autonom SEO-agent för Villalife.se — en svensk sajt om villa, hus, bostad, trädgård och renovering.

Ditt uppdrag varje dag:
1. Hämta aktuell GSC-data och analysera möjligheterna
2. Välj de 3 artiklar/sidor med störst potential att förbättra trafik och affiliate-intäkter
3. För quick wins och content gaps: läs befintlig artikel, skriv förbättrad version, publicera
4. För keyword gaps: skriv ny artikel från scratch för sökfrasen
5. Logga allt i dashboarden

Riktlinjer för innehåll:
- Alltid svenska, naturlig ton
- Minst 1200 ord per artikel
- Tydliga H2/H3-rubriker med relaterade sökfraser
- Praktiska tips och konkret information
- SEO-optimerad titel och meta description
- Undvik keyword stuffing

Prioriteringsordning:
1. Quick wins (position 11-30) — störst chans att klättra snabbt
2. CTR-problem — lätt att fixa, snabb effekt
3. Content gaps (position 31-60) — kräver mer arbete men stor potential
4. Nya artiklar för keyword gaps — bygger långsiktig trafik

Logga varje publicerad artikel i dashboarden.
När du är klar — summera kort vad du gjort och varför."""


def run_agent(dry_run: bool = False) -> str:
    """Kör Claude-agenten med full tool use. Returnerar slutsummering."""

    print(f"\n{'='*50}")
    print(f"VILLALIFE SEO AGENT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if dry_run:
        print("[DRY RUN] Simulerar körning utan att publicera\n")

    messages = [
        {
            "role": "user",
            "content": f"""Kör dagens SEO-arbete för Villalife.se.
Datum: {datetime.now().strftime('%Y-%m-%d')}
{"OBS: Detta är en dry-run. Analysera och planera men publicera INTE." if dry_run else ""}

Börja med att hämta GSC-data, analysera situationen och beskriv kort din strategi innan du börjar."""
        }
    ]

    iteration = 0
    final_response = ""

    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"[Iteration {iteration}]")

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
            } for t in TOOL_DEFINITIONS],
            tool_choice="auto",
            max_tokens=8000,
        )

        msg = response.choices[0]
        finish_reason = msg.finish_reason

        # Lägg till assistentens svar i historiken
        messages.append({
            "role": "assistant",
            "content": msg.message.content or "",
            **({"tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in (msg.message.tool_calls or [])
            ]} if msg.message.tool_calls else {})
        })

        # Inga fler tool calls — agenten är klar
        if finish_reason == "stop" or not msg.message.tool_calls:
            final_response = msg.message.content or ""
            print(f"\n✅ Agent klar efter {iteration} iterationer\n")
            print(final_response)
            break

        # Kör verktygen
        tool_results = []
        for tool_call in msg.message.tool_calls:
            name = tool_call.function.name
            import json
            args = json.loads(tool_call.function.arguments)

            print(f"  → Verktyg: {name}({', '.join(f'{k}={repr(v)[:50]}' for k,v in args.items())})")

            if dry_run and name == "publish_article":
                result = f"[DRY RUN] Skulle publicera: {args.get('title', '')}"
            else:
                result = execute_tool(name, args)

            print(f"     {result[:100]}{'...' if len(result) > 100 else ''}")

            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })

        messages.extend(tool_results)

    else:
        print(f"⚠️ Max iterationer ({MAX_ITERATIONS}) nådda")
        final_response = "Max iterationer nådda."

    return final_response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = run_agent(dry_run=args.dry_run)
    return result


if __name__ == "__main__":
    main()
