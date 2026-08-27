"""Which platforms actually carry well-known B2B service companies?

Software vendors live on G2/Capterra/Gartner. Service companies do not, so
before picking a vendor set we check where they genuinely appear.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

ENV = Path(r"C:\Users\Sistemas\AIS-OS\projects\lean-labs\factor8_app\.env")
_L = ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
FC_KEY = next(m.group(1) for m in (re.search(r"(fc-[A-Za-z0-9]+)", l) for l in _L) if m)
DFS_AUTH = next(l.split("=", 1)[1].strip() for l in _L
                if l.startswith("FACTOR8_DATAFORSEO_AUTH="))
FC = {"Authorization": f"Bearer {FC_KEY}", "Content-Type": "application/json"}
DFS = {"Authorization": f"Basic {DFS_AUTH}", "Content-Type": "application/json"}
SEM = asyncio.Semaphore(4)

CANDIDATES = [
    ("Coalition Technologies", "coalitiontechnologies.com"),
    ("Power Digital", "powerdigitalmarketing.com"),
    ("Wpromote", "wpromote.com"),
    ("Victorious", "victoriousseo.com"),
    ("Tinuiti", "tinuiti.com"),
    ("Siege Media", "siegemedia.com"),
    ("NinjaPromo", "ninjapromo.io"),
    ("Sociallyin", "sociallyin.com"),
    ("Lounge Lizard", "loungelizard.com"),
    ("Titan Growth", "titangrowth.com"),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


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


async def clutch(c, name):
    async with SEM:
        r = await post(c, "https://api.firecrawl.dev/v2/search", FC,
                       {"query": f'"{name}" site:clutch.co/profile', "limit": 6})
    if not r or r.status_code != 200:
        return None
    d = r.json().get("data"); w = d.get("web", d) if isinstance(d, dict) else d
    for u in [h.get("url", "") for h in (w or [])]:
        if "clutch.co/profile/" not in u:
            continue
        slug = norm(u.rsplit("/", 1)[-1])
        if slug != norm(name) and not slug.startswith(norm(name)[:12]):
            continue
        async with SEM:
            sc = await post(c, "https://api.firecrawl.dev/v2/scrape", FC,
                            {"url": u, "formats": ["markdown"], "onlyMainContent": True,
                             "waitFor": 3500, "timeout": 65000}, t=150.0)
        if not sc or sc.status_code != 200:
            continue
        md = ((sc.json().get("data") or {}).get("markdown")) or ""
        # Clutch renders: "Overall Review Rating\n\n4.9\n\n\n(450)"
        m = re.search(r"Overall Review Rating\s*\n+\s*([0-5]\.\d)\s*\n+\s*\(([\d,]+)\)", md)
        if m:
            return (float(m.group(1)), int(m.group(2).replace(",", "")), u)
    return None


async def trustpilot(c, domain):
    async with SEM:
        r = await post(c, "https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
                       DFS, [{"domain": domain, "depth": 10}])
    if not r:
        return None
    try:
        tid = r.json()["tasks"][0]["id"]
    except Exception:
        return None
    for _ in range(12):
        await asyncio.sleep(10)
        async with SEM:
            g = await c.get(f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{tid}",
                            headers=DFS, timeout=90.0)
        try:
            t = g.json()["tasks"][0]
        except Exception:
            continue
        if t.get("result"):
            res = t["result"][0]
            rt = (res.get("rating") or {}).get("value")
            return (rt, res.get("reviews_count")) if rt else None
    return None


async def google(c, name):
    async with SEM:
        r = await post(c, "https://api.dataforseo.com/v3/business_data/google/my_business_info/task_post",
                       DFS, [{"keyword": name, "location_name": "United States",
                              "language_code": "en"}])
    if not r:
        return None
    try:
        tid = r.json()["tasks"][0]["id"]
    except Exception:
        return None
    for _ in range(12):
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
            if not items:
                return None
            it = items[0]; rt = it.get("rating") or {}
            if not it.get("title") or norm(name)[:8] not in norm(it["title"]):
                return None
            return (rt.get("value"), rt.get("votes_count")) if rt.get("value") else None
    return None


async def main():
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=10)) as c:
        res = await asyncio.gather(*[
            asyncio.gather(clutch(c, n), trustpilot(c, d), google(c, n))
            for n, d in CANDIDATES])
    print(f"{'company':<36}{'clutch':<18}{'trustpilot':<16}{'google':<14}live")
    print("-" * 88)
    keep = []
    for (n, d), (cl, tp, go) in zip(CANDIDATES, res):
        live = sum(1 for x in (cl, tp, go) if x)
        f = lambda x: f"{x[0]}/{x[1]:,}" if x else "-"
        print(f"{n[:35]:<36}{f(cl):<18}{f(tp):<16}{f(go):<14}{live}")
        if live >= 2:
            keep.append(n)
    print(f"\n{len(keep)} of {len(CANDIDATES)} have at least two platforms")
    print("keep:", ", ".join(keep))


if __name__ == "__main__":
    asyncio.run(main())
