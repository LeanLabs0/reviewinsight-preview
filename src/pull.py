"""Pull real review data for the ReviewInsight preview.

Two categories, ~8 vendors each. All four portals per vendor.
Routes proven 2026-08-11: DataForSEO for Trustpilot, Firecrawl for the rest.

Every field carries its source URL and capture date. A field we cannot read
is None, never 0 - a zero would read as a real measurement.
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

_lines = ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
FC_KEY = next(m.group(1) for m in (re.search(r"(fc-[A-Za-z0-9]+)", l) for l in _lines) if m)
DFS_AUTH = next(l.split("=", 1)[1].strip() for l in _lines
                if l.startswith("FACTOR8_DATAFORSEO_AUTH="))

FC = {"Authorization": f"Bearer {FC_KEY}", "Content-Type": "application/json"}
DFS = {"Authorization": f"Basic {DFS_AUTH}", "Content-Type": "application/json"}

NOW = datetime.now(timezone.utc).isoformat()

CATEGORIES = {
    "marketing-automation": {
        "name": "Marketing Automation",
        "vendors": [
            ("hubspot-marketing-hub", "HubSpot Marketing Hub", "hubspot.com"),
            ("klaviyo", "Klaviyo", "klaviyo.com"),
            ("adobe-marketo-engage", "Adobe Marketo Engage", "marketo.com"),
            ("mailchimp", "Mailchimp", "mailchimp.com"),
            ("activecampaign", "ActiveCampaign", "activecampaign.com"),
            ("brevo", "Brevo", "brevo.com"),
            ("braze", "Braze", "braze.com"),
            ("iterable", "Iterable", "iterable.com"),
        ],
    },
    "project-management": {
        "name": "Project Management",
        "vendors": [
            ("monday-com", "monday.com", "monday.com"),
            ("asana", "Asana", "asana.com"),
            ("clickup", "ClickUp", "clickup.com"),
            ("wrike", "Wrike", "wrike.com"),
            ("smartsheet", "Smartsheet", "smartsheet.com"),
            ("notion", "Notion", "notion.so"),
            ("jira", "Jira", "atlassian.com"),
            ("basecamp", "Basecamp", "basecamp.com"),
        ],
    },
}

FC_SEM = asyncio.Semaphore(3)
DFS_SEM = asyncio.Semaphore(3)


async def _post(client, url, *, headers, json_body, timeout, tries=3):
    """POST with backoff. Transport drops are common at this concurrency."""
    for attempt in range(tries):
        try:
            r = await client.post(url, headers=headers, json=json_body, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code < 500 and r.status_code != 429:
                return r
        except Exception:
            pass
        await asyncio.sleep(2 * (attempt + 1))
    return None


async def _get(client, url, *, headers, timeout, tries=3):
    for attempt in range(tries):
        try:
            r = await client.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        await asyncio.sleep(2 * (attempt + 1))
    return None


async def fc_search(client: httpx.AsyncClient, query: str, limit: int = 6) -> list[str]:
    async with FC_SEM:
        r = await _post(client, "https://api.firecrawl.dev/v2/search", headers=FC,
                        json_body={"query": query, "limit": limit}, timeout=90.0)
        if r is None or r.status_code != 200:
            return []
        try:
            d = r.json().get("data")
            w = d.get("web", d) if isinstance(d, dict) else d
            return [h.get("url", "") for h in (w or [])]
        except Exception:
            return []


async def fc_scrape(client: httpx.AsyncClient, url: str) -> str:
    async with FC_SEM:
        r = await _post(client, "https://api.firecrawl.dev/v2/scrape", headers=FC,
                        json_body={"url": url, "formats": ["markdown"],
                                   "onlyMainContent": False, "waitFor": 3500,
                                   "timeout": 65000}, timeout=150.0)
        if r is None or r.status_code != 200:
            return ""
        try:
            return ((r.json().get("data") or {}).get("markdown")) or ""
        except Exception:
            return ""


def pick(urls: list[str], must: str,
         avoid=("alternatives", "competitors", "/pricing", "/compare", "gcom.pdo")) -> str | None:
    for u in urls:
        if must in u and not any(a in u for a in avoid):
            return u.split("?")[0]
    return None


def clean(txt: str, words: int = 40) -> str:
    """Trim a quote to ~40 words at a word boundary."""
    t = re.sub(r"\s+", " ", txt or "").strip().strip('"\u201c\u201d')
    parts = t.split(" ")
    return t if len(parts) <= words else " ".join(parts[:words]).rstrip(",.;:") + "\u2026"


# ---------------------------------------------------------------- G2
async def get_g2(client, display: str) -> dict:
    urls = await fc_search(client, f"{display} G2 reviews")
    u = pick(urls, "g2.com/products/")
    if not u:
        return {"portal": "g2", "status": "unresolved", "rating": None, "count": None,
                "quotes": [], "url": None, "captured_at": NOW}
    u = u.rstrip("/")
    if not u.endswith("reviews"):
        u += "/reviews"
    md = await fc_scrape(client, u)
    if not md:
        return {"portal": "g2", "status": "fetch_failed", "rating": None, "count": None,
                "quotes": [], "url": u, "captured_at": NOW}

    m = re.search(r"\n([0-5]\.\d)\s*\n+\s*([\d,]+)\s+reviews", md)
    rating = float(m.group(1)) if m else None
    count = int(m.group(2).replace(",", "")) if m else None

    quotes = []
    # Each G2 review block: role / company-size / date / "title" / rating / like text
    for blk in re.finditer(
            r"\n([A-Z][^\n]{2,60})\n\n((?:Small-Business|Mid-Market|Enterprise)[^\n]*)\n\n"
            r"(\d{1,2}/\d{1,2}/\d{4})\n(?:.*?)\n\"([^\"]{15,140})\"\n\n([0-5](?:\.\d)?)/5\n\n"
            r"What do you like best[^\n]*\n\n([^\n]{60,})", md, re.S):
        quotes.append({
            "text": clean(blk.group(6)), "title": blk.group(4).strip(),
            "role": blk.group(1).strip(), "company_size": blk.group(2).strip(),
            "date": blk.group(3), "rating": float(blk.group(5)),
            "portal": "G2", "source_url": u,
        })
        if len(quotes) >= 4:
            break
    return {"portal": "g2", "status": "ok" if rating else "parse_failed",
            "rating": rating, "count": count, "quotes": quotes,
            "url": u, "captured_at": NOW}


# ---------------------------------------------------------- Capterra
async def get_capterra(client, display: str) -> dict:
    urls = await fc_search(client, f"{display} Capterra reviews")
    u = pick(urls, "capterra.com/p/")
    if not u:
        return {"portal": "capterra", "status": "unresolved", "rating": None,
                "count": None, "sub_ratings": None, "quotes": [], "url": None,
                "captured_at": NOW}
    u = u.rstrip("/")
    if not u.endswith("/reviews"):
        u += "/reviews"
    u += "/"
    md = await fc_scrape(client, u)
    if not md:
        return {"portal": "capterra", "status": "fetch_failed", "rating": None,
                "count": None, "sub_ratings": None, "quotes": [], "url": u,
                "captured_at": NOW}

    m = re.search(r"\n([0-5]\.\d)\s*\(([\d,]+)\)", md)
    rating = float(m.group(1)) if m else None
    count = int(m.group(2).replace(",", "")) if m else None

    # Aggregate sub-ratings live between the overall rating and the first review
    # card. Scope the slice, require all four, sanity-check against overall.
    subs = None
    if m:
        head = md[m.end(): m.end() + 2500]
        cut = re.search(r"\n(?:[A-Z]{2}\n|Verified (?:User|LinkedIn User))", head)
        if cut:
            head = head[: cut.start()]
        found = {}
        for lbl in ("Ease of use", "Customer Service", "Features", "Value for Money"):
            sm = re.search(re.escape(lbl) + r"\s*\n+\s*([0-5]\.\d)", head, re.I)
            if sm:
                found[lbl] = float(sm.group(1))
        # The reviews page publishes two of the four. Take what is genuinely
        # there, but only if it sits close to the overall rating - a wide gap
        # means we scraped a review card instead of the aggregate.
        if len(found) >= 2:
            vals = list(found.values())
            if abs(sum(vals) / len(vals) - rating) <= 0.5:
                subs = found

    # Capterra uses the SAME curly character to open and close a quote.
    quotes = []
    Q = "\u201c"
    for blk in re.finditer(
            rf"Verified[^\n]*\n\n([^\n]{{5,240}})\n\n{Q}([^{Q}]{{40,400}}){Q}\n\n"
            r"([A-Z][a-z]+ \d{1,2}, \d{4})", md):
        meta = blk.group(1).strip()
        size = None
        ms = re.search(r"([\d,]+\s*-\s*[\d,]+|\d[\d,]*\+?)\s*employees", meta)
        if ms:
            size = ms.group(1).replace(" ", "") + " employees"
        # Role runs until the lowercase/uppercase seam where the industry starts
        role = re.split(r"(?<=[a-z])(?=[A-Z])", meta)[0].strip() or None
        quotes.append({
            "text": clean(blk.group(2)), "title": None,
            "role": role, "company_size": size,
            "date": blk.group(3), "rating": None,
            "portal": "Capterra", "source_url": u,
        })
        if len(quotes) >= 4:
            break
    return {"portal": "capterra", "status": "ok" if rating else "parse_failed",
            "rating": rating, "count": count, "sub_ratings": subs,
            "quotes": quotes, "url": u, "captured_at": NOW}


# ----------------------------------------------------------- Gartner
async def get_gartner(client, display: str) -> dict:
    urls = await fc_search(client, f"{display} Gartner Peer Insights reviews")
    # Product pages carry the aggregate; vendor pages do not.
    u = pick(urls, "gartner.com/reviews/product/")
    if not u:
        urls += await fc_search(client, f"{display} site:gartner.com/reviews/market")
        u = pick(urls, "gartner.com/reviews/market/") or pick(urls, "gartner.com/reviews/")
    if not u:
        return {"portal": "gartner", "status": "unresolved", "rating": None,
                "count": None, "ratings_count": None, "quotes": [], "url": None,
                "captured_at": NOW}
    md = await fc_scrape(client, u)
    if not md:
        return {"portal": "gartner", "status": "fetch_failed", "rating": None,
                "count": None, "ratings_count": None, "quotes": [], "url": u,
                "captured_at": NOW}

    mr = re.search(r"\n([0-5]\.\d)\s*\n+\s*\(([\d,]+)\s*Ratings?\)", md)
    mc = re.search(r"Reviews and Ratings\s*\(([\d,]+)\)", md)
    rating = float(mr.group(1)) if mr else None
    ratings_count = int(mr.group(2).replace(",", "")) if mr else None
    count = int(mc.group(1).replace(",", "")) if mc else ratings_count

    # Gartner replaces most bodies with a placeholder. Titles, ratings, dates
    # and reviewer role are public - use those, never the gated bodies.
    PLACEHOLDER = "this text serves as a placeholder"
    quotes = []
    for blk in re.finditer(
            r"\n([A-Z][^\n]{2,60})\n\n([^\n]{3,60})\n\n(FAVORABLE|CRITICAL|NEUTRAL)\n\n"
            r"#{2,5}\s*\u201c([^\u201d]{15,160})\u201d\n\n([0-5]\.\d)\n\n"
            r"([A-Z][a-z]{2} \d{1,2}, \d{4})", md):
        quotes.append({
            "text": None, "title": blk.group(4).strip(),
            "role": blk.group(1).strip(), "company_size": blk.group(2).strip(),
            "date": blk.group(6), "rating": float(blk.group(5)),
            "sentiment": blk.group(3), "body_gated": True,
            "portal": "Gartner Peer Insights", "source_url": u,
        })
        if len(quotes) >= 4:
            break
    return {"portal": "gartner", "status": "ok" if rating else "parse_failed",
            "rating": rating, "count": count, "ratings_count": ratings_count,
            "quotes": quotes, "url": u, "captured_at": NOW,
            "bodies_gated": PLACEHOLDER in md.lower()}


# -------------------------------------------------------- Trustpilot
async def tp_post(client, domain: str) -> str | None:
    async with DFS_SEM:
        r = await _post(
            client,
            "https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
            headers=DFS,
            json_body=[{"domain": domain, "depth": 20, "sort_by": "recency"}],
            timeout=90.0)
    if r is None:
        return None
    try:
        return r.json()["tasks"][0]["id"]
    except Exception:
        return None


async def tp_get(client, tid: str, domain: str) -> dict:
    url = f"https://www.trustpilot.com/review/{domain}"
    for _ in range(14):
        async with DFS_SEM:
            r = await _get(
                client,
                f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{tid}",
                headers=DFS, timeout=90.0)
        if r is None:
            await asyncio.sleep(12)
            continue
        try:
            t = r.json()["tasks"][0]
        except Exception:
            await asyncio.sleep(12)
            continue
        if t.get("result"):
            res = t["result"][0]
            items = res.get("items") or []
            quotes = []
            for it in items:
                body = it.get("review_text") or ""
                if len(body) < 60:
                    continue
                ts = (it.get("timestamp") or "")[:10]
                quotes.append({
                    "text": clean(body), "title": (it.get("title") or "").strip() or None,
                    "role": None, "company_size": None, "date": ts,
                    "rating": (it.get("rating") or {}).get("value"),
                    "portal": "Trustpilot",
                    "source_url": res.get("check_url") or url,
                })
                if len(quotes) >= 4:
                    break
            return {"portal": "trustpilot", "status": "ok",
                    "rating": (res.get("rating") or {}).get("value"),
                    "count": res.get("reviews_count"), "quotes": quotes,
                    "url": res.get("check_url") or url, "captured_at": NOW}
        await asyncio.sleep(12)
    return {"portal": "trustpilot", "status": "fetch_failed", "rating": None,
            "count": None, "quotes": [], "url": url, "captured_at": NOW}


# --------------------------------------------------------------- run
async def main() -> None:
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with httpx.AsyncClient(limits=limits, http2=False) as client:
        jobs = [(slug, disp, dom, cat)
                for cat, meta in CATEGORIES.items()
                for slug, disp, dom in meta["vendors"]]

        print(f"posting {len(jobs)} Trustpilot tasks")
        tp_ids = await asyncio.gather(*[tp_post(client, d) for _, _, d, _ in jobs])

        print("fetching G2 / Capterra / Gartner")
        scraped = await asyncio.gather(*[
            asyncio.gather(get_g2(client, disp), get_capterra(client, disp),
                           get_gartner(client, disp))
            for _, disp, _, _ in jobs])

        print("collecting Trustpilot")
        tps = await asyncio.gather(*[
            tp_get(client, tid, dom) if tid else
            asyncio.sleep(0, {"portal": "trustpilot", "status": "fetch_failed",
                              "rating": None, "count": None, "quotes": [],
                              "url": None, "captured_at": NOW})
            for tid, (_, _, dom, _) in zip(tp_ids, jobs)])

        out = {}
        for (slug, disp, dom, cat), (g2, cap, gar), tp in zip(jobs, scraped, tps):
            rec = {
                "slug": slug, "name": disp, "domain": dom, "category": cat,
                "category_name": CATEGORIES[cat]["name"],
                "captured_at": NOW,
                "portals": {"g2": g2, "capterra": cap, "gartner": gar,
                            "trustpilot": tp},
            }
            (HERE / "data" / f"{slug}.json").write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
            out[slug] = rec
            ok = [p for p, v in rec["portals"].items() if v.get("rating") is not None]
            nq = sum(len(v.get("quotes") or []) for v in rec["portals"].values())
            print(f"  {disp:<26} portals={len(ok)}/4 {','.join(ok):<38} quotes={nq}")

        (HERE / "data" / "_all.json").write_text(
            json.dumps({"generated_at": NOW, "categories": CATEGORIES,
                        "vendors": out}, indent=2), encoding="utf-8")
        print(f"\nwrote {len(out)} vendor files")


if __name__ == "__main__":
    asyncio.run(main())
