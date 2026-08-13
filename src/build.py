"""Render the ReviewInsight preview from the pulled data.

Every number on every page comes from data/*.json and carries its source and
capture date. The composite score is deliberately a pending state: we have not
computed it yet, so we show the formula and what is still missing rather than
inventing a figure.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA = json.loads((HERE / "data" / "_all.json").read_text(encoding="utf-8"))
OUT = HERE / "site"

SCORED = json.loads((HERE / "data" / "_scores.json").read_text(encoding="utf-8"))
SCORES: dict = SCORED["scores"]
WEIGHTS: dict = SCORED["weights"]
FLOORS: dict = SCORED["floors"]

VENDORS: dict = DATA["vendors"]
CATS: dict = DATA["categories"]
PORTALS = [("g2", "G2"), ("capterra", "Capterra"),
           ("gartner", "Gartner Peer Insights"), ("trustpilot", "Trustpilot")]
CAPTURED = datetime.fromisoformat(DATA["generated_at"]).strftime("%d %B %Y")
QUARTER = "2026-Q3"
CSS_V = hashlib.sha256(
    (HERE / "ri.css").read_bytes()).hexdigest()[:10]

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


def sc(v) -> dict:
    return SCORES.get(v["slug"], {"rated": False, "not_rated": ["missing"]})


def score_of(v) -> int | None:
    r = sc(v)
    return r["score"] if r.get("rated") else None


def dims_of(v) -> list:
    return [d for d in sc(v).get("dimensions", []) if d["key"] != "rating"]


def cat_vendors(cat: str) -> list:
    """Ranked by score. Unrated vendors sort last, by review volume."""
    vs = [v for v in VENDORS.values() if v["category"] == cat]
    return sorted(vs, key=lambda v: (-(score_of(v) or -1), -total_reviews(v)))


# ------------------------------------------------------------------- shell
def shell(depth: int, title: str, desc: str, body: str, nav: str = "",
          bare: bool = False) -> str:
    r = "../" * depth if depth else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="stylesheet" href="{r}ri.css?v={CSS_V}">
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
{'' if bare else '<main class="wrap">'}
{body}
{'' if bare else '</main>'}
<footer class="foot"><div class="wrap">
  <div>
    <h4>ReviewInsight</h4>
    <p>Independent review intelligence for B2B software buyers. We read G2,
    Capterra, Gartner Peer Insights and Trustpilot side by side and publish what
    they agree and disagree on. Vendors cannot pay for placement.</p>
    <p class="tiny" style="margin-top:10px">Editorial and independent. Vendors cannot
    buy a listing, a rank, or a removal.</p>
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
    <h4>Sources we read</h4>
    <ul>{''.join(f'<li>{e(lbl)}</li>' for _, lbl in PORTALS)}</ul>
  </div>
</div></footer>
</body>
</html>"""


def write(path: str, content: str) -> None:
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# -------------------------------------------------------------- components
def scorebox(v, big: bool = False) -> str:
    r = sc(v)
    if not r.get("rated"):
        return ('<span class="scorebox pending"><span class="v">NR</span>'
                '<span class="d">not rated</span></span>')
    cls = "scorebox" + (" big" if big else "")
    return (f'<span class="{cls}"><span class="v">{r["score"]}</span>'
            f'<span class="d">/100</span></span>')


def bar(value: float) -> str:
    w = max(0.0, min(100.0, float(value)))
    return f'<span class="barwrap"><span class="bar" style="width:{w:.0f}%"></span></span>'


