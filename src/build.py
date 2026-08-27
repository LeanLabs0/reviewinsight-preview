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

TAXONOMY = json.loads((HERE / "data" / "_taxonomy.json").read_text(encoding="utf-8"))
RATED = json.loads((HERE / "data" / "_ratings.json").read_text(encoding="utf-8"))
RATINGS: dict = RATED["ratings"]
PART_ORDER: list = RATED["parts"]
FLOORS: dict = RATED["floors"]

VENDORS: dict = DATA["vendors"]
CATS: dict = DATA["categories"]
ALL_PORTALS = [("g2", "G2"), ("capterra", "Capterra"),
               ("gartner", "Gartner Peer Insights"), ("trustpilot", "Trustpilot"),
               ("clutch", "Clutch"), ("google", "Google Business Profile")]
# which platforms count depends on what the company sells. A software vendor's
# Google listing is its office; a services company's Google listing is the
# business itself.
RATED_BY_KIND = {"software": {"g2", "capterra", "gartner", "trustpilot"},
                 "services": {"clutch", "trustpilot", "google"}}


def kind_of(v) -> str:
    return v.get("kind", "software")


def PORTALS_FOR(v):
    allowed = RATED_BY_KIND[kind_of(v)]
    return [(k, l) for k, l in ALL_PORTALS if k in allowed]


def CONTEXT_FOR(v):
    allowed = RATED_BY_KIND[kind_of(v)]
    return [(k, l) for k, l in ALL_PORTALS
            if k not in allowed and (v["portals"].get(k) or {}).get("rating") is not None]


PORTALS = [("g2", "G2"), ("capterra", "Capterra"),
           ("gartner", "Gartner Peer Insights"), ("trustpilot", "Trustpilot")]
CAPTURED = datetime.fromisoformat(DATA["generated_at"]).strftime("%d %B %Y")
QUARTER = "2026-Q3"
CSS_V = hashlib.sha256(
    (HERE / "ri.css").read_bytes()).hexdigest()[:10]

e = html.escape


# ------------------------------------------------------------ derived facts
def portals_with_data(v) -> list[tuple[str, str, dict]]:
    return [(k, lbl, v["portals"][k]) for k, lbl in PORTALS_FOR(v)
            if (v["portals"].get(k) or {}).get("rating") is not None]


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
                     (r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$", "%b %d, %Y"),
                     (r"^[A-Z][a-z]{2} \d{4}$", "%b %Y"),
                     (r"^[A-Z][a-z]+ \d{4}$", "%B %Y")):
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
    for key in v["portals"]:
        qs = list((v["portals"].get(key) or {}).get("quotes") or [])
        qs.sort(key=lambda q: qdate(q) or datetime(1970, 1, 1), reverse=True)
        out += qs[:2]
    out.sort(key=lambda q: qdate(q) or datetime(1970, 1, 1), reverse=True)
    return out


def rec(v) -> dict:
    return RATINGS.get(v["slug"], {"rated": False, "not_rated": ["missing"]})


def rating_of(v) -> int | None:
    r = rec(v)
    return r["rating"] if r.get("rated") else None


def parts_of(v) -> list:
    return rec(v).get("parts", [])


def cat_vendors(cat: str) -> list:
    """Ranked by score. Unrated vendors sort last, by review volume."""
    vs = [v for v in VENDORS.values() if v["category"] == cat]
    return sorted(vs, key=lambda v: (-(rating_of(v) or -1), -total_reviews(v)))


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
  <span class="text-xl font-bold"><a class="brand" href="{r}index.html">ReviewInsight</a></span>
  <nav>
    <a class="btn" href="{r}categories/index.html"{' aria-current="page"' if nav == 'cat' else ''}>Categories</a>
    <a class="btn" href="{r}vendors/index.html"{' aria-current="page"' if nav == 'ven' else ''}>Vendors</a>
    <a class="btn" href="{r}methodology/index.html"{' aria-current="page"' if nav == 'meth' else ''}>Methodology</a>
    <a class="btn" href="{r}quarterly/{QUARTER.lower()}/index.html"{' aria-current="page"' if nav == 'q' else ''}>Quarterly index</a>
  </nav>
</div></header>
{'' if bare else '<main class="wrap">'}
{body}
{'' if bare else '</main>'}
<footer class="foot"><div class="wrap">
  <div>
    <h4>ReviewInsight</h4>
    <p>Independent review intelligence for B2B buyers. We read the major review
    platforms together and publish one rating per company, with the arithmetic
    behind it.</p>
    <p class="tiny" style="margin-top:10px">Editorial and independent. No company can
    pay to be listed or to change its rating.</p>
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
    <ul>{''.join(f'<li>{e(lbl)}</li>' for _, lbl in ALL_PORTALS)}</ul>
  </div>
