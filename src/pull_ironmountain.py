"""Pull Iron Mountain's platform figures for the methodology examples.

Kevin named it the prime bad example: 1.6 on Trustpilot against 4.5 on
Gartner. It is not indexed, so the figures go to data/_examples.json rather
than the vendor set, and the page will label it accordingly.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ENV = Path(r"C:\Users\Sistemas\AIS-OS\projects\lean-labs\factor8_app\.env")
_L = ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
FC = next(m.group(1) for m in (re.search(r"(fc-[A-Za-z0-9]+)", l) for l in _L) if m)
DFS = next(l.split("=", 1)[1].strip() for l in _L
           if l.startswith("FACTOR8_DATAFORSEO_AUTH="))
FH = {"Authorization": f"Bearer {FC}", "Content-Type": "application/json"}
DH = {"Authorization": f"Basic {DFS}", "Content-Type": "application/json"}
NOW = datetime.now(timezone.utc).isoformat()

out = {"name": "Iron Mountain", "captured_at": NOW, "portals": {}}

# ---- Trustpilot ----------------------------------------------------------
r = httpx.post("https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
               headers=DH, json=[{"domain": "ironmountain.com", "depth": 10}], timeout=90)
tid = r.json()["tasks"][0]["id"]
for _ in range(14):
    time.sleep(10)
    g = httpx.get(f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{tid}",
                  headers=DH, timeout=90).json()
    t = g["tasks"][0]
    if t.get("result"):
        res = t["result"][0]
        out["portals"]["trustpilot"] = {
            "label": "Trustpilot",
            "rating": (res.get("rating") or {}).get("value"),
            "count": res.get("reviews_count"),
            "url": res.get("check_url") or "https://www.trustpilot.com/review/ironmountain.com",
            "captured_at": NOW}
        break

# ---- Gartner Peer Insights ----------------------------------------------
r = httpx.post("https://api.firecrawl.dev/v2/search", headers=FH,
               json={"query": "Iron Mountain site:gartner.com/reviews/product", "limit": 6},
               timeout=90)
d = r.json().get("data")
w = d.get("web", d) if isinstance(d, dict) else d
urls = [h.get("url", "") for h in (w or []) if "gartner.com/reviews/product" in h.get("url", "")]
for u in urls[:3]:
    u = u.split("?")[0]
    sc = httpx.post("https://api.firecrawl.dev/v2/scrape", headers=FH,
                    json={"url": u, "formats": ["markdown"], "onlyMainContent": False,
                          "waitFor": 3500, "timeout": 65000}, timeout=150)
    md = ((sc.json().get("data") or {}).get("markdown")) or "" if sc.status_code == 200 else ""
    mr = re.search(r"\n([0-5]\.\d)\s*\n+\s*\(([\d,]+)\s*Ratings?\)", md)
    if mr:
        out["portals"]["gartner"] = {
            "label": "Gartner Peer Insights", "rating": float(mr.group(1)),
            "count": int(mr.group(2).replace(",", "")), "url": u, "captured_at": NOW}
        break

(HERE / "data" / "_examples.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