def dim_block(v, depth: int) -> str:
    """The four Rs with their arithmetic, so a reader can redo the score."""
    r = sc(v)
    if not r.get("rated"):
        need = ", ".join(r.get("not_rated", []))
        el = r.get("eligibility", {})
        return (f'<div class="nodata"><b>Not rated.</b> We need at least '
                f'{FLOORS["sites"]} sites carrying reviews, {FLOORS["reviews"]} reviews, '
                f'and {FLOORS["recent_reviews"]} from the last year. '
                f'{e(v["name"])} has {el.get("sites","?")} sites, '
                f'{el.get("reviews","?")} reviews and {el.get("recent_reviews","?")} recent. '
                f'Short on: {e(need)}.</div>')
    rows = []
    for d in dims_of(v):
        parts = "".join(
            f'<li><span>{e(pt["name"])}</span><span class="muted">{e(pt["detail"])}</span>'
            f'<span class="num">{pt["value"]}</span></li>' for pt in d.get("parts", []))
        rows.append(f"""<div class="dimrow">
  <div class="dimhd"><b>{e(d['label'])}</b>
    <span class="tiny muted">weight {int(WEIGHTS[d['key']]*100)}%</span>
    <span class="num dimval">{d['value']}</span></div>
  {bar(d['value'])}
  <details><summary class="tiny">How this was worked out</summary>
    <div class="formula">{e(d['math'])}</div>
    <ul class="dimparts">{parts}</ul></details>
</div>""")
    rating = next(x for x in sc(v)["dimensions"] if x["key"] == "rating")
    return f"""<div class="scorepanel">
  <div class="scoretop">
    {scorebox(v, big=True)}
    <div>
      <p>Reviewers rate {e(v['name'])} <b class="num">{rating['value']}</b> out of 100.
      The evidence behind that comes out at <b class="num">{r['evidence']}</b>, so we publish
      <b class="num">{r['score']}</b>.</p>
      <details class="mathtoggle">
        <summary class="tiny">Show the arithmetic</summary>
        <div class="formula">rating   = {e(rating['math'])}
evidence = {e(r['evidence_math'])}
score    = {e(r['score_math'])}</div>
      </details>
      <p class="tiny muted">Measured on {r['sample_size']} reviews, {r['labelled']} of them
      read and labelled. <a href="{'../' * depth}methodology/index.html">How the score works</a></p>
    </div>
  </div>
  {''.join(rows)}
</div>"""


def score_note_at(depth: int) -> str:
    return ('<p class="small muted">Scores combine what reviewers rate a product with how '
            'strong the evidence behind that rating is. '
            f'<a href="{"../" * depth}methodology/index.html">How the score works</a></p>')


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
    dchips = "".join(
        f'<span class="chip">{e(d["label"].split("-")[0])} <b class="num">{d["value"]:.0f}</b></span>'
        for d in dims_of(v))
    return f"""<div class="rrow">
  <div class="pos">{i}</div>
  <div>{scorebox(v)}</div>
  <div class="who">
    <h3><a href="{r}vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
    <div class="meta">{e(v['category_name'])}</div>
    <div class="facts">{dchips}
      <span><b class="num">{total_reviews(v):,}</b> reviews</span>
      <span><b class="num">{len(got)}</b> of 4 sites</span>
      <a class="small" href="{r}vendors/{v['slug']}/alternatives/index.html">Alternatives</a>
    </div>
  </div>
  <div class="spread-cell">{spread_inline(v)}</div>
</div>"""