</div></footer>
</body>
</html>"""


def write(path: str, content: str) -> None:
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# -------------------------------------------------------------- components
def ratingbox(v, big: bool = False) -> str:
    r = rec(v)
    if not r.get("rated"):
        return ('<span class="ratingbox pending"><span class="v">NR</span>'
                '<span class="d">not rated</span></span>')
    cls = "ratingbox" + (" big" if big else "")
    return (f'<span class="{cls}"><span class="v">{r["rating"]}</span>'
            f'<span class="d">/100</span></span>')


def bar(value: float) -> str:
    w = max(0.0, min(100.0, float(value)))
    return f'<span class="barwrap"><span class="bar" style="width:{w:.0f}%"></span></span>'


def rating_block(v, depth: int) -> str:
    """The four parts with their arithmetic, so a reader can redo the rating."""
    r = rec(v)
    if not r.get("rated"):
        el = r.get("eligibility", {})
        return (f'<div class="nodata"><b>Not rated.</b> A company needs reviews on at '
                f'least {FLOORS["platforms"]} platforms, {FLOORS["reviews"]} reviews in '
                f'total, and {FLOORS["recent_reviews"]} written in the last year. '
                f'{e(v["name"])} has {el.get("platforms","?")} platforms and '
                f'{el.get("reviews","?")} reviews, {el.get("recent_reviews","?")} of them '
                f'from the last year.</div>')
    rows = []
    for d in parts_of(v):
        bits = "".join(
            f'<li><span>{e(pt["name"])}</span><span class="muted">{e(pt["detail"])}</span>'
            f'<span class="num">{pt["value"]}</span></li>' for pt in d.get("parts", []))
        rows.append(f"""<div class="dimrow">
  <div class="dimhd"><b>{e(d['label'])}</b><span class="num dimval">{d['value']}</span></div>
  {bar(d['value'])}
  <details><summary class="tiny">How this was worked out</summary>
    <div class="formula">{e(d['math'])}</div>
    <ul class="dimparts">{bits}</ul></details>
</div>""")
    return f"""<div class="ratingpanel">
  <div class="ratingtop">
    {ratingbox(v, big=True)}
    <div>
      <p>{e(v['name'])} rates <b class="num">{r['rating']}</b> out of 100, the average of
      the four parts below.</p>
      <details class="mathtoggle">
        <summary class="tiny">Show the arithmetic</summary>
        <div class="formula">{e(r['rating_math'])}</div>
      </details>
      <p class="tiny muted">Built from {r['reviews_total']:,} reviews, {r['reviews_last_year']:,}
      of them written in the last year. We read {r['labelled']} closely.
      <a href="{'../' * depth}methodology/index.html">How the rating works</a></p>
    </div>
  </div>
  {''.join(rows)}
</div>"""


def rating_note_at(depth: int) -> str:
    return ('<p class="small muted">A rating is the average of four parts: the review '
            'average, how consistent the platforms are, how recent the reviews are, and '
            'how often reviewers name a real outcome. '
            f'<a href="{"../" * depth}methodology/index.html">How the rating works</a></p>')


def four_ratings_cards() -> str:
    """4-column grid of rating cards for methodology page."""
    return """<div class="rgrid">
    <div class="rcard">
      <b>Review Average</b>
      <p class="small">Count every review once, not the platform averages. More reviews carry more of this rating.</p>
    </div>
    <div class="rcard">
      <b>Reliable</b>
      <p class="small">Whether the platforms agree. A wide gap or one platform brings this down. Review counts never punish.</p>
    </div>
    <div class="rcard">
      <b>Recent</b>
      <p class="small">Reviews from the last year count. Lifetime totals do not. This is how much of the base is recent.</p>
    </div>
    <div class="rcard">
      <b>Result-Specific</b>
      <p class="small">How often reviewers name an outcome a stranger could check. A number, a time saved, a tool replaced. Not vibes.</p>
    </div>
  </div>"""


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
across the {s['n']} platforms carrying it, from {e(s['lo'][0])} at
<span class="num">{s['lo'][1]}</span> to {e(s['hi'][0])} at
<span class="num">{s['hi'][1]}</span>.</p>
<div class="spreadaxis" role="img"
  aria-label="Star ratings for {e(v['name'])} plotted from 1 to 5 across {s['n']} platforms">
  <svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
    <line x1="60" y1="62" x2="{W-60}" y2="62" stroke="var(--rule)"/>
    {ticks}{''.join(marks)}{''.join(labels)}
  </svg>
</div>"""


def sources_table(v) -> str:
    rows = []
    for key, lbl in PORTALS_FOR(v):
        p = v["portals"].get(key) or {}
        if p.get("rating") is None:
            rows.append(
                f'<tr><td>{e(lbl)}</td><td colspan="3" class="muted">No listing found</td>'
                f'<td class="muted">not listed</td></tr>')
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
    extra = []
    for key, lbl in CONTEXT_FOR(v):
        p = v["portals"].get(key) or {}
        if p.get("rating") is None:
            continue
        extra.append(
            f'<tr class="ctx"><td>{e(lbl)}</td><td class="n">{p["rating"]}</td>'
            f'<td class="n">{p["count"]:,}</td><td class="tiny">{e(p["captured_at"][:10])}</td>'
            + (f'<td><a href="{e(p["url"])}" rel="nofollow noopener" target="_blank">Open&nbsp;&#8599;</a></td></tr>'
               if p.get("url") else '<td class="muted">not listed</td></tr>'))
    note = ('<p class="tiny muted">Shown for context and kept out of the rating, because '
            'a software product&rsquo;s Google listing rates its office rather than the '
            'product.</p>' if extra else '')
    return f"""<div class="tscroll"><table>
<thead><tr><th>Platform</th><th class="n">Rating</th><th class="n">Reviews</th>
<th>Checked</th><th>Source</th></tr></thead>
<tbody>{''.join(rows)}{''.join(extra)}</tbody></table></div>{note}"""


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
        for d in parts_of(v))
    return f"""<div class="rrow">
  <div class="pos">{i}</div>
  <div>{ratingbox(v)}</div>
  <div class="who">
    <h3><a href="{r}vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
    <div class="meta">{e(v['category_name'])}</div>
    <div class="facts">{dchips}
      <span><b class="num">{total_reviews(v):,}</b> reviews</span>
      <span><b class="num">{len(got)}</b> platforms</span>
      <a class="small" href="{r}vendors/{v['slug']}/alternatives/index.html">Alternatives</a>
    </div>
  </div>
  <div class="spread-cell">{spread_inline(v)}</div>
</div>"""


