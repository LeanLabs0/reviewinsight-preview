"""Add Google Business Profile and Clutch, per Kevin's 14 Aug question.

Both are wired the same way as the existing platforms and merged into
data/_all.json. Where a company genuinely has no listing we record that
rather than inventing one, because an absent listing is itself a finding.

Two things worth knowing before reading the results:

  Clutch lists service providers, not software products. Searching it for a
  software vendor returns agencies that implement that software, so every
  candidate is name-checked against the company and rejected if it does not
  match. Expect most software vendors to come back empty.

  A Google Business Profile for a software company is its office, and the
  reviews on it are about the office rather than the product. We record it,
  and it is excluded from the rating for software companies for that reason.
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
SEM = asyncio.Semaphore(3)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def post(client, url, headers, body, timeout=90.0, tries=3):
    for i in range(tries):
        try:
            r = await client.post(url, headers=headers, json=body, timeout=timeout)
            if r.status_code == 200 or (r.status_code < 500 and r.status_code != 429):
                return r
        except Exception:
            pass
        await asyncio.sleep(2 * (i + 1))
    return None


# ------------------------------------------------------- Google Business
async def google(client, v: dict) -> dict:
    """DataForSEO my_business_info. Keyword resolution needs a hint, so try
    the bare name first and fall back to a headquarters-style query."""
    base = {"portal": "google", "status": "unresolved", "rating": None,
            "count": None, "quotes": [], "url": None, "captured_at": NOW,
            "about": "office listing, not the product"}
    for kw in (v["name"], f"{v['name']} headquarters"):
        async with SEM:
            r = await post(client,
                           "https://api.dataforseo.com/v3/business_data/google/my_business_info/task_post",
                           DFS, [{"keyword": kw, "location_name": "United States",
                                  "language_code": "en"}])
        if r is None:
            continue
        try:
            tid = r.json()["tasks"][0]["id"]
        except Exception:
            continue
        for _ in range(14):
            await asyncio.sleep(9)
            async with SEM:
                g = await client.get(
                    f"https://api.dataforseo.com/v3/business_data/google/my_business_info/task_get/{tid}",
                    headers=DFS, timeout=90.0)
            try:
                t = g.json()["tasks"][0]
            except Exception:
                continue
            if not t.get("result"):
                continue
            items = (t["result"][0] or {}).get("items") or []
            if not items:
                break
            it = items[0]
            title, rt = it.get("title"), (it.get("rating") or {})
            # only accept a listing that is plausibly this company
            if not title or norm(v["name"])[:8] not in norm(title):
                break
            return {**base, "status": "ok" if rt.get("value") else "no_reviews",
                    "rating": rt.get("value"), "count": rt.get("votes_count"),
                    "url": it.get("url") or it.get("cid_url"),
                    "category": it.get("category"), "matched_on": kw}
    return base


# --------------------------------------------------------------- Clutch
async def clutch(client, v: dict) -> dict:
    base = {"portal": "clutch", "status": "no_listing", "rating": None,
            "count": None, "quotes": [], "url": None, "captured_at": NOW,
            "about": "services directory"}
    async with SEM:
        r = await post(client, "https://api.firecrawl.dev/v2/search", FC,
                       {"query": f'"{v["name"]}" site:clutch.co/profile', "limit": 6})
    if r is None or r.status_code != 200:
        return base
    try:
        d = r.json().get("data")
        w = d.get("web", d) if isinstance(d, dict) else d
        urls = [h.get("url", "") for h in (w or [])]
    except Exception:
        return base

    want = norm(v["name"])
    for u in urls:
        if "clutch.co/profile/" not in u:
            continue
        slug = norm(u.rsplit("/", 1)[-1])
        # the profile has to BE the company, not an agency implementing it.
        # "clickup-marketing" and "asana-partners" must not match.
        if slug != want:
            continue
        async with SEM:
            sc = await post(client, "https://api.firecrawl.dev/v2/scrape", FC,
                            {"url": u, "formats": ["markdown"],
                             "onlyMainContent": False, "waitFor": 3500,
                             "timeout": 65000}, timeout=150.0)
        if sc is None or sc.status_code != 200:
            continue
        md = ((sc.json().get("data") or {}).get("markdown")) or ""
        m = re.search(r"([0-5]\.\d)\s*\n+\s*([\d,]+)\s*[Rr]eview", md)
        if not m:
            continue
        return {**base, "status": "ok", "rating": float(m.group(1)),
                "count": int(m.group(2).replace(",", "")), "url": u}
    return {**base, "candidates_rejected": [u for u in urls if "clutch.co/profile/" in u][:3]}


async def main() -> None:
    data = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with httpx.AsyncClient(limits=limits) as client:
        vs = list(data["vendors"].values())
        res = await asyncio.gather(*[
            asyncio.gather(google(client, v), clutch(client, v)) for v in vs])

    for v, (g, c) in zip(vs, res):
        v["portals"]["google"] = g
        v["portals"]["clutch"] = c
        (HERE / "data" / f"{v['slug']}.json").write_text(
            json.dumps(v, indent=2), encoding="utf-8")
        print(f"  {v['name'][:24]:<26} google={g['status']:<12}"
              f"{'' if g['rating'] is None else str(g['rating'])+'/'+str(g['count']):<10}"
              f" clutch={c['status']}")

    (HERE / "data" / "_all.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    ok_g = sum(1 for v in vs if v["portals"]["google"]["rating"] is not None)
    ok_c = sum(1 for v in vs if v["portals"]["clutch"]["rating"] is not None)
    print(f"\ngoogle business profile: {ok_g} of {len(vs)} companies")
    print(f"clutch:                  {ok_c} of {len(vs)} companies")


if __name__ == "__main__":
    asyncio.run(main())
