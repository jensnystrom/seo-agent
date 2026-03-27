"""
GSC Audit Tool
Analyserar GSC-data och identifierar optimeringsmöjligheter.
Input:  .tmp/gsc_pages.json, .tmp/gsc_queries.json, .tmp/gsc_combos.json
Output: .tmp/audit_opportunities.json, .tmp/audit_summary.txt
"""

import json
import os

INPUT_DIR = ".tmp"
OUTPUT_DIR = ".tmp"


def load(filename):
    path = os.path.join(INPUT_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def categorize_pages(pages):
    """
    Kategoriserar sidor i tre prioritetsgrupper:

    QUICK WIN   — position 11-30, impressioner > 50
                  Nära första sidan, behöver bara lite push.
                  Åtgärd: förbättra title/meta + stärk innehållet.

    CONTENT GAP — position 31-60, impressioner > 100
                  Syns men rankar för långt ner.
                  Åtgärd: skriv om/expandera artikeln ordentligt.

    CTR ISSUE   — position 1-20, CTR < 2%
                  Rankar bra men ingen klickar.
                  Åtgärd: optimera title och meta description.
    """
    quick_wins = []
    content_gaps = []
    ctr_issues = []

    for p in pages:
        pos = p["position"]
        imp = p["impressions"]
        ctr = p["ctr"]
        clicks = p["clicks"]

        if 11 <= pos <= 30 and imp >= 50:
            p["opportunity"] = "QUICK WIN"
            p["action"] = "Förbättra title/meta + stärk innehållet"
            p["priority_score"] = round(imp / pos, 1)
            quick_wins.append(p)

        elif 31 <= pos <= 60 and imp >= 100:
            p["opportunity"] = "CONTENT GAP"
            p["action"] = "Skriv om och expandera artikeln"
            p["priority_score"] = round(imp / pos, 1)
            content_gaps.append(p)

        elif pos <= 20 and ctr < 2.0 and imp >= 30:
            p["opportunity"] = "CTR ISSUE"
            p["action"] = "Optimera title och meta description"
            p["priority_score"] = round(imp * (2.0 - ctr), 1)
            ctr_issues.append(p)

    # Sortera efter priority_score (högst potential först)
    quick_wins.sort(key=lambda x: x["priority_score"], reverse=True)
    content_gaps.sort(key=lambda x: x["priority_score"], reverse=True)
    ctr_issues.sort(key=lambda x: x["priority_score"], reverse=True)

    return quick_wins, content_gaps, ctr_issues


def find_keyword_gaps(queries, pages):
    """
    Hittar sökfraser med hög exponering men ingen stark sida.
    Dessa är kandidater för NYA artiklar.
    """
    page_urls = {p["page"] for p in pages}

    # Queries med många visningar men låg position och inga klick
    gaps = []
    for q in queries:
        if q["impressions"] >= 50 and q["clicks"] == 0 and q["position"] > 20:
            gaps.append({
                "query": q["query"],
                "impressions": q["impressions"],
                "position": q["position"],
                "opportunity": "NEW CONTENT",
                "action": "Skapa ny artikel riktad mot denna sökfras",
                "priority_score": round(q["impressions"] / q["position"], 1)
            })

    gaps.sort(key=lambda x: x["priority_score"], reverse=True)
    return gaps[:50]  # Top 50 räcker


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pages = load("gsc_pages.json")
    queries = load("gsc_queries.json")

    quick_wins, content_gaps, ctr_issues = categorize_pages(pages)
    keyword_gaps = find_keyword_gaps(queries, pages)

    # Samla allt
    all_opportunities = {
        "quick_wins": quick_wins[:20],
        "content_gaps": content_gaps[:20],
        "ctr_issues": ctr_issues[:20],
        "new_content": keyword_gaps[:20],
    }

    with open(f"{OUTPUT_DIR}/audit_opportunities.json", "w", encoding="utf-8") as f:
        json.dump(all_opportunities, f, ensure_ascii=False, indent=2)

    # Skriv läsbar summering
    lines = []
    lines.append("=" * 60)
    lines.append("VILLALIFE.SE — AUDIT RAPPORT")
    lines.append("=" * 60)

    lines.append(f"\n🎯 QUICK WINS ({len(quick_wins)} sidor)")
    lines.append("   Position 11-30 med bra exponering — nära sida 1")
    for p in quick_wins[:10]:
        lines.append(f"   pos {p['position']:5.1f} | {p['impressions']:5} visn | {p['page']}")

    lines.append(f"\n📝 CONTENT GAPS ({len(content_gaps)} sidor)")
    lines.append("   Position 31-60 — behöver bättre innehåll")
    for p in content_gaps[:10]:
        lines.append(f"   pos {p['position']:5.1f} | {p['impressions']:5} visn | {p['page']}")

    lines.append(f"\n👆 CTR-PROBLEM ({len(ctr_issues)} sidor)")
    lines.append("   Rankar men ingen klickar — dålig title/meta")
    for p in ctr_issues[:10]:
        lines.append(f"   pos {p['position']:5.1f} | CTR {p['ctr']:4.1f}% | {p['page']}")

    lines.append(f"\n🆕 NYA ARTIKLAR ({len(keyword_gaps)} sökfraser)")
    lines.append("   Sökfraser vi syns för men saknar bra sida")
    for q in keyword_gaps[:10]:
        lines.append(f"   pos {q['position']:5.1f} | {q['impressions']:5} visn | {q['query']}")

    lines.append("\n" + "=" * 60)
    lines.append(f"TOTALT: {len(quick_wins) + len(content_gaps) + len(ctr_issues)} sidor att optimera")
    lines.append(f"        {len(keyword_gaps)} nya artiklar att skriva")
    lines.append("=" * 60)

    summary = "\n".join(lines)
    print(summary)

    with open(f"{OUTPUT_DIR}/audit_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)

    print(f"\nSparat till {OUTPUT_DIR}/audit_opportunities.json")


if __name__ == "__main__":
    main()