# ------------------------------------------------------------------- pages
def page_home() -> None:
    scored = sorted((v for v in VENDORS.values() if rating_of(v) is not None),
                    key=lambda v: -rating_of(v))
    top = scored[0]
    tr = rec(top)
    reviews_read = sum(rec(v).get("sample_size", 0) for v in VENDORS.values())
    behind = sum(p["count"] or 0 for v in VENDORS.values()
                 for _, _, p in portals_with_data(v))
    cells = sum(len(portals_with_data(v)) for v in VENDORS.values())

    # The sibling property opens with a real record. Ours opens with a real rating.
    rows = "".join(
        f'<div class="sprow"><span>{e(d["label"])}</span>'
        f'<span class="num">{d["value"]}</span></div>' for d in parts_of(top))
    plats = "".join(f'<span class="minichip">{e(lbl)} {p["rating"]}</span>'
                    for _, lbl, p in portals_with_data(top))
    specimen = f"""<div class="specimen">
  <div class="sphd"><b>{e(top['name'])}</b>
    <span class="verified">Rating {tr['rating']}</span></div>
  <div class="sprow"><span>Category</span><span>{e(top['category_name'])}</span></div>
  {rows}
  <div class="spfoot">{plats}</div>
</div>"""

    vendormap = json.dumps({v["name"].lower(): v["slug"] for v in VENDORS.values()})
    vendoropts = "".join(
        f'<option value="{e(v["name"])}">' for v in
        sorted(VENDORS.values(), key=lambda x: x["name"].lower()))

    last_year = sum(rec(v).get("reviews_last_year", 0) for v in VENDORS.values())
    stats = [(f"{len(VENDORS)}", "companies rated"),
             (f"{last_year:,}", "reviews from the last year"),
             (f"{reviews_read:,}", "reviews read one by one"),
             (f"{behind:,}", "reviews behind the averages"),
             ("None", "companies who paid to be here")]
    statbar = "".join(f'<div class="stat"><b class="num">{e(n)}</b><span>{e(l)}</span></div>'
                      for n, l in stats)

    def leaderboard(vs, limit=None):
        rows = vs[:limit] if limit else vs
        return "".join(f"""<div class="lrow">
  <span class="lpos num">{i}</span>
  {ratingbox(v)}
  <div class="lwho"><h3><a href="vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
    <div class="tiny muted">{e(v['category_name'])} &middot;
      {total_reviews(v):,} reviews across {len(portals_with_data(v))} sites</div></div>
  <div class="lchips">{''.join(
      f'<span class="chip">{e(d["label"].split("-")[0])} <b class="num">{d["value"]:.0f}</b></span>'
      for d in parts_of(v))}</div>
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

    rs = [("Review Avg", "Every review counted once, so a platform carrying more reviews carries more of the average."),
          ("Reliable", "Whether the platforms tell the same story. A wide gap, or being found on only one platform, brings this down."),
          ("Recent", "Strong for a review in the last 30 days, falling away with every day since the newest one."),
          ("Result-Specific", "How often reviewers name an outcome a stranger could check.")]
    rgrid = "".join(
        f'<div class="rcard"><b>{e(n)}</b><p class="small">{e(d)}</p></div>' for n, d in rs)

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
    <h1>One rating per company,<br>across every review platform.</h1>
    <p class="sub">Review platforms disagree about the same B2B company, sometimes by more
    than two stars. ReviewInsight reads them together and publishes a single rating that
    shows its own arithmetic.</p>
    <p class="sub">No company can pay to be listed here or to change its rating.</p>
    <form class="lookup" onsubmit="return riGo(this)">
      <input id="riq" list="ri-vendors" autocomplete="off" required
             placeholder="Look up any vendor" aria-label="Look up any vendor">
      <button type="submit" aria-label="Go">&rarr;</button>
      <datalist id="ri-vendors">{vendoropts}</datalist>
    </form>
    <p class="lookuphint tiny">{len(VENDORS)} vendors across
      {''.join(f'<a href="categories/{c}/index.html">{e(m["name"])}</a>'
               + (", " if i == 0 else "") for i, (c, m) in enumerate(CATS.items()))}.
      <a href="methodology/index.html">How the rating works</a>.</p>
  </div>
  {specimen}
</div></section>

<section class="statband"><div class="wrap">{statbar}</div></section>

<section class="band"><div class="wrap">
  <div class="eyebrow">Rankings</div>
  <div>
    <h2>Highest rated</h2>
    <p class="intro">Companies are ranked by their ReviewInsight Rating. A rating measures
    the review evidence behind a company, so it compares like with like inside a category.
    Across categories it tells you whose reviews are stronger, not whose product is better.</p>
    {ranking}
  </div>
</div></section>

<section class="band tint"><div class="wrap">
  <div class="eyebrow">Method</div>
  <div>
    <h2>What the rating measures</h2>
    <p class="intro">A rating is the average of these four. Each one is published, and
    every number on a company page can be rebuilt by hand.</p>
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

<section class="band"><div class="wrap">
  <div class="eyebrow">Coverage</div>
  <div>
    <h2>Industries</h2>
    <p class="intro">The index is being built out across the industry list the network
    already publishes. Two categories carry rated companies today. The rest are named so you can see the
    shape of the index, though nothing sits behind them yet.</p>
    <p class="small"><b>Live now.</b>
      {''.join(f'<a href="categories/{c}/index.html">{e(m["name"])}</a>'
               + (", " if i == 0 else "") for i, (c, m) in enumerate(CATS.items()))}</p>
    <div class="plainlist taxonomy">{''.join(
        f'<a href="categories/{t["slug"]}/index.html">{e(t["name"])}</a>'
        for t in TAXONOMY if t["slug"] not in CATS)}</div>
    <p class="tiny muted" style="margin-top:14px">{len(TAXONOMY)} industries. Nothing is
    published for an industry until every company in it has been read across the platforms that carry it.</p>
  </div>
</div></section>

<section class="band tint"><div class="wrap">
  <div class="eyebrow">Vendors</div>
  <div>
    <h2>Everyone we read</h2>
    <div class="plainlist">{allv}</div>
    <a class="morelink" href="vendors/index.html">Full list with ratings &rarr;</a>
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
          "One rating per B2B company, read across every review platform that "
          "carries it.", body, bare=True))


def page_industry(t: dict) -> None:
    live = "".join(
        f'<li><a href="../{c}/index.html">{e(m["name"])}</a>'
        f'<span class="num">{len(cat_vendors(c))} vendors</span></li>'
        for c, m in CATS.items())
    body = f"""<div class="crumb"><a href="../../index.html">Home</a> /
<a href="../index.html">Categories</a></div>
<h1>{e(t['name'])}</h1>
<div class="lede">No {e(t['name'])} companies have been rated yet. This page exists so the
industry has an address, and it will fill in once every vendor in it has been read.</div>

<section class="section rule-top">
  <h2>What will be here</h2>
  <p>A ranked list of {e(t['name'])} companies, each with a rating built from what
  reviewers say across every platform that carries them. Every company gets its own page
  showing the arithmetic behind the rating, what each platform says, how far those
  platforms disagree, and quotes that link back to the review they came from.</p>
  <p class="small muted">We publish an industry only once every company in it has been
  read on the same day. A partial ranking is worse than none, because it looks
  complete.</p>
</section>

<section class="section rule-top">
  <h2>Live now</h2>
  <p class="small muted">Two categories are rated today. They show exactly what this page
  will look like.</p>
  <ul class="catlist">{live}</ul>
</section>

<section class="section rule-top">
  <h2>How the rating works</h2>
  <p class="small muted">The method is published in full, including the formula, the curves
  and the cutoffs below which a vendor is shown as unrated rather than given a number.</p>
  <p><a href="../../methodology/index.html">Read the methodology &rarr;</a></p>
</section>"""
    write(f"categories/{t['slug']}/index.html",
          shell(2, f"{t['name']} | ReviewInsight",
                f"{t['name']} companies rated across every review platform.", body, "cat"))


def page_categories() -> None:
    items = "".join(
        f'<li><a href="{c}/index.html">{e(m["name"])}</a>'
        f'<span class="num">{len(cat_vendors(c))} vendors</span></li>' for c, m in CATS.items())
    rest = "".join(
        f'<li><a href="{t["slug"]}/index.html">{e(t["name"])}</a>'
        f'<span class="num muted">not yet rated</span></li>'
        for t in TAXONOMY if t["slug"] not in CATS)
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>Categories</h1>
<div class="lede">Two categories carry rated companies today. The rest of the industry
list has a page each, so you can see what is planned, but nothing is published for an
industry until every company in it has been read.</div>

<h2>Rated</h2>
<ul class="catlist">{items}</ul>

<section class="section rule-top">
  <h2>Not yet rated</h2>
  <p class="small muted">{len(TAXONOMY)} industries on the network list.</p>
  <ul class="catlist twocol">{rest}</ul>
</section>"""
    write("categories/index.html",
          shell(1, "Categories | ReviewInsight", "B2B software categories.", body, "cat"))


def page_category(cat: str, meta: dict) -> None:
    vs = cat_vendors(cat)
    rows = "".join(rank_row(i, v, 2) for i, v in enumerate(vs, 1))
    spreads = sorted(spread(v)["points"] for v in vs if spread(v))
    med = spreads[len(spreads) // 2] if spreads else 0
    body = f"""<div class="crumb"><a href="../../index.html">Home</a> / <a href="../index.html">Categories</a></div>
<h1>{e(meta['name'])}</h1>
<div class="lede">{len(vs)} companies, read across every review platform that carries
them on {CAPTURED}. The median rating gap in this category is {med} points.</div>

<p class="small muted">Ranked by ReviewInsight Rating, the average of the four parts
shown on each company page.</p>
<div class="rank">{rows}</div>

{rating_note_at(2)}

<section class="section rule-top">
  <h2>Cuts of this category</h2>
  <div class="cols">
    <div class="card"><h3><a href="../../best/{cat}/for-recent-activity/index.html">Most active review base</a></h3>
      <p class="small muted">Vendors whose newest reviews are the freshest.</p></div>
    <div class="card"><h3><a href="../../best/{cat}/for-consistent-ratings/index.html">Most consistent across platforms</a></h3>
      <p class="small muted">Companies the platforms agree on most closely.</p></div>
  </div>
</section>
"""
    write(f"categories/{cat}/index.html",
          shell(2, f"{meta['name']} | ReviewInsight",
                f"{meta['name']} vendors read across four review platforms.", body, "cat"))


def page_vendors_index() -> None:
    rows = "".join(
        f'<tr><td class="n">{rating_of(v) if rating_of(v) else "NR"}</td>'
        f'<td><a href="{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="small">{e(v["category_name"])}</td>'
        f'<td class="n">{total_reviews(v):,}</td>'
        f'<td class="n">{len(portals_with_data(v))}</td>'
        f'<td class="n">{spread(v)["points"] if spread(v) else "n/a"}</td></tr>'
        for v in sorted(VENDORS.values(), key=lambda x: -(rating_of(x) or -1)))
    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>All vendors</h1>
<div class="lede">Every vendor we currently read, with the size of its review base
and how far the platforms disagree.</div>
<div class="tscroll"><table>
<thead><tr><th class="n">Rating</th><th>Company</th><th>Category</th><th class="n">Reviews</th>
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
<div class="lede">{total_reviews(v):,} reviews across {len(got)} review
{'platform' if len(got) == 1 else 'platforms'}.
{f'Newest review {nr.strftime("%d %B %Y")}.' if nr else ''}</div>
<p class="stamp">Checked {CAPTURED}</p>

<section class="section rule-top">
  <h2>The rating</h2>
  {rating_block(v, 2)}
</section>

<section class="section rule-top">
  <h2>Platform by platform</h2>
  {sources_table(v)}
</section>

<section class="section rule-top">
  <h2>How far the platforms disagree</h2>
  {spread_detail(v)}
</section>

<section class="section rule-top">
  <h2>From the reviews</h2>
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
            for d in parts_of(v))
        return f"""<div>
  <h3>{ratingbox(v)} <a href="../../vendors/{v['slug']}/index.html">{e(v['name'])}</a></h3>
  <p class="small muted">{total_reviews(v):,} reviews across {len(portals_with_data(v))} platforms</p>
  {rows}
  {sources_table(v)}
  <div style="margin-top:16px">{spread_inline(v)}</div>
</div>"""

    ra, rb = rating_of(a), rating_of(b)
    if ra is not None and rb is not None and ra != rb:
        win, lose = (a, b) if ra > rb else (b, a)
        da = {d["key"]: d["value"] for d in parts_of(win)}
        db = {d["key"]: d["value"] for d in parts_of(lose)}
        gap = max(da, key=lambda k: da[k] - db[k])
        gl = next(d["label"] for d in parts_of(win) if d["key"] == gap)
        verdict = (f"{e(win['name'])} rates {max(ra, rb)} against {e(lose['name'])} at "
                   f"{min(ra, rb)}. The widest difference is {e(gl.lower())}, "
                   f"{da[gap]:.0f} against {db[gap]:.0f}.")
    elif ra is not None and rb is not None:
        verdict = f"Both rate {ra}. The difference is in which parts get them there."
    else:
        verdict = "One of these does not have enough recent reviews to be rated."
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
                 "A small gap means the platforms tell the same story.")
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
It is not the ReviewInsight Rating.</p>"""
    write(f"best/{cat}/for-{cut}/index.html",
          shell(3, f"{meta['name']}: {title} | ReviewInsight", blurb, body, "cat"))



# ------------------------------------------------- methodology examples
EXAMPLES = json.loads((HERE / "data" / "_examples.json").read_text(encoding="utf-8"))


def _reviews_of(slug: str) -> list:
    f = HERE / "data" / "reviews" / f"{slug}.json"
    return json.loads(f.read_text(encoding="utf-8"))["reviews"] if f.exists() else []


def part_value(v, key: str):
    for d in parts_of(v):
        if d["key"] == key:
            return d["value"]
    return None


def attrib_line(lbl: str, p: dict) -> str:
    """Kevin's target format: G2: 4.6 from 1,300 reviews, last updated [date]."""
    when = datetime.fromisoformat(p["captured_at"]).strftime("%d %b %Y")
    count = f'{p["count"]:,}' if p.get("count") else "?"
    return f'{e(lbl)}: {p["rating"]} from {count} reviews, last updated {when}'