# ------------------------------------------------------------------- pages
def page_home() -> None:
    scored = sorted((v for v in VENDORS.values() if score_of(v) is not None),
                    key=lambda v: -score_of(v))
    top = scored[0]
    tr = sc(top)
    reviews_read = sum(sc(v).get("sample_size", 0) for v in VENDORS.values())
    behind = sum(p["count"] or 0 for v in VENDORS.values()
                 for _, _, p in portals_with_data(v))
    cells = sum(len(portals_with_data(v)) for v in VENDORS.values())

    # The sibling property opens with a real record. Ours opens with a real score.
    rows = "".join(
        f'<div class="sprow"><span>{e(d["label"])}</span>'
        f'<span class="num">{d["value"]}</span></div>' for d in dims_of(top))
    sites = "".join(f'<span class="minichip">{e(lbl)} {p["rating"]}</span>'
                    for _, lbl, p in portals_with_data(top))
    specimen = f"""<div class="specimen">
  <div class="sphd"><b>{e(top['name'])}</b>
    <span class="verified">Score {tr['score']}</span></div>
  <div class="sprow"><span>Category</span><span>{e(top['category_name'])}</span></div>
  <div class="sprow"><span>Reviewers rate it</span><span class="num">{tr['rating']}</span></div>
  <div class="sprow"><span>Evidence strength</span><span class="num">{tr['evidence']}</span></div>
  {rows}
  <div class="spfoot">{sites}</div>
</div>"""

    vendormap = json.dumps({v["name"].lower(): v["slug"] for v in VENDORS.values()})
    vendoropts = "".join(
        f'<option value="{e(v["name"])}">' for v in
        sorted(VENDORS.values(), key=lambda x: x["name"].lower()))

    stats = [(f"{len(VENDORS)}", "vendors scored"),
             (f"{behind:,}", "reviews behind those scores"),
             (f"{reviews_read:,}", "reviews read one by one"),
             (f"{cells} of {len(VENDORS)*4}", "vendor and site pairs checked"),
             ("None", "vendors who paid to be here")]
    statbar = "".join(f'<div class="stat"><b class="num">{e(n)}</b><span>{e(l)}</span></div>'
                      for n, l in stats)

    def leaderboard(vs, limit=None):
        rows = vs[:limit] if limit else vs
        return "".join(f"""<div class="lrow">
  <span class="lpos num">{i}</span>
  {scorebox(v)}
  <div class="lwho"><h3><a href="vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
    <div class="tiny muted">{e(v['category_name'])} &middot;
      {total_reviews(v):,} reviews across {len(portals_with_data(v))} sites</div></div>
  <div class="lchips">{''.join(
      f'<span class="chip">{e(d["label"].split("-")[0])} <b class="num">{d["value"]:.0f}</b></span>'
      for d in dims_of(v))}</div>
</div>""" for i, v in enumerate(rows, 1))

    scopes = [("all", "All vendors", scored, "vendors/index.html",
               f"All {len(VENDORS)} vendors")]
    for c, m in CATS.items():
        scopes.append((c, m["name"], cat_vendors(c), f"categories/{c}/index.html",
                       f"Full {m['name']} ranking"))

    radios = "".join(
        f'<input class="tabradio" type="radio" name="scope" id="sc-{k}"'
        f'{" checked" if i == 0 else ""}>' for i, (k, *_ ) in enumerate(scopes))
    tablist = "".join(f'<label for="sc-{k}">{e(n)}</label>' for k, n, *_ in scopes)
    panels = "".join(f"""<div class="tabpanel" id="panel-{k}">
    <div class="lead">{leaderboard(vs, 8)}</div>
    <a class="morelink" href="{href}">{e(cta)} &rarr;</a>
  </div>""" for k, n, vs, href, cta in scopes)

    ranking = f"""<div class="tabs">{radios}
  <div class="tablist">{tablist}</div>
  {panels}
</div>"""

    rs = [("recent", "Recent", "How much of the evidence comes from the last year, and how fresh the newest review is."),
          ("reliable", "Reliable", "Whether the sites agree with each other, and whether written reviews match the stars they carry."),
          ("results", "Results-specific", "How often reviewers name an outcome a stranger could check, rather than saying it saves time."),
          ("resonance", "Resonance", "Whether reviewers recommend the product or merely put up with it.")]
    rgrid = "".join(
        f'<div class="rcard"><b>{e(n)}</b><span class="tiny muted">weight {int(WEIGHTS[k]*100)}%</span>'
        f'<p class="small">{e(d)}</p></div>' for k, n, d in rs)

    allv = "".join(f'<a href="vendors/{v["slug"]}/index.html">{e(v["name"])}</a>'
                   for v in sorted(VENDORS.values(), key=lambda x: x["name"].lower()))

    widest = sorted((v for v in VENDORS.values() if spread(v)),
                    key=lambda v: spread(v)["points"], reverse=True)[:4]
    gaps = "".join(
        f'<tr><td><a href="vendors/{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="n">{spread(v)["points"]}</td>'
        f'<td class="small">{e(spread(v)["lo"][0])} {spread(v)["lo"][1]} '
        f'vs {e(spread(v)["hi"][0])} {spread(v)["hi"][1]}</td></tr>' for v in widest)

    body = f"""<section class="hero2"><div class="wrap">
  <div>
    <h1>Software reviews,<br>read four at a time.</h1>
    <p class="sub">G2, Capterra, Gartner Peer Insights and Trustpilot rate the same product
    differently. ReviewInsight reads all four for every vendor, reads the reviews themselves
    rather than counting them, and publishes one score with the arithmetic attached.</p>
    <p class="sub">No vendor can pay to appear here, rank higher, or have anything removed.</p>
    <form class="lookup" onsubmit="return riGo(this)">
      <input id="riq" list="ri-vendors" autocomplete="off" required
             placeholder="Look up any vendor" aria-label="Look up any vendor">
      <button type="submit" aria-label="Go">&rarr;</button>
      <datalist id="ri-vendors">{vendoropts}</datalist>
    </form>
    <p class="lookuphint tiny">{len(VENDORS)} vendors across
      {''.join(f'<a href="categories/{c}/index.html">{e(m["name"])}</a>'
               + (", " if i == 0 else "") for i, (c, m) in enumerate(CATS.items()))}.
      <a href="methodology/index.html">How we score</a>.</p>
  </div>
  {specimen}
</div></section>

<section class="statband"><div class="wrap">{statbar}</div></section>

<section class="band"><div class="wrap">
  <div class="eyebrow">Rankings</div>
  <div>
    <h2>Highest scored</h2>
    <p class="intro">A score is what reviewers rate a product, moved toward the middle when
    the evidence behind that rating is thin, stale or contradictory. Pick a category to
    rank within it.</p>
    {ranking}
  </div>
</div></section>

<section class="band tint"><div class="wrap">
  <div class="eyebrow">Method</div>
  <div>
    <h2>What the score measures</h2>
    <p class="intro">Four things decide how far a vendor moves away from neutral. Every one
    of them is published, and every number on a vendor page can be rebuilt by hand.</p>
    <div class="rgrid">{rgrid}</div>
    <a class="morelink" href="methodology/index.html">Full method &rarr;</a>
  </div>
</div></section>

<section class="band"><div class="wrap">
  <div class="eyebrow">Finding</div>
  <div>
    <h2>Where the sites disagree</h2>
    <p class="intro">The gap between a vendor's highest and lowest rated site, in stars.
    Every vendor has one. A wide gap means no single rating tells the story.</p>
    <div class="tscroll"><table>
      <thead><tr><th>Vendor</th><th class="n">Rating gap</th><th>Between</th></tr></thead>
      <tbody>{gaps}</tbody></table></div>
  </div>
</div></section>

<section class="band tint"><div class="wrap">
  <div class="eyebrow">Vendors</div>
  <div>
    <h2>Everyone we read</h2>
    <div class="plainlist">{allv}</div>
    <a class="morelink" href="vendors/index.html">Full list with scores &rarr;</a>
  </div>
</div></section>
<script>
const RI_VENDORS = {vendormap};
function riGo(f) {{
  const q = document.getElementById('riq').value.trim().toLowerCase();
  let hit = RI_VENDORS[q];
  if (!hit) {{
    const k = Object.keys(RI_VENDORS).find(n => n.includes(q));
    if (k) hit = RI_VENDORS[k];
  }}
  if (hit) location.href = 'vendors/' + hit + '/index.html';
  else location.href = 'vendors/index.html';
  return false;
}}
</script>"""
    write("index.html", shell(0, "ReviewInsight",
          "One score per B2B software vendor, read across G2, Capterra, Gartner Peer "
          "Insights and Trustpilot.", body, bare=True))


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

