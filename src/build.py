"""Render the ReviewInsight preview from the pulled data.

Every number on every page comes from data/*.json and carries its source and
capture date. The composite score is deliberately a pending state: we have not
computed it yet, so we show the formula and what is still missing rather than
inventing a figure.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
OUT = HERE / "site"

VENDORS: dict = DATA["vendors"]
CATS: dict = DATA["categories"]
PORTALS = [("g2", "G2"), ("capterra", "Capterra"),
           ("gartner", "Gartner Peer Insights"), ("trustpilot", "Trustpilot")]
CAPTURED = datetime.fromisoformat(DATA["generated_at"]).strftime("%d %B %Y")
QUARTER = "2026-Q3"

e = html.escape


# ------------------------------------------------------------ derived facts
def portals_with_data(v) -> list[tuple[str, str, dict]]:
    return [(k, lbl, v["portals"][k]) for k, lbl in PORTALS
            if v["portals"][k].get("rating") is not None]


def total_reviews(v) -> int:
    return sum(p["count"] or 0 for _, _, p in portals_with_data(v))


def spread(v):
    """Widest gap between platform star ratings. Real, computed, no model."""
    got = portals_with_data(v)
    if len(got) < 2:
        return None
    pairs = [(lbl, p["rating"]) for _, lbl, p in got]
    lo = min(pairs, key=lambda x: x[1])
    hi = max(pairs, key=lambda x: x[1])
    return {"points": round(hi[1] - lo[1], 1), "lo": lo, "hi": hi,
            "all": pairs, "n": len(got)}


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def qdate(q) -> datetime | None:
    d = (q.get("date") or "").strip()
    for pat, fmt in ((r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
                     (r"^\d{1,2}/\d{1,2}/\d{4}$", "%m/%d/%Y"),
                     (r"^[A-Z][a-z]+ \d{1,2}, \d{4}$", "%B %d, %Y"),
                     (r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$", "%b %d, %Y")):
        if re.match(pat, d):
            try:
                return datetime.strptime(d, fmt)
            except ValueError:
                continue
    return None


def newest_review(v) -> datetime | None:
    ds = [qdate(q) for p in v["portals"].values() for q in (p.get("quotes") or [])]
    ds = [d for d in ds if d]
    return max(ds) if ds else None


def all_quotes(v) -> list:
    """Balanced across platforms, newest first within each.

    Sorting purely by date buries Capterra and Gartner under Trustpilot, which
    posts constantly. Take up to two per platform so the page shows what each
    source actually sounds like.
    """
    out = []
    for key, _ in PORTALS:
        qs = list(v["portals"][key].get("quotes") or [])
        qs.sort(key=lambda q: qdate(q) or datetime(1970, 1, 1), reverse=True)
        out += qs[:2]
    out.sort(key=lambda q: qdate(q) or datetime(1970, 1, 1), reverse=True)
    return out


def cat_vendors(cat: str) -> list:
    vs = [v for v in VENDORS.values() if v["category"] == cat]
    return sorted(vs, key=total_reviews, reverse=True)


# ------------------------------------------------------------------- shell
def shell(depth: int, title: str, desc: str, body: str, nav: str = "") -> str:
    r = "../" * depth if depth else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="stylesheet" href="{r}ri.css">
</head>
<body>
<header class="mast"><div class="wrap">
  <a class="brand" href="{r}index.html">ReviewInsight</a>
  <nav>
    <a href="{r}categories/index.html"{' aria-current="page"' if nav == 'cat' else ''}>Categories</a>
    <a href="{r}vendors/index.html"{' aria-current="page"' if nav == 'ven' else ''}>Vendors</a>
    <a href="{r}methodology/index.html"{' aria-current="page"' if nav == 'meth' else ''}>Methodology</a>
    <a href="{r}quarterly/{QUARTER.lower()}/index.html"{' aria-current="page"' if nav == 'q' else ''}>Quarterly index</a>
  </nav>
  <span class="spacer tiny">Data captured {CAPTURED}</span>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="foot"><div class="wrap">
  <div>
    <h4>ReviewInsight</h4>
    <p>Independent review intelligence for B2B software buyers. We read G2,
    Capterra, Gartner Peer Insights and Trustpilot side by side and publish what
    they agree and disagree on. Vendors cannot pay for placement.</p>
    <p class="tiny" style="margin-top:10px">A brand by Brandvious, Inc.</p>
  </div>
  <div>
    <h4>Browse</h4>
    <ul>
      {''.join(f'<li><a href="{r}categories/{c}/index.html">{e(m["name"])}</a></li>' for c, m in CATS.items())}
      <li><a href="{r}vendors/index.html">All vendors</a></li>
      <li><a href="{r}methodology/index.html">Methodology</a></li>
    </ul>
  </div>
  <div>
    <h4>Brandvious network</h4>
    <ul><li>B2BIndex</li><li>BestFit</li></ul>
  </div>
</div></footer>
</body>
</html>"""