def attribs(pairs: list) -> str:
    return ('<ul class="attribs">'
            + "".join(f"<li>{attrib_line(lbl, p)}</li>" for lbl, p in pairs)
            + "</ul>")


def extag(kind: str, text: str) -> str:
    return f'<span class="extag {kind}">{e(text)}</span>'


def gap_track(pairs: list) -> str:
    """The review-gap evidence: platform dots on a 1-to-5 track with the
    span between lowest and highest shaded, so a wide gap is a wide bar."""
    def pos(r):
        return max(0.0, min(100.0, (r - 1.0) / 4.0 * 100))
    lo = min(pairs, key=lambda x: x[1]["rating"])
    hi = max(pairs, key=lambda x: x[1]["rating"])
    lo_r, hi_r = lo[1]["rating"], hi[1]["rating"]
    dots = "".join(
        f'<span class="gpt" style="left:{pos(p["rating"]):.1f}%" title="{e(lbl)} {p["rating"]}"></span>'
        for lbl, p in pairs)
    return f"""<div class="gaptrack">
  <span class="gspan" style="left:{pos(lo_r):.1f}%; width:{max(pos(hi_r)-pos(lo_r), 1.2):.1f}%"></span>
  <span class="gaxis"></span>{dots}
  <span class="gtick" style="left:0">1</span><span class="gtick" style="left:50%">3</span>
  <span class="gtick" style="left:100%">5</span>
</div>
<div class="gapleg"><span>{e(lo[0])} <b class="num">{lo_r}</b></span>
<span>{e(hi[0])} <b class="num">{hi_r}</b></span></div>"""