<p class="small muted">Ranked by ReviewInsight score. Each score is what reviewers rate
the product, adjusted for how strong the evidence behind that rating is.</p>
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
        f'<tr><td class="n">{score_of(v) if score_of(v) else "NR"}</td>'
        f'<td><a href="{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="small">{e(v["category_name"])}</td>'
        f'<td class="n">{total_reviews(v):,}</td>'
        f'<td class="n">{len(portals_with_data(v))}/4</td>'
        f'<td class="n">{spread(v)["points"] if spread(v) else "&mdash;"}</td></tr>'
        for v in sorted(VENDORS.values(), key=lambda x: -(score_of(x) or -1)))
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>All vendors</h1>
<div class="lede">Every vendor we currently read, with the size of its review base
and how far the platforms disagree.</div>
<div class="tscroll"><table>
<thead><tr><th class="n">Score</th><th>Vendor</th><th>Category</th><th class="n">Reviews</th>
<th class="n">Sites</th><th class="n">Rating gap</th></tr></thead>
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
  <h2>The score</h2>
  {dim_block(v, 2)}
</section>

<section class="section rule-top">
  <h2>What each site says</h2>
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
        rows = "".join(
            f'<div class="dimrow"><div class="dimhd"><b>{e(d["label"])}</b>'
            f'<span class="num dimval">{d["value"]}</span></div>{bar(d["value"])}</div>'
            for d in dims_of(v))
        return f"""<div>
  <h3>{scorebox(v)} <a href="../../vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
  <p class="small muted">{total_reviews(v):,} reviews across {len(portals_with_data(v))} of 4 sites</p>
  {rows}
  {sources_table(v)}
  <div style="margin-top:16px">{spread_inline(v)}</div>
</div>"""

    ra, rb = score_of(a), score_of(b)
    if ra is not None and rb is not None and ra != rb:
        win, lose = (a, b) if ra > rb else (b, a)
        da = {d["key"]: d["value"] for d in dims_of(win)}
        db = {d["key"]: d["value"] for d in dims_of(lose)}
        gap = max(da, key=lambda k: da[k] - db[k])
        gl = next(d["label"] for d in dims_of(win) if d["key"] == gap)
        verdict = (f"{e(win['name'])} scores {max(ra, rb)} against {e(lose['name'])} at "
                   f"{min(ra, rb)}. The widest difference is {e(gl.lower())}, "
                   f"{da[gap]:.0f} against {db[gap]:.0f}.")
    elif ra is not None and rb is not None:
        verdict = f"Both score {ra}. The difference is in which dimensions get them there."
    else:
        verdict = "One of these does not have enough review evidence to score."
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
    evw = " + ".join(f"{w:.2f} {k.capitalize()}" for k, w in WEIGHTS.items())
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>Methodology</h1>
<div class="lede">What we read, how the score is worked out, and what we deliberately
do not do. Every figure on the site can be rebuilt from the numbers on the vendor pages.</div>

