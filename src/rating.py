"""Compute the ReviewInsight Rating.

    Rating = (Review Avg + Reliable + Recent + Result-Specific) / 4

Four equally weighted parts, per Kevin's 14 Aug spec. Replaces the earlier
two-layer model, and the words "score" and "evidence strength" along with it.

  Review Avg       every review counted once, so a platform with more reviews
                   carries more of the average. 55 reviews at 4.9 plus 2 at 1.0
                   is 4.76, not 2.95.
  Reliable         does the picture hold up across platforms. A wide gap drags
                   this down hard, because a gap is what review gaming looks
                   like. Being found on only one platform drags it down too.
                   Differences in review COUNT never count against a brand.
  Recent           strong for a review inside the last 30 days, falling away
                   with every day since the newest one.
  Result-Specific  how often reviewers name an outcome a stranger could check.

Every curve is published. Every number can be redone by hand from the
derivation this writes out.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
ALL = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
TODAY = datetime.fromisoformat(ALL["generated_at"]).replace(tzinfo=None)

# Order is Kevin's: Review Avg first, Recent deliberately not first.
PARTS = ["review_avg", "reliable", "recent", "results"]
LABELS = {"review_avg": "Review Avg", "reliable": "Reliable",
          "recent": "Recent", "results": "Result-Specific"}

CURVES = {
    # days since the newest review anywhere
    "freshness": [(0, 100), (30, 90), (45, 82), (60, 74), (90, 60),
                  (180, 34), (365, 10), (730, 0)],
    # share of the reviews we hold that were written in the last year
    "recent_share": [(0, 0), (.10, 18), (.25, 42), (.40, 60), (.60, 78),
                     (.80, 92), (1, 100)],
    # widest gap in stars between two platforms. Deliberately harsh: Kevin
    # wants a gap to greatly lower the rating, because it is the tell for
    # review gaming rather than a quirk of sampling.
    "agreement": [(0, 100), (.25, 94), (.5, 85), (1.0, 68), (1.5, 48),
                  (2.0, 30), (2.5, 16), (3.0, 7), (4.0, 0)],
    # share of reviews naming a checkable outcome
    "specificity": [(0, 0), (.02, 12), (.05, 28), (.10, 48), (.15, 62),
                    (.20, 72), (.30, 85), (.40, 93), (.50, 100)],
}

# A brand seen on one platform only has no corroboration, so Reliable cannot
# be high no matter how tidy that single rating looks.
PRESENCE = {1: 0.35, 2: 0.70, 3: 0.88, 4: 1.00}
FLOORS = {"platforms": 2, "reviews": 15, "recent_reviews": 5}
MIN_PER_SITE = 5


def curve(name: str, x: float) -> tuple[float, str]:
    knots = CURVES[name]
    if x <= knots[0][0]:
        return float(knots[0][1]), f"{x:g} at or below {knots[0][0]:g}, so {knots[0][1]}"
    if x >= knots[-1][0]:
        return float(knots[-1][1]), f"{x:g} at or above {knots[-1][0]:g}, so {knots[-1][1]}"
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= x <= x1:
            v = y0 + (x - x0) / (x1 - x0) * (y1 - y0)
            return v, f"{y0} + ({x:g}-{x0:g})/({x1:g}-{x0:g}) x ({y1}-{y0}) = {v:.1f}"
    return 0.0, "out of range"


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for pat, fmt in ((r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
                     (r"^\d{1,2}/\d{1,2}/\d{4}$", "%m/%d/%Y"),
                     (r"^[A-Z][a-z]+ \d{1,2}, \d{4}$", "%B %d, %Y"),
                     (r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$", "%b %d, %Y")):
        if re.match(pat, s.strip()):
            try:
                return datetime.strptime(s.strip(), fmt)
            except ValueError:
                pass
    return None


def site_mean(rows, value):
    """Mean of the per-platform means, for text-derived measures.

    Trustpilot supplies most of any sample, so pooling would let one platform
    decide a measure. Note this applies to how often reviewers say something,
    never to Review Avg, which is deliberately volume-weighted.
    """
    buckets: dict[str, list[float]] = {}
    for r in rows:
        buckets.setdefault(r["portal"], []).append(value(r))
    used = {k: v for k, v in buckets.items() if len(v) >= MIN_PER_SITE} or buckets
    per = {k: sum(v) / len(v) for k, v in used.items()}
    return (sum(per.values()) / len(per) if per else 0.0,
            per, {k: len(v) for k, v in used.items()})


def compute(slug: str, v: dict, reviews: list[dict]) -> dict:
    sites = [(m["label"], v["portals"][k]) for k, m in PORTAL_META.items()
             if k in RATING_PLATFORMS and k in v["portals"]
             and v["portals"][k].get("rating") is not None
             and v["portals"][k].get("count")]

    dated = [(r, parse_date(r.get("date"))) for r in reviews]
    dated = [(r, d) for r, d in dated if d]
    recent_1y = [r for r, d in dated if (TODAY - d).days <= 365]
    labelled = [r for r in reviews if r.get("label") and not (
        r["portal"] == "G2" and r.get("sample_order") not in ("most_recent", None))]

    total = sum(p["count"] for _, p in sites)
    elig = {"platforms": len(sites), "reviews": total,
            "recent_reviews": len(recent_1y), "sample": len(reviews),
            "labelled": len(labelled)}
    fails = [k for k, need in FLOORS.items() if elig[k] < need]
    if fails:
        return {"slug": slug, "rated": False, "not_rated": fails, "eligibility": elig}

    parts: list[dict] = []

    # ---- Review Avg: every review counted once --------------------------
    weighted = sum(p["rating"] * p["count"] for _, p in sites) / total
    review_avg = round(weighted * 20, 1)
    parts.append({
        "key": "review_avg", "label": LABELS["review_avg"], "value": review_avg,
        "math": " + ".join(f"{p['rating']}x{p['count']:,}" for _, p in sites)
                + f" = {sum(p['rating']*p['count'] for _, p in sites):,.0f}, "
                  f"/ {total:,} reviews = {weighted:.2f} stars, x20 = {review_avg}",
        "parts": [{"name": lbl, "detail": f"{p['rating']} from {p['count']:,} reviews",
                   "value": round(p["rating"] * 20, 1), "curve": ""} for lbl, p in sites]})

    # ---- Reliable: agreement, and corroboration --------------------------
    gap = max(p["rating"] for _, p in sites) - min(p["rating"] for _, p in sites)
    agree, agree_math = curve("agreement", round(gap, 2))
    pres = PRESENCE.get(len(sites), 1.00)
    reliable = round(agree * pres, 1)
    lo = min(sites, key=lambda s: s[1]["rating"])
    hi = max(sites, key=lambda s: s[1]["rating"])
    parts.append({
        "key": "reliable", "label": LABELS["reliable"], "value": reliable,
        "math": f"{agree:.1f} x {pres:.2f} for {len(sites)} platforms = {reliable}",
        "parts": [
            {"name": "Widest gap between platforms",
             "detail": f"{gap:.1f} stars, {lo[0]} at {lo[1]['rating']} against "
                       f"{hi[0]} at {hi[1]['rating']}",
             "value": round(agree, 1), "curve": agree_math},
            {"name": "Platforms carrying reviews",
             "detail": f"{len(sites)}, which counts for {pres:.0%} of the agreement figure",
             "value": round(pres * 100, 1),
             "curve": "one platform 35%, two 70%, three 88%, four or more 100%"}]})

    # ---- Recent ----------------------------------------------------------
    newest = max(d for _, d in dated)
    age = (TODAY - newest).days
    fresh, fresh_math = curve("freshness", age)
    share = len(recent_1y) / len(dated)
    shr, shr_math = curve("recent_share", round(share, 3))
    recent = round(0.6 * fresh + 0.4 * shr, 1)
    parts.append({
        "key": "recent", "label": LABELS["recent"], "value": recent,
        "math": f"0.6 x {fresh:.1f} + 0.4 x {shr:.1f} = {recent}",
        "parts": [
            {"name": "Days since the newest review", "detail": f"{age}",
             "value": round(fresh, 1), "curve": fresh_math},
            {"name": "Written in the last year",
             "detail": f"{len(recent_1y)} of {len(dated)} reviews we read ({share:.0%})",
             "value": round(shr, 1), "curve": shr_math}]})

    # ---- Result-Specific --------------------------------------------------
    n_spec = sum(1 for r in labelled if r["label"]["results_specific"])
    rate, per_site, per_n = site_mean(
        labelled, lambda r: 1.0 if r["label"]["results_specific"] else 0.0)
    results, res_math = curve("specificity", round(rate, 3))
    results = round(results, 1)
    parts.append({
        "key": "results", "label": LABELS["results"], "value": results,
        "math": res_math,
        "parts": [{"name": "Reviews naming a checkable outcome",
                   "detail": f"{n_spec} of {len(labelled)} reviews we read closely, "
                             f"{rate:.0%} averaged across platforms",
                   "value": results, "curve": res_math}]
        + [{"name": site, "detail": f"{val:.0%} of {per_n[site]} reviews",
            "value": round(val * 100, 1), "curve": ""}
           for site, val in sorted(per_site.items())]})

    vals = {p["key"]: p["value"] for p in parts}
    rating = round(sum(vals[k] for k in PARTS) / len(PARTS))
    math = (" + ".join(f"{vals[k]}" for k in PARTS)
            + f" = {sum(vals[k] for k in PARTS):.1f}, / {len(PARTS)} = "
              f"{sum(vals[k] for k in PARTS)/len(PARTS):.2f} -> {rating}")

    return {"slug": slug, "rated": True, "rating": rating, "rating_math": math,
            "parts": parts, "eligibility": elig,
            "sample_size": len(reviews), "labelled": len(labelled),
            "reviews_last_year": len(recent_1y), "reviews_total": total}


PORTAL_META = {
    "g2": {"label": "G2"}, "capterra": {"label": "Capterra"},
    "gartner": {"label": "Gartner Peer Insights"}, "trustpilot": {"label": "Trustpilot"},
    "google": {"label": "Google Business Profile"}, "clutch": {"label": "Clutch"},
}

# Google Business Profile and Clutch are collected and shown, but they do not
# feed the rating of a software company.
#
# A Google Business Profile is an office. ClickUp's is 3.9 from 86 people, next
# to 13,689 reviews of the product on G2, and those 86 are rating a building and
# an employer. Letting that in would invent a gap where there is none, which is
# the one thing Reliable must never do.
#
# Clutch lists service providers. It returned no profile for any of the sixteen
# software companies here, so there is nothing to include.
#
# For a category of B2B service companies both would be primary sources, and
# this set is where they turn on.
RATING_PLATFORMS = {"g2", "capterra", "gartner", "trustpilot"}


def main() -> None:
    out = {}
    for slug, v in ALL["vendors"].items():
        f = HERE / "data" / "reviews" / f"{slug}.json"
        reviews = json.loads(f.read_text(encoding="utf-8"))["reviews"] if f.exists() else []
        out[slug] = compute(slug, v, reviews)

    (HERE / "data" / "_ratings.json").write_text(
        json.dumps({"parts": PARTS, "labels": LABELS, "curves": CURVES,
                    "presence": PRESENCE, "floors": FLOORS, "ratings": out}, indent=2),
        encoding="utf-8")

    rows = sorted((r for r in out.values() if r["rated"]), key=lambda r: -r["rating"])
    print(f"{'vendor':<24}{'rating':>7}{'Avg':>7}{'Rel':>7}{'Rec':>7}{'Res':>7}{'sites':>7}")
    print("-" * 66)
    for r in rows:
        v = {p["key"]: p["value"] for p in r["parts"]}
        print(f"{ALL['vendors'][r['slug']]['name'][:23]:<24}{r['rating']:>7}"
              f"{v['review_avg']:>7}{v['reliable']:>7}{v['recent']:>7}{v['results']:>7}"
              f"{r['eligibility']['platforms']:>7}")
    for r in out.values():
        if not r["rated"]:
            print(f"{ALL['vendors'][r['slug']]['name'][:23]:<24}  NOT RATED: {', '.join(r['not_rated'])}")
    sc = [r["rating"] for r in rows]
    print(f"\nratings {min(sc)} to {max(sc)}, spread {max(sc)-min(sc)}")


if __name__ == "__main__":
    main()
