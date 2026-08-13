"""Pull the industry taxonomy from the sibling property so the categories
we list here match the ones already published across the network."""
import json
import re
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ENV = Path(r"C:\Users\Sistemas\AIS-OS\projects\lean-labs\factor8_app\.env")
FC = next(m.group(1) for m in
          (re.search(r"(fc-[A-Za-z0-9]+)", l) for l in
           ENV.read_text(encoding="utf-8", errors="ignore").splitlines()) if m)

SKIP = {"records", "topics", "contributors", "industries", "about",
        "submit", "api", "search", "main-content"}

r = httpx.post("https://api.firecrawl.dev/v2/scrape",
               headers={"Authorization": f"Bearer {FC}",
                        "Content-Type": "application/json"},
               json={"url": "https://www.answerstack.io/industries",
                     "formats": ["markdown"], "onlyMainContent": True,
                     "waitFor": 4000, "timeout": 70000}, timeout=150.0)
md = (r.json().get("data") or {}).get("markdown") or ""

out, seen = [], set()
for m in re.finditer(r"\[([^\]]+)\]\(https://www\.answerstack\.io/([a-z0-9-]+)\)", md):
    label, slug = m.group(1), m.group(2)
    if slug in SKIP or slug in seen:
        continue
    # link text carries the name then a topic count on continuation lines
    name = re.split(r"\\+\s*\n", label)[0].strip().rstrip("\\").strip()
    if not name or not name[0].isupper() or len(name) > 40:
        continue
    seen.add(slug)
    out.append({"name": name, "slug": slug})

(HERE / "data" / "_taxonomy.json").write_text(
    json.dumps(out, indent=2), encoding="utf-8")
print(f"{len(out)} industries")
for c in out:
    print(f"  {c['name']}")