<section class="section rule-top">
  <h2>Where the data comes from</h2>
  <p>For every vendor we read four platforms and record the average rating, the number
  of reviews, and a sample of review text with its date. Each figure carries the page
  it came from and the day we checked it. Nothing is typed in by hand.</p>
  {sources_note()}
</section>

<section class="section rule-top">
  <h2>The score</h2>
  <p>Two things decide it. What reviewers rate a product, and how much that rating
  can be trusted. We publish both, and the second one adjusts the first.</p>
  <div class="formula">rating   = the four sites' own averages, averaged, x20</div>
  <div class="formula">evidence = {evw}</div>
  <div class="formula">score    = 50 + (rating - 50) x evidence / 100</div>
  <p>A product with perfect evidence scores exactly what reviewers rate it. A product
  with no usable evidence sits at 50, because we do not know anything about it. Everything
  else lands in between, moved away from the middle only as far as its evidence earns.</p>
  {score_explainer()}
</section>

<section class="section rule-top">
  <h2>Where each number comes from</h2>
  <div class="tscroll"><table>
  <thead><tr><th>Part</th><th>Measured from</th></tr></thead>
  <tbody>
    <tr><td>Recent</td><td>How many days since the newest review, and what share of the
      reviews we hold were written in the last year.</td></tr>
    <tr><td>Reliable</td><td>How far apart the sites' star ratings are, and how often a
      review's wording matches the stars it was given.</td></tr>
    <tr><td>Results-specific</td><td>The share of reviews naming an outcome a stranger
      could check. A number, a time saved, a tool replaced. Not "saves time".</td></tr>
    <tr><td>Resonance</td><td>Whether reviewers recommend the product, approve of it,
      tolerate it, or warn you off. Averaged per site, then across sites.</td></tr>
  </tbody></table></div>
  <p class="small muted">Two of the four need the review text read. A model labels each
  review and has to quote the exact words behind its label; if those words are not
  literally in the review, the label is thrown away. Every calculation is done in code,
  never by the model.</p>
  <p class="small muted">G2 gives us no working pagination, so we read it through four
  sort orders. Two of those return the best and worst reviews on purpose, so we use them
  for quotes and keep them out of every rate. Gartner keeps review text behind a login,
  so it contributes ratings and dates but not tone.</p>
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
