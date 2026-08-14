"""Add a category of B2B service companies.

Kevin: "it's not software reviews. it's B2B companies." Software vendors live
on G2, Capterra and Gartner. Service companies do not, which is why Clutch
returned nothing for the sixteen software products. They live on Clutch,
Google and Trustpilot instead.

For a service company the Google listing IS the business, so unlike a software
vendor's office listing it belongs in the rating.

Writes aggregate figures into data/_all.json and review-level records into
data/reviews/, matching the shape the existing pipeline already reads.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ENV = Path(r"C:\Users\Sistemas\AIS-OS\projects\lean-labs\factor8_app\.env")
_L = ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
FC_KEY = next(m.group(1) for m in (re.search(r"(fc-[A-Za-z0-9]+)", l) for l in _L) if m)
DFS_AUTH = next(l.split("=", 1)[1].strip() for l in _L
                if l.startswith("FACTOR8_DATAFORSEO_AUTH="))
FC = {"Authorization": f"Bearer {FC_KEY}", "Content-Type": "application/json"}
DFS = {"Authorization": f"Basic {DFS_AUTH}", "Content-Type": "application/json"}
NOW = datetime.now(timezone.utc).isoformat()
SEM = asyncio.Semaphore(4)
Q = "\u201c"

CATEGORY = ("digital-marketing", "Digital Marketing")
COMPANIES = [
    ("webfx", "WebFX", "webfx.com"),
    ("smartsites", "SmartSites", "smartsites.com"),
    ("disruptive-advertising", "Disruptive Advertising", "disruptiveadvertising.com"),
    ("ninjapromo", "NinjaPromo", "ninjapromo.io"),
    ("lounge-lizard", "Lounge Lizard", "loungelizard.com"),
    ("thrive-internet-marketing-agency", "Thrive Internet Marketing Agency", "thriveagency.com"),
    ("coalition-technologies", "Coalition Technologies", "coalitiontechnologies.com"),
    ("ignite-visibility", "Ignite Visibility", "ignitevisibility.com"),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean(t, words=40):
    t = re.sub(r"\s+", " ", t or "").strip().strip('"' + Q + "\u201d")
    p = t.split(" ")
    return t if len(p) <= words else " ".join(p[:words]).rstrip(",.;:") + "\u2026"


async def post(c, url, h, body, t=90.0):
    for i in range(3):
        try:
            r = await c.post(url, headers=h, json=body, timeout=t)
            if r.status_code == 200 or (r.status_code < 500 and r.status_code != 429):
                return r
        except Exception:
            pass
        await asyncio.sleep(2 * (i + 1))
    return None


# ---------------------------------------------------------------- Clutch
async def clutch(c, name):
    empty = {"portal": "clutch", "status": "no_listing", "rating": None, "count": None,
             "quotes": [], "url": None, "captured_at": NOW}, []
    async with SEM:
        r = await post(c, "https://api.firecrawl.dev/v2/search", FC,
                       {"query": f'"{name}" site:clutch.co/profile', "limit": 6})
    if not r or r.status_code != 200:
        return empty
    d = r.json().get("data"); w = d.get("web", d) if isinstance(d, dict) else d
    for u in [h.get("url", "") for h in (w or [])]:
        if "clutch.co/profile/" not in u:
            continue
        slug = norm(u.rsplit("/", 1)[-1].split("?")[0])
        if slug != norm(name) and not slug.startswith(norm(name)[:12]):
            continue
        u = u.split("?")[0]
        async with SEM:
            sc = await post(c, "https://api.firecrawl.dev/v2/scrape", FC,
                            {"url": u, "formats": ["markdown"], "onlyMainContent": True,
                             "waitFor": 4000, "timeout": 70000}, t=150.0)
        if not sc or sc.status_code != 200:
            continue
        md = ((sc.json().get("data") or {}).get("markdown")) or ""
        m = re.search(r"Overall Review Rating\s*\n+\s*([0-5]\.\d)\s*\n+\s*\(([\d,]+)\)", md)
        if not m:
            continue
        subs = dict(re.findall(r"-\s*(Quality|Schedule|Cost|Willing to Refer)\s*\n\s*([0-5]\.\d)", md))
        reviews = []
        # each review block: a date range, a 5.0, then a quoted headline
        for b in re.finditer(
                r"([A-Z][a-z]{2}\.?\s*\d{4})\s*-\s*[^\n]{2,24}\n+\s*([0-5]\.\d)\s*\n+"
                r"(?:Quality[\s\S]{0,120}?)?\"([^\"]{25,400})\"", md):
            reviews.append({
                "portal": "Clutch", "review_id": None, "date": b.group(1).replace(".", ""),
                "rating": float(b.group(2)), "title": None,
                "text": clean(b.group(3), 60), "role": None, "company_size": None,
                "source_url": u, "sample_order": "page"})
        return ({"portal": "clutch", "status": "ok", "rating": float(m.group(1)),
                 "count": int(m.group(2).replace(",", "")), "sub_ratings": subs or None,
                 "quotes": [{**r, "text": clean(r["text"])} for r in reviews[:4]],
                 "url": u, "captured_at": NOW}, reviews)
    return empty


# ------------------------------------------------------------ Trustpilot
async def trustpilot(c, domain):
    empty = {"portal": "trustpilot", "status": "no_listing", "rating": None,
             "count": None, "quotes": [], "url": None, "captured_at": NOW}, []
    async with SEM:
        r = await post(c, "https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
                       DFS, [{"domain": domain, "depth": 60, "sort_by": "recency"}])
    if not r:
        return empty
    try:
        tid = r.json()["tasks"][0]["id"]
    except Exception:
        return empty
    for _ in range(16):
        await asyncio.sleep(10)
        async with SEM:
            g = await c.get(f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{tid}",
                            headers=DFS, timeout=90.0)
        try:
            t = g.json()["tasks"][0]
        except Exception:
            continue
        if not t.get("result"):
            continue
        res = t["result"][0]
        if not (res.get("rating") or {}).get("value"):
            return empty
        url = res.get("check_url") or f"https://www.trustpilot.com/review/{domain}"
        rv = [{"portal": "Trustpilot", "review_id": None,
               "date": (i.get("timestamp") or "")[:10] or None,
               "rating": (i.get("rating") or {}).get("value"),
               "title": (i.get("title") or "").strip() or None,
               "text": clean(i.get("review_text") or "", 60) or None,
               "role": None, "company_size": None, "source_url": url,
               "sample_order": "recency"} for i in (res.get("items") or [])]
        return ({"portal": "trustpilot", "status": "ok",
                 "rating": res["rating"]["value"], "count": res.get("reviews_count"),
                 "quotes": [{**x, "text": clean(x["text"] or "")} for x in rv if x["text"]][:4],
                 "url": url, "captured_at": NOW}, rv)
    return empty


# ---------------------------------------------------------------- Google
async def google(c, name):
    empty = {"portal": "google", "status": "no_listing", "rating": None, "count": None,
             "quotes": [], "url": None, "captured_at": NOW}, []
    async with SEM:
        r = await post(c, "https://api.dataforseo.com/v3/business_data/google/my_business_info/task_post",
                       DFS, [{"keyword": name, "location_name": "United States",
                              "language_code": "en"}])
    if not r:
        return empty
    try:
        tid = r.json()["tasks"][0]["id"]
    except Exception:
        return empty
    info = None
    for _ in range(14):
        await asyncio.sleep(9)
        async with SEM:
            g = await c.get(f"https://api.dataforseo.com/v3/business_data/google/my_business_info/task_get/{tid}",
                            headers=DFS, timeout=90.0)
        try:
            t = g.json()["tasks"][0]
        except Exception:
            continue
        if t.get("result"):
            items = (t["result"][0] or {}).get("items") or []
            if items and items[0].get("title") and norm(name)[:8] in norm(items[0]["title"]):
                info = items[0]
            break
    if not info or not (info.get("rating") or {}).get("value"):
        return empty
    rt = info["rating"]
    # pull the review text too
    async with SEM:
        r2 = await post(c, "https://api.dataforseo.com/v3/business_data/google/reviews/task_post",
                        DFS, [{"keyword": name, "location_name": "United States",
                               "language_code": "en", "depth": 40, "sort_by": "newest"}])
    rv = []
    if r2:
        try:
            tid2 = r2.json()["tasks"][0]["id"]
            for _ in range(14):
                await asyncio.sleep(9)
                async with SEM:
                    g2 = await c.get(f"https://api.dataforseo.com/v3/business_data/google/reviews/task_get/{tid2}",
                                     headers=DFS, timeout=90.0)
                t2 = g2.json()["tasks"][0]
                if t2.get("result"):
                    for i in (t2["result"][0].get("items") or []):
                        rv.append({"portal": "Google Business Profile", "review_id": None,
                                   "date": (i.get("timestamp") or "")[:10] or None,
                                   "rating": (i.get("rating") or {}).get("value"),
                                   "title": None,
                                   "text": clean(i.get("review_text") or "", 60) or None,
                                   "role": None, "company_size": None,
                                   "source_url": info.get("url") or "", "sample_order": "newest"})
                    break
        except Exception:
            pass
    return ({"portal": "google", "status": "ok", "rating": rt["value"],
             "count": rt.get("votes_count"),
             "quotes": [{**x, "text": clean(x["text"] or "")} for x in rv if x["text"]][:4],
             "url": info.get("url"), "captured_at": NOW,
             "category": info.get("category")}, rv)


async def main():
    data = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
    cat_slug, cat_name = CATEGORY
    data["categories"][cat_slug] = {
        "name": cat_name,
        "vendors": [[s, n, d] for s, n, d in COMPANIES],
        "kind": "services",
    }
    for k in data["categories"]:
        data["categories"][k].setdefault("kind", "software")

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=10)) as c:
        res = await asyncio.gather(*[
            asyncio.gather(clutch(c, n), trustpilot(c, d), google(c, n))
            for _, n, d in COMPANIES])

    outdir = HERE / "data" / "reviews"
    outdir.mkdir(parents=True, exist_ok=True)
    for (slug, name, domain), ((cl, cl_r), (tp, tp_r), (go, go_r)) in zip(COMPANIES, res):
        rec = {"slug": slug, "name": name, "domain": domain, "category": cat_slug,
               "category_name": cat_name, "captured_at": NOW, "kind": "services",
               "portals": {"clutch": cl, "trustpilot": tp, "google": go}}
        data["vendors"][slug] = rec
        (HERE / "data" / f"{slug}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        reviews = cl_r + tp_r + go_r
        (outdir / f"{slug}.json").write_text(
            json.dumps({"slug": slug, "captured_at": NOW, "reviews": reviews}, indent=2),
            encoding="utf-8")
        live = [p for p in ("clutch", "trustpilot", "google")
                if rec["portals"][p]["rating"] is not None]
        print(f"  {name[:32]:<34} platforms={len(live)} ({','.join(live)})  reviews={len(reviews)}")

    (HERE / "data" / "_all.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nadded {len(COMPANIES)} companies to {cat_name}")


if __name__ == "__main__":
    asyncio.run(main())