def write(path: str, content: str) -> None:
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# -------------------------------------------------------------- components
def score_note() -> str:
    """One quiet line. The full explanation lives on the methodology page."""
    return ('<p class="small muted">We do not publish a ReviewInsight score yet. '
            'Everything on this page comes straight from the review sites and links '
            'back to them. <a href="{root}methodology/index.html">How the score will work</a></p>')


def score_note_at(depth: int) -> str:
    return score_note().replace("{root}", "../" * depth)


def score_explainer() -> str:
    """Methodology page only."""
    return """<div class="formula">score = (Recent + Reliable + Results&#8209;specific + Resonance) / 4</div>
  <ul class="dims">
    <li><b>Recent</b><span class="small">How strong the review evidence is in the last 180 days.</span></li>
    <li><b>Reliable</b><span class="small">Whether the evidence holds up: do the written reviews match their star ratings, does the rating pattern look natural, do reviews arrive steadily or in bursts.</span></li>
    <li><b>Results&#8209;specific</b><span class="small">How often reviewers name a concrete outcome you could check, rather than saying it saves time.</span></li>
    <li><b>Resonance</b><span class="small">Whether reviewers recommend the product or merely tolerate it.</span></li>
  </ul>
  <p class="small muted" style="margin-top:14px">A vendor with fewer than two sites
  carrying reviews, under 15 reviews, or under 5 reviews in the last year will be
  shown as Not Rated rather than given a number.</p>"""


def spread_inline(v) -> str:
    s = spread(v)
    if not s:
        return '<div class="tiny">Needs two platforms to compare</div>'
    def pos(r):
        return max(0.0, min(100.0, (r - 1.0) / 4.0 * 100))
    pts = "".join(
        f'<span class="pt{" lo" if lbl == s["lo"][0] else ""}" style="left:{pos(r):.1f}%" '
        f'title="{e(lbl)} {r}"></span>' for lbl, r in s["all"])
    return f"""<div class="spread">
  <div class="hd"><span class="muted">Rating gap</span><span class="val">{s['points']} pts</span></div>
  <div class="track"><span class="axis"></span>{pts}</div>
  <div class="legend"><span>{e(s['lo'][0])} {s['lo'][1]}</span><span>{e(s['hi'][0])} {s['hi'][1]}</span></div>
</div>"""


