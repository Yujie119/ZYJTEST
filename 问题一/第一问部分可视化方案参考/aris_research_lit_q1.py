"""ARIS research-lit style metadata retrieval for Q1-like journals.

OpenAlex is used only for discovery and metadata. Quartile labels are kept
conservative in the report and should be checked against the current
China-Academy/JCR release before a manuscript makes an explicit Q1 claim.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
import requests

OUT = Path(__file__).resolve().parent
QUERIES = [
    "drone delivery energy vehicle routing",
    "UAV disaster relief logistics multi objective",
    "drone routing uncertainty robust optimization",
    "UAV terrain GIS path planning elevation",
    "UAV emergency relief distribution",
    "drone delivery battery energy payload",
    "humanitarian logistics trucks UAV transportation",
    "UAV coverage path planning remote sensing terrain",
]

def main():
    session = requests.Session()
    session.headers.update({"User-Agent": "ARIS-research-lit/1.0 (mailto:research@example.com)"})
    out = {}
    for q in QUERIES:
        for attempt in range(4):
            r = session.get(
                "https://api.openalex.org/works",
                params={
                    "search": q,
                    "filter": "from_publication_date:2017-01-01,type:article",
                    "per-page": 50,
                    "mailto": "research@example.com",
                },
                timeout=45,
            )
            if r.status_code == 200:
                out[q] = r.json().get("results", [])
                break
            if r.status_code == 429:
                time.sleep(2.5 * (attempt + 1))
                continue
            out[q] = {"error": r.status_code, "text": r.text[:500]}
            break
        time.sleep(1.2)
    (OUT / "aris_research_lit_q1_raw.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Deduplicate by DOI/title and retain compact fields for manual screening.
    seen = {}
    for q, rows in out.items():
        if not isinstance(rows, list):
            continue
        for x in rows:
            src = (x.get("primary_location") or {}).get("source") or {}
            doi = (x.get("doi") or "").lower()
            key = doi or (x.get("title") or "").lower()
            if not key:
                continue
            seen[key] = {
                "query": q,
                "title": x.get("title"),
                "year": x.get("publication_year"),
                "journal": src.get("display_name"),
                "doi": x.get("doi"),
                "cited_by": x.get("cited_by_count"),
                "oa": x.get("open_access", {}).get("is_oa"),
                "pdf": (x.get("best_oa_location") or {}).get("pdf_url"),
                "landing": (x.get("best_oa_location") or {}).get("landing_page_url"),
            }
    rows = sorted(seen.values(), key=lambda x: (x.get("journal") or "", -(x.get("cited_by") or 0)))
    (OUT / "aris_research_lit_q1_compact.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"queries={len(QUERIES)} records={len(rows)}")

if __name__ == "__main__":
    main()
