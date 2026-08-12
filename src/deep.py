"""Pull review-level records at depth, enough to measure the four Rs.

The shallow pull gets ~14 reviews per vendor, which is fine for quotes and
useless for statistics. This gets ~150: G2 40 via the four sort orders,
Trustpilot 100 at depth, plus whatever Capterra and Gartner publish.

Writes data/reviews/{slug}.json - a flat list of records, each with a date,
a star rating where the platform gives one, and the text where it is public.
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
ALL = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
FC_SEM = asyncio.Semaphore(3)
DFS_SEM = asyncio.Semaphore(3)
Q = "\u201c"


async def _post(client, url, *, headers, body, timeout, tries=3):
    for i in range(tries):
        try:
            r = await client.post(url, headers=headers, json=body, timeout=timeout)
            if r.status_code == 200 or (r.status_code < 500 and r.status_code != 429):
                return r
        except Exception:
            pass
        await asyncio.sleep(2 * (i + 1))
    return None


async def _get(client, url, *, headers, timeout, tries=3):
    for i in range(tries):
        try:
            r = await client.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        await asyncio.sleep(2 * (i + 1))
    return None


async def scrape(client, url) -> str:
    async with FC_SEM:
        r = await _post(client, "https://api.firecrawl.dev/v2/scrape", headers=FC,
                        body={"url": url, "formats": ["markdown"],
                              "onlyMainContent": False, "waitFor": 3500,
                              "timeout": 65000}, timeout=150.0)
    if r is None or r.status_code != 200:
        return ""
    try:
        return ((r.json().get("data") or {}).get("markdown")) or ""
    except Exception:
        return ""


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


# ------------------------------------------------------------------ G2
def parse_g2(md: str, url: str, order: str) -> list[dict]:
    """Anchor on the quoted headline + N/5 pair, then read around it."""
    out = []
    for m in re.finditer(r'\n"([^"]{10,200})"\n\n([0-5](?:\.\d)?)/5\n', md):
        back = md[max(0, m.start() - 1200): m.start()]
        fwd = md[m.end(): m.end() + 2600]

        dm = re.findall(r"\n(\d{1,2}/\d{1,2}/\d{4})\n", back)
        date = dm[-1] if dm else None
        rid = re.findall(r"survey_responses/(\d+)", back + fwd[:400])
        size = re.findall(r"\n((?:Small-Business|Mid-Market|Enterprise)[^\n]*)\n", back)
        role = None
        if date:
            seg = back.rsplit(date, 1)[0].strip().split("\n")
            cand = [s.strip() for s in seg if s.strip()][-2:]
            for c in cand:
                if (2 < len(c) < 70 and "](" not in c and "Small-Business" not in c
                        and "Mid-Market" not in c and "Enterprise" not in c):
                    role = c
        like = re.search(r"What do you like best[^\n]*\n\n(.+?)(?:Review collected by|\n\n#|\Z)",
                         fwd, re.S)
        dis = re.search(r"What do you dislike[^\n]*\n\n(.+?)(?:Review collected by|\n\n#|\Z)",
                        fwd, re.S)
        body = " ".join(x for x in [norm(like.group(1)) if like else "",
                                    norm(dis.group(1)) if dis else ""] if x)
        out.append({
            "portal": "G2", "review_id": rid[0] if rid else None,
            "date": date, "rating": float(m.group(2)),
            "title": norm(m.group(1)), "text": body[:2000] or None,
            "role": role, "company_size": size[-1] if size else None,
            "source_url": url, "sample_order": order,
        })
    return out


async def g2_reviews(client, base: str) -> list[dict]:
    orders = ["most_recent", "most_helpful", "highest_rated", "lowest_rated"]
    mds = await asyncio.gather(*[scrape(client, f"{base}?order={o}") for o in orders])
    seen, out = set(), []
    for o, md in zip(orders, mds):
        for r in parse_g2(md, base, o):
            key = r["review_id"] or (r["title"], r["date"])
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    return out


# ------------------------------------------------------------ Capterra
def parse_capterra(md: str, url: str) -> list[dict]:
    out = []
    for m in re.finditer(
            rf"Verified[^\n]*\n\n([^\n]{{5,240}})\n\n{Q}([^{Q}]{{30,600}}){Q}\n\n"
            r"([A-Z][a-z]+ \d{1,2}, \d{4})", md):
        meta = m.group(1).strip()
        ms = re.search(r"([\d,]+\s*-\s*[\d,]+|\d[\d,]*\+?)\s*employees", meta)
        out.append({
            "portal": "Capterra", "review_id": None, "date": m.group(3),
            "rating": None, "title": None, "text": norm(m.group(2)),
            "role": re.split(r"(?<=[a-z])(?=[A-Z])", meta)[0].strip() or None,
            "company_size": (ms.group(1).replace(" ", "") + " employees") if ms else None,
            "source_url": url, "sample_order": "page",
        })
    return out


async def capterra_reviews(client, base: str) -> list[dict]:
    pages = [base] + [f"{base}?page={n}" for n in (2, 3)]
    mds = await asyncio.gather(*[scrape(client, u) for u in pages])
    seen, out = set(), []
    for md in mds:
        for r in parse_capterra(md, base):
            k = r["text"][:80]
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
    return out


# ------------------------------------------------------------- Gartner
def parse_gartner(md: str, url: str) -> list[dict]:
    out = []
    for m in re.finditer(
            r"\n([A-Z][^\n]{2,60})\n\n([^\n]{3,60})\n\n(FAVORABLE|CRITICAL|NEUTRAL)\n\n"
            r"#{2,5}\s*" + Q + r"([^" + "\u201d" + Q + r"]{10,200})[" + "\u201d" + Q + r"]\n\n"
            r"([0-5]\.\d)\n\n([A-Z][a-z]{2} \d{1,2}, \d{4})", md):
        out.append({
            "portal": "Gartner Peer Insights", "review_id": None,
            "date": m.group(6), "rating": float(m.group(5)),
            "title": norm(m.group(4)), "text": None, "body_gated": True,
            "role": m.group(1).strip(), "company_size": m.group(2).strip(),
            "sentiment_label": m.group(3), "source_url": url, "sample_order": "page",
        })
    return out


# ---------------------------------------------------------- Trustpilot
async def tp_deep(client, domain: str, depth: int = 100) -> list[dict]:
    async with DFS_SEM:
        r = await _post(
            client,
            "https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
            headers=DFS, body=[{"domain": domain, "depth": depth, "sort_by": "recency"}],
            timeout=90.0)
    if r is None:
        return []
    try:
        tid = r.json()["tasks"][0]["id"]
    except Exception:
        return []
    for _ in range(18):
        await asyncio.sleep(10)
        async with DFS_SEM:
            g = await _get(
                client,
                f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{tid}",
                headers=DFS, timeout=90.0)
        if g is None:
            continue
        try:
            t = g.json()["tasks"][0]
        except Exception:
            continue
        if t.get("result"):
            res = t["result"][0]
            url = res.get("check_url") or f"https://www.trustpilot.com/review/{domain}"
            out = []
            for it in res.get("items") or []:
                out.append({
                    "portal": "Trustpilot", "review_id": None,
                    "date": (it.get("timestamp") or "")[:10] or None,
                    "rating": (it.get("rating") or {}).get("value"),
                    "title": norm(it.get("title") or "") or None,
                    "text": norm(it.get("review_text") or "")[:2000] or None,
                    "role": None, "company_size": None,
                    "source_url": url, "sample_order": "recency",
                })
            return out
    return []


# ------------------------------------------------------------------ run
async def one(client, v: dict) -> tuple[str, list[dict]]:
    p = v["portals"]
    tasks = []
    tasks.append(g2_reviews(client, p["g2"]["url"]) if p["g2"].get("url") else _none())
    tasks.append(capterra_reviews(client, p["capterra"]["url"]) if p["capterra"].get("url") else _none())
    tasks.append(_gartner(client, p["gartner"]["url"]) if p["gartner"].get("url") else _none())
    tasks.append(tp_deep(client, v["domain"]))
    parts = await asyncio.gather(*tasks)
    return v["slug"], [r for part in parts for r in part]


async def _none():
    return []


async def _gartner(client, url):
    return parse_gartner(await scrape(client, url), url)


async def main() -> None:
    outdir = HERE / "data" / "reviews"
    outdir.mkdir(parents=True, exist_ok=True)
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with httpx.AsyncClient(limits=limits) as client:
        vs = list(ALL["vendors"].values())
        results = await asyncio.gather(*[one(client, v) for v in vs])
    total = 0
    for slug, revs in results:
        (outdir / f"{slug}.json").write_text(
            json.dumps({"slug": slug, "captured_at": NOW, "reviews": revs}, indent=2),
            encoding="utf-8")
        by = {}
        for r in revs:
            by[r["portal"]] = by.get(r["portal"], 0) + 1
        dated = sum(1 for r in revs if r.get("date"))
        texted = sum(1 for r in revs if r.get("text"))
        total += len(revs)
        print(f"  {slug:<24} {len(revs):>4} reviews  dated={dated:>3} text={texted:>3}  "
              + " ".join(f"{k.split()[0]}:{n}" for k, n in by.items()))
    print(f"\ntotal {total} reviews across {len(results)} vendors")


if __name__ == "__main__":
    asyncio.run(main())