def spread_detail(v) -> str:
    s = spread(v)
    if not s:
        got = portals_with_data(v)
        return f'<div class="nodata">Only {len(got)} platform carries data for {e(v["name"])}, so there is nothing to compare across platforms yet.</div>'
    W, H = 900, 108
    SHORT = {"Gartner Peer Insights": "Gartner"}
    def x(r):
        return 60 + (r - 1.0) / 4.0 * (W - 120)
    # Ratings cluster tightly, so labels collide. Stack a label onto a higher
    # row whenever it would overlap the one before it.
    rows_y = [34, 18, 2]
    marks, labels, used = [], [], []
    for lbl, r in sorted(s["all"], key=lambda p: p[1]):
        cx = x(r)
        name = SHORT.get(lbl, lbl)
        halfw = (len(name) + 4) * 3.6
        row = 0
        while row < len(rows_y) - 1 and any(
                abs(cx - ux) < (halfw + uw) and ur == row for ux, uw, ur in used):
            row += 1
        used.append((cx, halfw, row))
        marks.append(f'<circle class="mk" cx="{cx:.1f}" cy="62" r="6"/>')
        labels.append(
            f'<text class="lbl" x="{cx:.1f}" y="{rows_y[row] + 12}" text-anchor="middle">'
            f'{e(name)} {r}</text>'
            f'<line x1="{cx:.1f}" y1="{rows_y[row] + 16}" x2="{cx:.1f}" y2="56" '
            f'stroke="var(--rule)" stroke-width="1"/>')
    ticks = "".join(
        f'<line x1="{x(t):.1f}" y1="58" x2="{x(t):.1f}" y2="66" stroke="var(--rule)"/>'
        f'<text x="{x(t):.1f}" y="90" text-anchor="middle">{t}</text>' for t in (1, 2, 3, 4, 5))
    return f"""<p>Ratings for {e(v['name'])} span <b class="num">{s['points']} points</b>
across {s['n']} platforms, from {e(s['lo'][0])} at <span class="num">{s['lo'][1]}</span>
to {e(s['hi'][0])} at <span class="num">{s['hi'][1]}</span>.</p>
<div class="spreadaxis" role="img"
  aria-label="Star ratings for {e(v['name'])} plotted from 1 to 5 across {s['n']} platforms">
  <svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
    <line x1="60" y1="62" x2="{W-60}" y2="62" stroke="var(--rule)"/>
    {ticks}{''.join(marks)}{''.join(labels)}
  </svg>
</div>"""


def sources_table(v) -> str:
    rows = []
    for key, lbl in PORTALS:
        p = v["portals"][key]
        if p.get("rating") is None:
            rows.append(
                f'<tr><td>{e(lbl)}</td><td colspan="3" class="muted">No listing found</td>'
                f'<td class="muted">&mdash;</td></tr>')
            continue
        extra = ""
        if key == "gartner" and p.get("ratings_count") and p["ratings_count"] != p["count"]:
            extra = f'<div class="tiny">{p["ratings_count"]:,} ratings</div>'
        if key == "capterra" and p.get("sub_ratings"):
            extra = '<div class="tiny">' + " &middot; ".join(
                f"{e(k)} {val}" for k, val in p["sub_ratings"].items()) + "</div>"
        rows.append(
            f'<tr><td>{e(lbl)}</td>'
            f'<td class="n">{p["rating"]}</td>'
            f'<td class="n">{p["count"]:,}{extra}</td>'
            f'<td class="tiny">{e(p["captured_at"][:10])}</td>'
            f'<td><a href="{e(p["url"])}" rel="nofollow noopener" target="_blank">Open&nbsp;&#8599;</a></td></tr>')
    return f"""<div class="tscroll"><table>
<thead><tr><th>Platform</th><th class="n">Rating</th><th class="n">Reviews</th>
<th>Checked</th><th>Source</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def evidence(q) -> str:
    bits = [b for b in [q.get("role"), q.get("company_size")] if b]
    who = " &middot; ".join(e(b) for b in bits) if bits else "Reviewer details not published"
    if q.get("body_gated"):
        body = (f'<blockquote>&ldquo;{e(q["title"] or "")}&rdquo;</blockquote>'
                f'<p class="tiny">Gartner publishes the headline, rating and date but puts the '
                f'review body behind a login, so we quote only the headline.</p>')
        cls = "ev gated"
    else:
        body = f'<blockquote>&ldquo;{e(q["text"] or "")}&rdquo;</blockquote>'
        cls = "ev"
    rating = f'<span class="num">{q["rating"]}</span> &middot; ' if q.get("rating") else ""
    return f"""<div class="{cls}">{body}
  <div class="prov">{rating}<span>{e(q["portal"])}</span><span class="sep">&middot;</span>
    <span>{e(q.get("date") or "undated")}</span><span class="sep">&middot;</span>
    <span>{who}</span><span class="sep">&middot;</span>
    <a href="{e(q["source_url"])}" rel="nofollow noopener" target="_blank">Read on {e(q["portal"])}&nbsp;&#8599;</a>
  </div></div>"""


def rank_row(i: int, v, depth: int) -> str:
    r = "../" * depth
    got = portals_with_data(v)
    nr = newest_review(v)
    return f"""<div class="rrow">
  <div class="pos">{i}</div>
  <div><span class="scorebox pending"><span class="v">&mdash;</span><span class="d">pending</span></span></div>
  <div class="who">
    <h3><a href="{r}vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
    <div class="meta">{e(v['category_name'])}</div>
    <div class="facts">
      <span><b class="num">{total_reviews(v):,}</b> reviews</span>
      <span><b class="num">{len(got)}</b> of 4 platforms</span>
      {f'<span>newest <b class="num">{nr.strftime("%d %b %Y")}</b></span>' if nr else ''}
      <a class="small" href="{r}vendors/{v['slug']}/alternatives/index.html">Alternatives</a>
    </div>
  </div>
  <div class="spread-cell">{spread_inline(v)}</div>