def recency_track(slug: str) -> str:
    """Twelve months of review activity: one dot per review, newest marked."""
    now = datetime.fromisoformat(DATA["generated_at"]).replace(tzinfo=None)
    ds = sorted(d for d in (qdate(r) for r in _reviews_of(slug)) if d)
    year = [d for d in ds if (now - d).days <= 365]
    dots = "".join(
        f'<span class="rpt" style="left:{max(0.0, min(100.0, 100 - (now - d).days / 365 * 100)):.1f}%"></span>'
        for d in year[-80:])
    newest = f'<span class="rpt new" style="left:{max(0.0, min(100.0, 100 - (now - ds[-1]).days / 365 * 100)):.1f}%"></span>' if ds else ""
    age = (now - ds[-1]).days if ds else None
    head = (f'newest review <b class="num">{age}</b> '
            + ("day" if age == 1 else "days") + " ago") if age is not None else "no dated reviews"
    return f"""<p class="small" style="margin-bottom:6px">{head},
<b class="num">{len(year)}</b> reviews in the last year</p>
<div class="rectrack"><span class="gaxis"></span>{dots}{newest}
  <span class="gtick" style="left:0">12 months ago</span>
  <span class="gtick" style="left:100%">today</span>
</div>"""


def _norm_text(t):
    return re.sub(r"\s+", " ", (t or "").lower())


