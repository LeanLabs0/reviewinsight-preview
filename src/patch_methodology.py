"""Rebuild the methodology examples in the template, not the built HTML.

The previous pass hand-edited site/methodology/index.html, so its examples
vanished on every rebuild and never matched the vendor-page component
language. This puts the whole section in build.py:

  - one example-card component used the same way for every concept
  - good and bad halves labelled explicitly
  - the review gap gets its own section, Iron Mountain as the bad example
  - evidence per concept: gap track, recency track, marked quotes
  - platform figures in Kevin's attribution format
"""
from pathlib import Path

p = Path("build.py")
s = p.read_text(encoding="utf-8")

HELPERS = '''
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
    return re.sub(r"\\s+", " ", (t or "").lower())


def result_quote(slug: str, want_specific: bool) -> str:
    """A real review, with the checkable outcome marked when there is one."""
    best = None
    for r in _reviews_of(slug):
        lab, txt = r.get("label"), r.get("text") or ""
        if not lab or len(txt) < 60:
            continue
        if want_specific:
            ev = lab.get("results_evidence") or ""
            if lab.get("results_specific") and ev and _norm_text(ev) in _norm_text(txt):
                if best is None or len(txt) < len(best[0]):
                    best = (txt, ev, r)
        else:
            if not lab.get("results_specific") and lab.get("resonance") in ("satisfied", "advocate"):
                if best is None or len(txt) < len(best[0]):
                    best = (txt, None, r)
    if not best:
        return '<div class="nodata">No matching review in the sample.</div>'
    txt, ev, r = best
    words = txt.split(" ")
    if len(words) > 38:
        txt = " ".join(words[:38]).rstrip(",.;:") + "\\u2026"
    shown = e(txt)
    if ev:
        i = _norm_text(txt).find(_norm_text(ev))
        if i >= 0:
            raw = txt[i:i + len(ev)]
            shown = e(txt[:i]) + "<mark>" + e(raw) + "</mark>" + e(txt[i + len(ev):])
    cap = ("The marked words are an outcome a stranger could check."
           if ev else "Positive, and nothing in it can be checked.")
    return f"""<div class="exquote"><blockquote>&ldquo;{shown}&rdquo;</blockquote>
<p class="tiny muted">{e(r["portal"])} &middot; {e(r.get("date") or "undated")} &middot; {cap}</p></div>"""


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

'''

# ---------------------------------------------------------------- insert
anchor = "def page_methodology() -> None:"
i = s.index(anchor)
s = s[:i] + HELPERS + "\n" + s[i:]

# ------------------------------------------------------------- new page
start = s.index(anchor)
end = s.index("\ndef ", start + 10)
NEW = '''def page_methodology() -> None:
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

'''
s = s[:start] + NEW + s[end + 1:]
p.write_text(s, encoding="utf-8")
print("page_methodology replaced, helpers inserted")