</div>"""


# ------------------------------------------------------------------- pages
def page_home() -> None:
    cats = "".join(
        f'<div class="card"><h3><a href="categories/{c}/index.html">{e(m["name"])}</a></h3>'
        f'<p class="small muted">{len(cat_vendors(c))} vendors read across four platforms.</p>'
        f'<p class="small"><a href="categories/{c}/index.html">See the ranking</a></p></div>'
        for c, m in CATS.items())
    widest = sorted((v for v in VENDORS.values() if spread(v)),
                    key=lambda v: spread(v)["points"], reverse=True)[:3]
    rows = "".join(
        f'<tr><td><a href="vendors/{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="n">{spread(v)["points"]}</td>'
        f'<td class="small">{e(spread(v)["lo"][0])} {spread(v)["lo"][1]} '
        f'vs {e(spread(v)["hi"][0])} {spread(v)["hi"][1]}</td></tr>' for v in widest)
    body = f"""<h1 style="margin-top:34px">Four review sites, read together</h1>
<div class="lede">Buyers check G2, then Capterra, then Trustpilot, and get three
different answers. We read all four for every vendor, publish what each one says
with a link back to it, and are building a single score on top. Vendors cannot pay
for placement.</div>
{score_note_at(0)}

<section class="section rule-top">
  <h2>Categories</h2>
  <div class="cols">{cats}</div>
</section>

<section class="section rule-top">
  <h2>Where the sites disagree most</h2>
  <p class="small muted">The gap between a vendor's highest and lowest rated platform,
  in stars. Every vendor has one; these are the largest in the set.</p>
  <div class="tscroll"><table>
    <thead><tr><th>Vendor</th><th class="n">Rating gap</th><th>Between</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
</section>
"""
    write("index.html", shell(0, "ReviewInsight",
          "Independent review intelligence for B2B software buyers.", body))


def page_categories() -> None:
    items = "".join(
        f'<li><a href="{c}/index.html">{e(m["name"])}</a>'
        f'<span class="num">{len(cat_vendors(c))} vendors</span></li>' for c, m in CATS.items())
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>Categories</h1>
<div class="lede">Two categories are live while we prove the data. Each vendor in
them is read across all four review platforms.</div>
<ul class="catlist">{items}</ul>"""
    write("categories/index.html",
          shell(1, "Categories | ReviewInsight", "B2B software categories.", body, "cat"))