def result_quote(slug: str, want_specific: bool) -> str:
    """A real review, with the checkable outcome marked when there is one.

    The strong half must read as a strong example at a glance, so among the
    outcome-naming reviews we prefer positive ones, then the most recent.
    An angry review can be perfectly result-specific, but it belongs on the
    vendor page, not as the teaching example."""
    cands = []
    for r in _reviews_of(slug):
        lab, txt = r.get("label"), r.get("text") or ""
        if not lab or len(txt) < 60:
            continue
        if want_specific:
            ev = lab.get("results_evidence") or ""
            if lab.get("results_specific") and ev and _norm_text(ev) in _norm_text(txt):
                cands.append((txt, ev, r))
        else:
            if not lab.get("results_specific") and lab.get("resonance") in ("satisfied", "advocate"):
                cands.append((txt, None, r))
    if not cands:
        return '<div class="nodata">No matching review in the sample.</div>'
    def keyf(c):
        txt, ev, r = c
        positive = r["label"].get("resonance") in ("satisfied", "advocate")
        when = qdate(r) or datetime(1970, 1, 1)
        return (0 if positive else 1, -when.timestamp(), len(txt))
    cands.sort(key=keyf)
    # the strong half must actually show its mark, so prefer candidates whose
    # evidence can be located in the text
    if want_specific:
        cands = [c for c in cands
                 if _norm_text(c[0]).find(_norm_text(c[1])) >= 0] or cands
    txt, ev, r = cands[0]
    words = txt.split(" ")
    WINDOW = 38
    if ev:
        # trim around the evidence so the marked words survive the cut
        i = _norm_text(txt).find(_norm_text(ev))
        prefix_words = len(txt[:max(i, 0)].split())
        ev_words = len(ev.split())
        lead = max(0, (WINDOW - ev_words) // 2)
        start = max(0, min(prefix_words - lead, len(words) - WINDOW))
        end = min(len(words), start + WINDOW)
        txt = (("\u2026" if start > 0 else "")
               + " ".join(words[start:end]).rstrip(",.;:")
               + ("\u2026" if end < len(words) else ""))
    elif len(words) > WINDOW:
        txt = " ".join(words[:WINDOW]).rstrip(",.;:") + "\u2026"
    shown = e(txt)
    if ev:
        j = _norm_text(txt).find(_norm_text(ev))
        if j >= 0:
            raw = txt[j:j + len(ev)]
            shown = e(txt[:j]) + "<mark>" + e(raw) + "</mark>" + e(txt[j + len(ev):])
    cap = ("The marked words are an outcome a stranger could check."
           if ev else "Positive, and nothing in it can be checked.")
    return f"""<div class="exquote"><blockquote>&ldquo;{shown}&rdquo;</blockquote>
<p class="tiny muted">{e(r["portal"])} &middot; {(qdate(r).strftime("%d %b %Y") if qdate(r) else "undated")} &middot; {cap}</p></div>"""


def exhalf(kind: str, tag: str, name: str, href: str | None, viz: str, foot: str = "") -> str:
    title = f'<a href="{href}">{e(name)}</a>' if href else e(name)
    return f"""<div class="exhalf {kind}">
  <div class="exhalf-head">{extag(kind, tag)}<h4>{title}</h4></div>
  {viz}
  {foot}
</div>"""


def excard(title: str, what: str, good: str, bad: str) -> str:
    return f"""<div class="excard">
  <div class="exhead"><h3>{e(title)}</h3><p class="small muted">{what}</p></div>
  <div class="exgrid">{good}{bad}</div>
</div>"""


def page_methodology() -> None:
    platforms = ", ".join(lbl for k, lbl in ALL_PORTALS)
    clickup = VENDORS["clickup"]
    smart = VENDORS["smartsheet"]
    coal = VENDORS["coalition-technologies"]
    wrike = VENDORS["wrike"]
    iterable_ = VENDORS["iterable"]
    im = EXAMPLES

    # -- review gap ---------------------------------------------------
    cu_pairs = [(lbl, p) for _, lbl, p in portals_with_data(clickup)]
    im_pairs = [(p["label"], p) for p in im["portals"].values()]
    cu_gap = spread(clickup)["points"]
    im_gap = round(max(p["rating"] for _, p in im_pairs)
                   - min(p["rating"] for _, p in im_pairs), 1)
    gap_good = exhalf("strong", f"Gap {cu_gap} stars", clickup["name"],
                      "../vendors/clickup/index.html",
                      gap_track(cu_pairs), attribs(cu_pairs))
    gap_bad = exhalf("weak", f"Gap {im_gap} stars", im["name"], None,
                     gap_track(im_pairs),
                     attribs(im_pairs)
                     + '<p class="tiny muted">Not indexed. Shown because the gap is the '
                       'widest we have measured.</p>')

    # -- reliable -----------------------------------------------------
    rel_good = exhalf("strong", f"Reliable {part_value(clickup, 'reliable'):.0f}",
                      clickup["name"], "../vendors/clickup/index.html",
                      gap_track(cu_pairs),
                      f'<p class="small">{len(cu_pairs)} platforms telling the same story.</p>')
    sm_pairs = [(lbl, p) for _, lbl, p in portals_with_data(smart)]
    rel_bad = exhalf("weak", f"Reliable {part_value(smart, 'reliable'):.0f}",
                     smart["name"], "../vendors/smartsheet/index.html",
                     gap_track(sm_pairs),
                     '<p class="small">Well rated on three platforms and far off on the '
                     'fourth, so the picture does not hold together.</p>')

    # -- recent -------------------------------------------------------
    rec_good = exhalf("strong", f"Recent {part_value(clickup, 'recent'):.0f}",
                      clickup["name"], "../vendors/clickup/index.html",
                      recency_track("clickup"))
    rec_bad = exhalf("weak", f"Recent {part_value(coal, 'recent'):.0f}",
                     coal["name"], "../vendors/coalition-technologies/index.html",
                     recency_track("coalition-technologies"))

    # -- result-specific ----------------------------------------------
    res_good = exhalf("strong", f"Result-Specific {part_value(wrike, 'results'):.0f}",
                      wrike["name"], "../vendors/wrike/index.html",
                      result_quote("wrike", True))
    res_bad = exhalf("weak", f"Result-Specific {part_value(iterable_, 'results'):.0f}",
                     iterable_["name"], "../vendors/iterable/index.html",
                     result_quote("iterable", False))

    body = f"""<div class="crumb"><a href="../index.html">Home</a></div>
<h1>ReviewInsight methodology</h1>
<p class="small muted">We captured this data on {CAPTURED}.</p>
<div class="lede">Read how we calculate each rating. Every figure here can be rebuilt from the numbers on each company's vendor pages.</div>

<section class="section rule-top">
  <h2>Where we read the data</h2>
  <p>We read public vendor pages for every company. Each platform contributes its rating, review count, and review text with dates.</p>
  <p>The platforms: {platforms}. Which ones count for a company depends on what it sells, set out lower on this page.</p>
</section>

<section class="section rule-top">
  <h2>The review gap</h2>
  <p class="intro">The distance between a company's highest and lowest platform rating.
  A small gap means the platforms agree. A wide one means somebody's picture is wrong,
  and it is usually the platform the company controls best.</p>
  {excard("", "", gap_good, gap_bad)}
</section>

<section class="section rule-top">
  <h2>The four ratings</h2>
  <p>Each ReviewInsight Rating averages four parts, weighted equally. Every part is a whole number from 1 to 100.</p>
  {four_ratings_cards()}
</section>

<section class="section rule-top">
  <h2>Each part, shown on a real company</h2>
  <p class="small muted">One strong and one weak example per part, from the live index.
  Every company links to its page, where the full arithmetic is shown.</p>
  {excard("Reliable", "Do the platforms tell the same story, and is the company on more than one.", rel_good, rel_bad)}
  {excard("Recent", "Each dot is one review from the last twelve months.", rec_good, rec_bad)}
  {excard("Result-Specific", "Does the review name an outcome you could check.", res_good, res_bad)}
</section>

<section class="section rule-top">
  <h2>Overall Rating</h2>
  <p>The ReviewInsight Rating averages four parts, weighted equally.</p>
  <div class="formula">ReviewInsight Rating = (Review Average + Reliable + Recent + Result-Specific) / 4</div>
  <p class="small muted" style="margin-top:12px">Every part is a whole number from 1 to 100. Displayed ratings carry no decimals.</p>
</section>

<section class="section rule-top">
  <h2>Which platforms count</h2>
  <div class="tscroll"><table>
  <thead><tr><th>Kind of company</th><th>Platforms that count</th><th>Shown but not counted</th></tr></thead>
  <tbody>
    <tr><td>Software products</td><td>G2, Capterra, Gartner Peer Insights, Trustpilot</td>
      <td>Google Business Profile</td></tr>
    <tr><td>Service companies</td><td>Clutch, Trustpilot, Google Business Profile</td>
      <td>&nbsp;</td></tr>
  </tbody></table></div>
  <p class="small muted">A software company's Google listing is its office, so it is shown
  for context and left out of the rating. For an agency the Google listing is the business
  itself, so it counts. Clutch lists service providers and carries no software products.</p>
</section>

<section class="section rule-top">
  <h2>Not Rated</h2>
  <p>A company needs at least two platforms, fifteen reviews total, and five reviews in the last year.</p>
  <p class="small muted">WebFX carries 468 reviews, and only three are from the last year, so it is shown as Not Rated rather than given a number.</p>
</section>

<section class="section rule-top">
  <h2>What we refuse</h2>
  <div class="rgrid">
    <div class="rcard">
      <h3>Paid placement</h3>
      <p class="small">A company cannot buy a rank or a better rating.</p>
    </div>
    <div class="rcard">
      <h3>Invented numbers</h3>
      <p class="small">If we cannot read a figure we show that we could not. We never fill a gap with an estimate.</p>
    </div>
    <div class="rcard">
      <h3>No quotes over 40 words</h3>
      <p class="small">Quotes are trimmed and linked back to the review they came from, with the date.</p>
    </div>
    <div class="rcard">
      <h3>Hidden math</h3>
      <p class="small">Every figure is rebuildable from the numbers on the vendor pages.</p>
    </div>
  </div>
</section>

<section class="section rule-top">
  <h2>Known gaps</h2>
  <p class="small">Gartner Peer Insights puts review text behind a login. We use its rating and date, and do not touch the gated text.</p>
  <p class="small muted">Two vendors in this preview have no listing on one platform. We show the gap rather than hide it.</p>
</section>

<section class="section rule-top">
  <h2>Check a company rating</h2>
  <p class="small muted">See how any indexed company rates across the four parts and read the reviews behind each one.</p>
  <p><a href="../vendors/index.html">Browse companies</a></p>
</section>"""
    write("methodology/index.html",
          shell(1, "Methodology | ReviewInsight", "How ReviewInsight reads and publishes review data.", body, "meth"))

def sources_note() -> str:
    rows = "".join(
        f"<tr><td>{e(lbl)}</td><td class='n'>{sum(1 for v in VENDORS.values() if (v['portals'].get(k) or {}).get('rating') is not None)}"
        f" of {len(VENDORS)}</td><td class='small'>"
        f"{'Rating, review count, review text with dates' if k != 'gartner' else 'Rating, review and rating counts, review headlines with dates. Bodies are login-gated.'}"
        f"</td></tr>" for k, lbl in ALL_PORTALS)
    return f"""<div class="tscroll"><table>
<thead><tr><th>Platform</th><th class="n">Companies covered</th><th>What we take</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""


def page_quarterly() -> None:
    rows = "".join(
        f'<tr><td><a href="../../vendors/{v["slug"]}/index.html">{e(v["name"])}</a></td>'
        f'<td class="small">{e(v["category_name"])}</td>'
        + "".join(f'<td class="n">{(v["portals"].get(k) or {}).get("rating") or "n/a"}</td>'
                  for k, _ in ALL_PORTALS)
        + f'<td class="n">{total_reviews(v):,}</td></tr>'
        for v in sorted(VENDORS.values(), key=lambda x: x["name"].lower()))
    heads = "".join(f'<th class="n">{e(l)}</th>' for _, l in ALL_PORTALS)
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

    for t in TAXONOMY:
        if t["slug"] in CATS:      # now a real category, so it gets the real page
            continue
        page_industry(t)

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
