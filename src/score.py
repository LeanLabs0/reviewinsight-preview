"""Compute the ReviewInsight score.

    rating   = mean of the sites' own averages, x20            (what reviewers say)
    evidence = 0.30 Recent + 0.25 Reliable + 0.25 Results + 0.20 Resonance
    score    = 50 + (rating - 50) x evidence/100

We move a vendor away from neutral only as far as its evidence justifies. Perfect
evidence and the score is exactly what reviewers rate it. No evidence and it sits
at 50, because we do not know anything.

Every curve below is published. Every number a page shows can be redone by hand
from the derivation this writes out.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
ALL = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
TODAY = datetime.fromisoformat(ALL["generated_at"]).replace(tzinfo=None)
PORTALS = [("g2", "G2"), ("capterra", "Capterra"),
           ("gartner", "Gartner Peer Insights"), ("trustpilot", "Trustpilot")]

WEIGHTS = {"recent": 0.30, "reliable": 0.25, "results": 0.25, "resonance": 0.20}

CURVES = {
    "freshness": [(0, 100), (14, 95), (30, 88), (60, 75), (90, 62),
                  (180, 40), (365, 15), (730, 0)],
    "recency_share": [(0, 0), (.10, 20), (.25, 45), (.40, 62), (.60, 80), (.80, 92), (1, 100)],
    "agreement": [(0, 100), (.25, 95), (.5, 88), (1.0, 75), (1.5, 60),
                  (2.0, 45), (2.5, 30), (3.0, 18), (4.0, 0)],
    "coherence": [(0, 0), (.40, 25), (.60, 50), (.75, 70), (.85, 85), (.95, 97), (1, 100)],
    "specificity": [(0, 0), (.02, 12), (.05, 28), (.10, 48), (.15, 62),
                    (.20, 72), (.30, 85), (.40, 93), (.50, 100)],
}
BAND_POINTS = {"detractor": 0, "lukewarm": 35, "satisfied": 65, "advocate": 100}
FLOORS = {"sites": 2, "reviews": 15, "recent_reviews": 5}


def curve(name: str, x: float) -> tuple[float, str]:
    """Piecewise linear. Returns the value and the arithmetic that produced it."""
    knots = CURVES[name]
    if x <= knots[0][0]:
        return float(knots[0][1]), f"{x} at or below {knots[0][0]} -> {knots[0][1]}"
    if x >= knots[-1][0]:
        return float(knots[-1][1]), f"{x} at or above {knots[-1][0]} -> {knots[-1][1]}"
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


def expected_band(stars: float) -> str:
    if stars >= 4.5:
        return "advocate"
    if stars >= 3.5:
        return "satisfied"
    if stars >= 2.5:
        return "lukewarm"
    return "detractor"


ORDER = ["detractor", "lukewarm", "satisfied", "advocate"]
MIN_PER_SITE = 5


def by_site(rows, pred):
    """Count matches and totals per source site."""
    hits, n = {}, {}
    for r in rows:
        s = r["portal"]
        n[s] = n.get(s, 0) + 1
        if pred(r):
            hits[s] = hits.get(s, 0) + 1
    for s in n:
        hits.setdefault(s, 0)
    return hits, n


def site_mean(rows, value):
    """Mean of per-site means. A site needs MIN_PER_SITE reviews to count.

    Trustpilot supplies roughly two thirds of every sample, so a pooled mean
    would quietly hand it two thirds of the vote on dimensions the method says
    are weighted equally by site.
    """
    buckets: dict[str, list[float]] = {}
    for r in rows:
        buckets.setdefault(r["portal"], []).append(value(r))
    used = {s: vals for s, vals in buckets.items() if len(vals) >= MIN_PER_SITE}
    if not used:
        used = buckets
    per = {s: sum(v) / len(v) for s, v in used.items()}
    return (sum(per.values()) / len(per) if per else 0.0,
            per, {s: len(v) for s, v in used.items()})


def compute(slug: str, v: dict, reviews: list[dict]) -> dict:
    sites = [(lbl, v["portals"][k]) for k, lbl in PORTALS
             if v["portals"][k].get("rating") is not None]
    dated = [(r, parse_date(r.get("date"))) for r in reviews]
    dated = [(r, d) for r, d in dated if d]
    # G2 has no working pagination, so we read it through four sort orders.
    # Two of those orders are deliberately the best and worst reviews on the
    # product, which is fine for pulling quotes and ruinous for any rate we
    # compute. Only the recency-ordered slice is a fair sample of G2.
    labelled = [r for r in reviews if r.get("label") and not (
        r["portal"] == "G2" and r.get("sample_order") not in ("most_recent", None))]

    total_reviews = sum(p["count"] or 0 for _, p in sites)
    recent_1y = [r for r, d in dated if (TODAY - d).days <= 365]

    elig = {"sites": len(sites), "reviews": total_reviews,
            "recent_reviews": len(recent_1y), "sample": len(reviews),
            "labelled": len(labelled)}
    fails = [k for k, need in FLOORS.items() if elig[k] < need]
    if fails:
        return {"slug": slug, "rated": False, "not_rated": fails, "eligibility": elig}

    steps: list[dict] = []

    # ---- rating: what reviewers say -------------------------------------
    mean_stars = sum(p["rating"] for _, p in sites) / len(sites)
    rating = round(mean_stars * 20, 1)
    steps.append({"key": "rating", "label": "What reviewers rate it",
                  "value": rating,
                  "math": " + ".join(f"{p['rating']}" for _, p in sites)
                          + f" = {sum(p['rating'] for _, p in sites):.1f}, / {len(sites)}"
                            f" = {mean_stars:.2f}, x20 = {rating}",
                  "inputs": {lbl: p["rating"] for lbl, p in sites}})

    # ---- Recent ----------------------------------------------------------
    newest = max(d for _, d in dated)
    age = (TODAY - newest).days
    fresh, fresh_math = curve("freshness", age)
    share = len(recent_1y) / len(dated)
    shr, shr_math = curve("recency_share", round(share, 3))
    recent = round(0.5 * fresh + 0.5 * shr, 1)
    steps.append({"key": "recent", "label": "Recent", "value": recent,
                  "math": f"0.5 x {fresh:.1f} + 0.5 x {shr:.1f} = {recent}",
                  "parts": [
                      {"name": "Newest review", "detail": f"{age} days ago",
                       "value": round(fresh, 1), "curve": fresh_math},
                      {"name": "Share from the last year",
                       "detail": f"{len(recent_1y)} of {len(dated)} dated reviews ({share:.0%})",
                       "value": round(shr, 1), "curve": shr_math}]})

    # ---- Reliable --------------------------------------------------------
    star_spread = max(p["rating"] for _, p in sites) - min(p["rating"] for _, p in sites)
    agree, agree_math = curve("agreement", round(star_spread, 2))
    pairs = [r for r in labelled if r.get("rating") is not None]
    if pairs:
        # Per site, then average the sites. Trustpilot supplies two thirds of the
        # sample, so pooling would let one site decide a dimension the whole
        # method says is equally weighted.
        hits_by, n_by = by_site(pairs, lambda r: abs(
            ORDER.index(r["label"]["resonance"])
            - ORDER.index(expected_band(r["rating"]))) <= 1)
        shares = [hits_by[s] / n_by[s] for s in n_by if n_by[s] >= 5]
        hits, tot = sum(hits_by.values()), sum(n_by.values())
        coh_share = sum(shares) / len(shares) if shares else hits / tot
        coh, coh_math = curve("coherence", round(coh_share, 3))
        coh_detail = (f"{hits} of {tot} reviews read the way their star rating implies, "
                      f"averaged across {len(shares) or 1} site"
                      f"{'s' if len(shares) != 1 else ''}")
    else:
        coh, coh_math, coh_detail, coh_share = 50.0, "no rated reviews with text", "not measurable", 0
    reliable = round(0.5 * agree + 0.5 * coh, 1)
    steps.append({"key": "reliable", "label": "Reliable", "value": reliable,
                  "math": f"0.5 x {agree:.1f} + 0.5 x {coh:.1f} = {reliable}",
                  "parts": [
                      {"name": "Sites agree", "detail": f"{star_spread:.1f} stars between highest and lowest",
                       "value": round(agree, 1), "curve": agree_math},
                      {"name": "Words match the stars", "detail": coh_detail,
                       "value": round(coh, 1), "curve": coh_math}]})

    # ---- Results-specific ------------------------------------------------
    n_spec = sum(1 for r in labelled if r["label"]["results_specific"])
    rate, per_site_spec, per_site_n = site_mean(
        labelled, lambda r: 1.0 if r["label"]["results_specific"] else 0.0)
    results, res_math = curve("specificity", round(rate, 3))
    results = round(results, 1)
    steps.append({"key": "results", "label": "Results-specific", "value": results,
                  "math": res_math,
                  "parts": [{"name": "Reviews naming a checkable outcome",
                             "detail": f"{n_spec} of {len(labelled)} labelled reviews, "
                                       f"{rate:.0%} averaged across sites",
                             "value": results, "curve": res_math}]
                  + [{"name": site, "detail": f"{v:.0%} of {per_site_n[site]} reviews",
                      "value": round(v * 100, 1), "curve": ""}
                     for site, v in sorted(per_site_spec.items())]})

    # ---- Resonance -------------------------------------------------------
    counts = {b: sum(1 for r in labelled if r["label"]["resonance"] == b) for b in ORDER}
    n = sum(counts.values())
    res_val, per_site_res, per_site_rn = site_mean(
        labelled, lambda r: float(BAND_POINTS[r["label"]["resonance"]]))
    resonance = round(res_val, 1)
    steps.append({"key": "resonance", "label": "Resonance", "value": resonance,
                  "math": "mean of the site means: "
                          + ", ".join(f"{s} {v:.1f}" for s, v in sorted(per_site_res.items()))
                          + f" -> {resonance}",
                  "parts": [{"name": b.capitalize(),
                             "detail": f"{counts[b]} reviews ({counts[b]/n:.0%})" if n else "0",
                             "value": BAND_POINTS[b], "curve": ""} for b in ORDER]
                  + [{"name": site, "detail": f"{per_site_rn[site]} reviews",
                      "value": round(v, 1), "curve": ""}
                     for site, v in sorted(per_site_res.items())]})

    dims = {s["key"]: s["value"] for s in steps if s["key"] in WEIGHTS}
    evidence = round(sum(dims[k] * w for k, w in WEIGHTS.items()), 1)
    ev_math = " + ".join(f"{w:.2f}x{dims[k]}" for k, w in WEIGHTS.items()) + f" = {evidence}"
    score = round(50 + (rating - 50) * evidence / 100)
    sc_math = f"50 + ({rating} - 50) x {evidence}/100 = {50 + (rating-50)*evidence/100:.1f} -> {score}"

    return {"slug": slug, "rated": True, "score": score, "rating": rating,
            "evidence": evidence, "evidence_math": ev_math, "score_math": sc_math,
            "dimensions": steps, "eligibility": elig,
            "sample_size": len(reviews), "labelled": len(labelled)}


def main() -> None:
    out = {}
    for slug, v in ALL["vendors"].items():
        f = HERE / "data" / "reviews" / f"{slug}.json"
        reviews = json.loads(f.read_text(encoding="utf-8"))["reviews"] if f.exists() else []
        out[slug] = compute(slug, v, reviews)

    (HERE / "data" / "_scores.json").write_text(
        json.dumps({"weights": WEIGHTS, "curves": CURVES, "floors": FLOORS,
                    "band_points": BAND_POINTS, "scores": out}, indent=2),
        encoding="utf-8")

    rows = [r for r in out.values() if r["rated"]]
    rows.sort(key=lambda r: -r["score"])
    print(f"{'vendor':<24}{'score':>6}{'rating':>8}{'evid':>7}"
          f"{'Rec':>6}{'Rel':>6}{'Res':>6}{'Rsn':>6}{'n':>6}")
    print("-" * 75)
    for r in rows:
        d = {s["key"]: s["value"] for s in r["dimensions"]}
        print(f"{ALL['vendors'][r['slug']]['name'][:23]:<24}{r['score']:>6}{r['rating']:>8}"
              f"{r['evidence']:>7}{d['recent']:>6}{d['reliable']:>6}"
              f"{d['results']:>6}{d['resonance']:>6}{r['sample_size']:>6}")
    for r in out.values():
        if not r["rated"]:
            print(f"{ALL['vendors'][r['slug']]['name'][:23]:<24}  NOT RATED: {', '.join(r['not_rated'])}")
    sc = [r["score"] for r in rows]
    print(f"\nscores {min(sc)} to {max(sc)}, spread {max(sc)-min(sc)}")


if __name__ == "__main__":
    main()