def page_category(cat: str, meta: dict) -> None:
    vs = cat_vendors(cat)
    rows = "".join(rank_row(i, v, 2) for i, v in enumerate(vs, 1))
    spreads = sorted(spread(v)["points"] for v in vs if spread(v))
    med = spreads[len(spreads) // 2] if spreads else 0
    body = f"""<div class="crumb"><a href="../../index.html">Home</a> / <a href="../index.html">Categories</a></div>
<h1>{e(meta['name'])}</h1>
<div class="lede">{len(vs)} vendors, read across G2, Capterra, Gartner Peer Insights
and Trustpilot on {CAPTURED}. The median platform spread in this category is
{med} points.</div>

<p class="small muted">Ordered by total review volume while the score is being built.
Volume is not the ranking we intend to publish, it is a stand-in you can verify.</p>
<div class="rank">{rows}</div>

{score_note_at(2)}

<section class="section rule-top">
  <h2>Cuts of this category</h2>
  <div class="cols">
    <div class="card"><h3><a href="../../best/{cat}/for-recent-activity/index.html">Most active review base</a></h3>
      <p class="small muted">Vendors whose newest reviews are the freshest.</p></div>
    <div class="card"><h3><a href="../../best/{cat}/for-consistent-ratings/index.html">Most consistent across platforms</a></h3>
      <p class="small muted">Vendors the four platforms agree on most closely.</p></div>
  </div>
</section>
"""
    write(f"categories/{cat}/index.html",
          shell(2, f"{meta['name']} | ReviewInsight",
                f"{meta['name']} vendors read across four review platforms.", body, "cat"))


def page_vendors_index() -> None:
    rows = "".join(
        f'<tr><td><a href="{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="small">{e(v["category_name"])}</td>'
        f'<td class="n">{total_reviews(v):,}</td>'
        f'<td class="n">{len(portals_with_data(v))}/4</td>'
        f'<td class="n">{spread(v)["points"] if spread(v) else "&mdash;"}</td></tr>'
        for v in sorted(VENDORS.values(), key=lambda x: x["name"].lower()))
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>All vendors</h1>
<div class="lede">Every vendor we currently read, with the size of its review base
and how far the platforms disagree.</div>
<div class="tscroll"><table>
<thead><tr><th>Vendor</th><th>Category</th><th class="n">Reviews</th>
<th class="n">Platforms</th><th class="n">Rating gap</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""
    write("vendors/index.html",
          shell(1, "All vendors | ReviewInsight", "Every vendor read by ReviewInsight.", body, "ven"))


def page_vendor(v) -> None:
    qs = all_quotes(v)[:6]
    got = portals_with_data(v)
    nr = newest_review(v)
    peers = [p for p in cat_vendors(v["category"]) if p["slug"] != v["slug"]][:2]
    cmp_cards = "".join(
        f'<div class="card"><h3><a href="../../compare/{pair_slug(v, p)}/index.html">'
        f'{e(v["name"])} vs {e(p["name"])}</a></h3></div>' for p in peers)
    ev = "".join(evidence(q) for q in qs) or '<div class="nodata">No quotes captured yet.</div>'
    body = f"""<div class="crumb"><a href="../../index.html">Home</a> /
<a href="../../categories/{v['category']}/index.html">{e(v['category_name'])}</a></div>
<h1>{e(v['name'])}</h1>
<div class="lede">{total_reviews(v):,} reviews across {len(got)} of 4 platforms.
{f'Newest review {nr.strftime("%d %B %Y")}.' if nr else ''}</div>
<p class="stamp">Checked {CAPTURED}</p>

<section class="section rule-top">
  <h2>What each platform says</h2>
  {sources_table(v)}
</section>

<section class="section rule-top">
  <h2>How far the platforms disagree</h2>
  {spread_detail(v)}
</section>

<section class="section rule-top">
  <h2>What reviewers said</h2>
  <p class="small muted">Quotes are trimmed to 40 words and link back to the original.
  We publish the reviewer's role and company size where the platform shows it, never their name.</p>
  {ev}
</section>

<section class="section rule-top">
  {score_note_at(2)}
</section>

<section class="section rule-top">
  <h2>Compare {e(v['name'])}</h2>
  <div class="cols">{cmp_cards}
    <div class="card"><h3><a href="alternatives/index.html">All alternatives</a></h3></div>
  </div>
</section>"""
    write(f"vendors/{v['slug']}/index.html",
          shell(2, f"{v['name']} reviews | ReviewInsight",
                f"{v['name']} read across G2, Capterra, Gartner and Trustpilot.", body, "ven"))


def page_alternatives(v) -> None:
    peers = [p for p in cat_vendors(v["category"]) if p["slug"] != v["slug"]]
    rows = "".join(
        f'<tr><td><a href="../../{p["slug"]}/index.html">{e(p["name"])}</a></td>'
        f'<td class="n">{total_reviews(p):,}</td>'
        f'<td class="n">{len(portals_with_data(p))}/4</td>'
        f'<td class="n">{spread(p)["points"] if spread(p) else "&mdash;"}</td>'
        f'<td><a href="../../../compare/{pair_slug(v, p)}/index.html">Compare</a></td></tr>'
        for p in peers)
    body = f"""<div class="crumb"><a href="../../../index.html">Home</a> /
<a href="../index.html">{e(v['name'])}</a></div>
<h1>{e(v['name'])} alternatives</h1>
<div class="lede">Every other vendor we read in {e(v['category_name'])}, with the size
of its review base and how far the platforms disagree about it.</div>
<div class="tscroll"><table>
<thead><tr><th>Vendor</th><th class="n">Reviews</th><th class="n">Platforms</th>
<th class="n">Rating gap</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"""
    write(f"vendors/{v['slug']}/alternatives/index.html",
          shell(3, f"{v['name']} alternatives | ReviewInsight",
                f"Alternatives to {v['name']} in {v['category_name']}.", body, "ven"))


def pair_slug(a, b) -> str:
    return "-vs-".join(sorted([a["slug"], b["slug"]]))


def page_compare(a, b) -> None:
    def col(v):
        return f"""<div>
  <h3><a href="../../vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
  <p class="small muted">{total_reviews(v):,} reviews across {len(portals_with_data(v))} of 4 platforms</p>
  {sources_table(v)}
  <div style="margin-top:16px">{spread_inline(v)}</div>
</div>"""
    sa, sb = spread(a), spread(b)
    verdict = (f"The platforms agree more closely about {e(a['name'] if sa['points'] < sb['points'] else b['name'])} "
               f"({min(sa['points'], sb['points'])} points apart) than about "
               f"{e(b['name'] if sa['points'] < sb['points'] else a['name'])} "
               f"({max(sa['points'], sb['points'])} points apart)."
               if sa and sb else "One of these vendors does not have enough platforms to compare.")
    body = f"""<div class="crumb"><a href="../../index.html">Home</a> /
<a href="../../categories/{a['category']}/index.html">{e(a['category_name'])}</a></div>
<h1>{e(a['name'])} vs {e(b['name'])}</h1>
<div class="lede">{verdict}</div>
<div class="two">{col(a)}{col(b)}</div>"""
    write(f"compare/{pair_slug(a, b)}/index.html",
          shell(2, f"{a['name']} vs {b['name']} | ReviewInsight",
                f"{a['name']} and {b['name']} compared across four review platforms.", body))


def page_best(cat: str, meta: dict, cut: str) -> None:
    vs = [v for v in cat_vendors(cat)]
    if cut == "recent-activity":
        title = "Most active review base"
        blurb = ("Ordered by how recent the newest review we captured is. A vendor whose "
                 "reviews stopped two years ago is telling you something.")
        vs = [v for v in vs if newest_review(v)]
        vs.sort(key=lambda v: newest_review(v), reverse=True)
        col, val = "Newest review", lambda v: newest_review(v).strftime("%d %b %Y")
    else:
        title = "Most consistent across platforms"
        blurb = ("Ordered by the gap between a vendor's highest and lowest rated platform. "
                 "A small gap means the four platforms tell the same story.")
        vs = [v for v in vs if spread(v)]
        vs.sort(key=lambda v: spread(v)["points"])
        col, val = "Rating gap", lambda v: f'{spread(v)["points"]} pts'
    rows = "".join(
        f'<tr><td class="n">{i}</td><td><a href="../../../vendors/{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="n">{val(v)}</td><td class="n">{total_reviews(v):,}</td></tr>'
        for i, v in enumerate(vs[:8], 1))
    body = f"""<div class="crumb"><a href="../../../index.html">Home</a> /
<a href="../../../categories/{cat}/index.html">{e(meta['name'])}</a></div>
<h1>{e(meta['name'])}: {title.lower()}</h1>
<div class="lede">{blurb}</div>
<div class="tscroll"><table>
<thead><tr><th class="n">#</th><th>Vendor</th><th class="n">{col}</th>
<th class="n">Reviews</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small muted" style="margin-top:16px">This cut uses one measured signal only.
It is not the ReviewInsight score.</p>"""
    write(f"best/{cat}/for-{cut}/index.html",
          shell(3, f"{meta['name']}: {title} | ReviewInsight", blurb, body, "cat"))


def page_methodology() -> None:
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>Methodology</h1>
<div class="lede">What we read, what we publish, and what we have not built yet.
This page will carry a version number and a changelog before the site is public.</div>

<section class="section rule-top">
  <h2>Where the data comes from</h2>
  <p>For every vendor we read four platforms and record the average rating, the number
  of reviews, and a sample of review text with its date. Each figure carries the page
  it came from and the day we checked it. Nothing is typed in by hand.</p>
  {sources_note()}
</section>

<section class="section rule-top">
  <h2>The score</h2>
  {score_explainer()}
</section>

<section class="section rule-top">
  <h2>What we will not do</h2>
  <ul class="dims">
    <li><b>No paid placement</b><span class="small">A vendor cannot buy a rank, a badge, or a better score. There is no vendor tier to sell.</span></li>
    <li><b>No invented numbers</b><span class="small">If we cannot read a figure we show that we could not, with the counts we do have. We never fill a gap with an estimate.</span></li>
    <li><b>No republished reviews</b><span class="small">Quotes are trimmed to 40 words, attributed, dated, and linked to the original. Reviewer names are dropped when we read the page, so we never store them.</span></li>
    <li><b>No hidden arithmetic</b><span class="small">Every score will show its inputs and its sum on the page, so you can redo it.</span></li>
  </ul>
</section>

<section class="section rule-top">
  <h2>Known gaps</h2>
  <p class="small">Gartner Peer Insights puts most review bodies behind a login. We use its
  headline, rating and date, and do not touch the gated text. Two vendors in this preview
  have no listing on one platform, which we show rather than hide.</p>
</section>"""
    write("methodology/index.html",
          shell(1, "Methodology | ReviewInsight", "How ReviewInsight reads and publishes review data.", body, "meth"))


def sources_note() -> str:
    rows = "".join(
        f"<tr><td>{e(lbl)}</td><td class='n'>{sum(1 for v in VENDORS.values() if v['portals'][k].get('rating') is not None)}"
        f" of {len(VENDORS)}</td><td class='small'>"
        f"{'Rating, review count, review text with dates' if k != 'gartner' else 'Rating, review and rating counts, review headlines with dates. Bodies are login-gated.'}"
        f"</td></tr>" for k, lbl in PORTALS)
    return f"""<div class="tscroll"><table>
<thead><tr><th>Platform</th><th class="n">Vendors covered</th><th>What we take</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""


def page_quarterly() -> None:
    rows = "".join(
        f'<tr><td><a href="../../vendors/{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="small">{e(v["category_name"])}</td>'
        + "".join(f'<td class="n">{v["portals"][k]["rating"] or "&mdash;"}</td>' for k, _ in PORTALS)
        + f'<td class="n">{total_reviews(v):,}</td></tr>'
        for v in sorted(VENDORS.values(), key=lambda x: x["name"].lower()))
    heads = "".join(f'<th class="n">{e(l)}</th>' for _, l in PORTALS)
    body = f"""<div class="crumb"><a href="../../index.html">Home</a></div>
<h1>{QUARTER} index</h1>
<div class="lede">Every rating we captured on {CAPTURED}, in one table. This page is
frozen so a figure quoted from it stays checkable after the live pages move on.</div>
<div class="tscroll"><table>
<thead><tr><th>Vendor</th><th>Category</th>{heads}<th class="n">Reviews</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="small muted" style="margin-top:16px">Ratings are each platform's own average
on the day we checked. We have not combined them into a single figure here.</p>"""
    write(f"quarterly/{QUARTER.lower()}/index.html",
          shell(2, f"{QUARTER} index | ReviewInsight",
                f"All captured ratings for {QUARTER}.", body, "q"))


# --------------------------------------------------------------------- run
def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy(HERE / "ri.css", OUT / "ri.css")

    page_home()
    page_categories()
    page_vendors_index()
    page_methodology()
    page_quarterly()

    pairs = set()
    for cat, meta in CATS.items():
        page_category(cat, meta)
        page_best(cat, meta, "recent-activity")
        page_best(cat, meta, "consistent-ratings")
        vs = cat_vendors(cat)
        for v in vs:
            page_vendor(v)
            page_alternatives(v)
        # every pair reachable from a profile or an alternatives table
        for i, a in enumerate(vs):
            for b in vs:
                if a["slug"] != b["slug"]:
                    pairs.add(tuple(sorted([a["slug"], b["slug"]])))
    for a_slug, b_slug in sorted(pairs):
        page_compare(VENDORS[a_slug], VENDORS[b_slug])

    n = sum(1 for _ in OUT.rglob("*.html"))
    print(f"built {n} pages into {OUT}")


if __name__ == "__main__":
    main()
