"""Full v2: favourite insights, side-by-side comparison, attribution dates,
decimals off displayed part values."""
from pathlib import Path

p = Path("build.py")
s = p.read_text(encoding="utf-8")
done = []


def rep(old, new, label, count=1):
    global s
    n = s.count(old)
    assert n == count, f"{label}: found {n}, expected {count}"
    s = s.replace(old, new)
    done.append(label)


# ---------- 1. helpers: shared mark, favourites, comparison ----------
anchor = "def exhalf("
i = s.index(anchor)
helpers = '''def _quote_with_mark(txt: str, ev: str | None, window: int = 38) -> str:
    """Trim a review to about `window` words, keeping and marking the evidence."""
    words = txt.split(" ")
    if ev:
        k = _norm_text(txt).find(_norm_text(ev))
        prefix_words = len(txt[:max(k, 0)].split())
        lead = max(0, (window - len(ev.split())) // 2)
        start = max(0, min(prefix_words - lead, len(words) - window))
        end = min(len(words), start + window)
        txt = (("\\u2026" if start > 0 else "")
               + " ".join(words[start:end]).rstrip(",.;:")
               + ("\\u2026" if end < len(words) else ""))
    elif len(words) > window:
        txt = " ".join(words[:window]).rstrip(",.;:") + "\\u2026"
    shown = e(txt)
    if ev:
        j = _norm_text(txt).find(_norm_text(ev))
        if j >= 0:
            raw = txt[j:j + len(ev)]
            shown = e(txt[:j]) + "<mark>" + e(raw) + "</mark>" + e(txt[j + len(ev):])
    return shown


def favorite_quotes(v) -> str:
    """Curated, quote based, fully attributable. Favourites are the reviews
    that name a checkable outcome, positive ones first, plus one specific
    critical voice so the section reads the evidence rather than cheerleads."""
    pos, neg = [], []
    for r in _reviews_of(v["slug"]):
        lab, txt = r.get("label"), r.get("text") or ""
        if not lab or len(txt) < 60 or not lab.get("results_specific"):
            continue
        ev = lab.get("results_evidence") or ""
        if not ev or _norm_text(ev) not in _norm_text(txt):
            continue
        entry = (qdate(r) or datetime(1970, 1, 1), txt, ev, r)
        (pos if lab.get("resonance") in ("satisfied", "advocate") else neg).append(entry)
    pos.sort(key=lambda x: x[0], reverse=True)
    neg.sort(key=lambda x: x[0], reverse=True)
    picks = pos[:3] + neg[:1]
    if not picks:
        fallback = "".join(evidence(q) for q in all_quotes(v)[:4])
        return fallback or '<div class="nodata">No quotes captured yet.</div>'
    out = []
    for when, txt, ev, r in picks:
        bits = [b for b in [r.get("role"), r.get("company_size")] if b]
        who = " &middot; ".join(e(b) for b in bits)
        rating = (f'<span class="num">{r["rating"]}</span> &middot; '
                  if r.get("rating") is not None else "")
        stamp = when.strftime("%d %b %Y") if when.year > 1970 else "undated"
        out.append(f"""<div class="ev"><blockquote>&ldquo;{_quote_with_mark(txt, ev)}&rdquo;</blockquote>
  <div class="prov">{rating}<span>{e(r["portal"])}</span><span class="sep">&middot;</span>
    <span>{stamp}</span>
    {f'<span class="sep">&middot;</span><span>{who}</span>' if who else ''}
    <span class="sep">&middot;</span>
    <a href="{e(r["source_url"])}" rel="nofollow noopener" target="_blank">Read on {e(r["portal"])}&nbsp;&#8599;</a>
  </div></div>""")
    out.append('<p class="tiny muted">The marked words are the outcome each review '
               'names. Chosen for how checkable they are, not for how kind.</p>')
    return "".join(out)


def comparison_block(v, depth: int) -> str:
    """The company on the left, its closest rated competitors beside it,
    the numbers side by side."""
    r = "../" * depth
    mine = rating_of(v)
    peers = [x for x in cat_vendors(v["category"])
             if x["slug"] != v["slug"] and rating_of(x) is not None]
    peers.sort(key=lambda x: (abs((rating_of(x) or 0) - mine) if mine is not None else 0,
                              -(rating_of(x) or 0)))
    peers = peers[:4]
    if not peers:
        return '<div class="nodata">No rated competitors in this category yet.</div>'
    cols = [v] + peers

    def head(x):
        if x["slug"] == v["slug"]:
            return f'<th class="tcol">{e(x["name"])}</th>'
        return (f'<th><a href="{r}vendors/{x["slug"]}/index.html">'
                f'{e(x["name"])}</a></th>')

    def cell(x, val, num=True):
        cls = ("tcol n" if num else "tcol") if x["slug"] == v["slug"] else ("n" if num else "")
        return f'<td class="{cls}">{val}</td>'

    rows = ["<tr><th>ReviewInsight Rating</th>" + "".join(
        cell(x, f'<b class="num big">{rating_of(x)}</b>'
             if rating_of(x) is not None else "NR") for x in cols) + "</tr>"]
    for key, lbl in (("review_avg", "Review Average"), ("reliable", "Reliable"),
                     ("recent", "Recent"), ("results", "Result-Specific")):
        rows.append(f"<tr><th>{lbl}</th>" + "".join(
            cell(x, f"{part_value(x, key):.0f}" if part_value(x, key) is not None else "n/a")
            for x in cols) + "</tr>")
    rows.append("<tr><th>Reviews in the last year</th>" + "".join(
        cell(x, f'{rec(x).get("reviews_last_year", 0):,}') for x in cols) + "</tr>")
    rows.append("<tr><th>&nbsp;</th>" + "".join(
        cell(x, "&nbsp;" if x["slug"] == v["slug"] else
             f'<a href="{r}compare/{pair_slug(v, x)}/index.html">Head to head</a>',
             num=False) for x in cols) + "</tr>")
    return ('<div class="tscroll"><table class="cmptab">'
            '<thead><tr><th>&nbsp;</th>' + "".join(head(x) for x in cols)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


'''
s = s[:i] + helpers + s[i:]
done.append("helpers inserted")

# ---------- 2. vendor page ----------
old_sections = (
    '<section class="section rule-top">\n'
    '  <h2>From the reviews</h2>\n'
    '  {ev}\n'
    '</section>\n'
    '\n'
    '<section class="section rule-top">\n'
    "  <h2>Compare {e(v['name'])}</h2>\n"
    '  <div class="cols">{cmp_cards}\n'
    '    <div class="card"><h3><a href="alternatives/index.html">All alternatives</a></h3></div>\n'
    '  </div>\n'
    '</section>"""'
)
new_sections = (
    '<section class="section rule-top">\n'
    '  <h2>Our favorite insights from the reviews</h2>\n'
    '  {favorite_quotes(v)}\n'
    '</section>\n'
    '\n'
    '<section class="section rule-top">\n'
    "  <h2>How {e(v['name'])} compares</h2>\n"
    '  <p class="small muted">The closest rated competitors in {e(v[\'category_name\'])},\n'
    '  numbers side by side.</p>\n'
    '  {comparison_block(v, 2)}\n'
    '  <p class="small" style="margin-top:12px"><a href="alternatives/index.html">All alternatives</a></p>\n'
    '</section>"""'
)
rep(old_sections, new_sections, "vendor sections")

old_prelude = (
    '    qs = all_quotes(v)[:6]\n'
    '    got = portals_with_data(v)\n'
    '    nr = newest_review(v)\n'
    '    peers = [p for p in cat_vendors(v["category"]) if p["slug"] != v["slug"]][:2]\n'
    '    cmp_cards = "".join(\n'
    '        f\'<div class="card"><h3><a href="../../compare/{pair_slug(v, p)}/index.html">\'\n'
    '        f\'{e(v["name"])} vs {e(p["name"])}</a></h3></div>\' for p in peers)\n'
    '    ev = "".join(evidence(q) for q in qs) or \'<div class="nodata">No quotes captured yet.</div>\'\n'
)
new_prelude = (
    '    got = portals_with_data(v)\n'
    '    nr = newest_review(v)\n'
)
rep(old_prelude, new_prelude, "vendor prelude")

rep('<p class="stamp">Checked {CAPTURED}</p>',
    '<p class="stamp">Last updated {CAPTURED}</p>', "vendor stamp")

# ---------- 3. sources table dates ----------
rep("<th>Checked</th><th>Source</th></tr></thead>",
    "<th>Last updated</th><th>Source</th></tr></thead>", "sources header")
rep("f'<td class=\"tiny\">{e(p[\"captured_at\"][:10])}</td>'\n"
    "            f'<td><a href=\"{e(p[\"url\"])}\"",
    "f'<td class=\"tiny\">{datetime.fromisoformat(p[\"captured_at\"]).strftime(\"%d %b %Y\")}</td>'\n"
    "            f'<td><a href=\"{e(p[\"url\"])}\"", "sources date fmt")
rep("f'<td class=\"n\">{p[\"count\"]:,}</td><td class=\"tiny\">{e(p[\"captured_at\"][:10])}</td>'",
    "f'<td class=\"n\">{p[\"count\"]:,}</td><td class=\"tiny\">{datetime.fromisoformat(p[\"captured_at\"]).strftime(\"%d %b %Y\")}</td>'",
    "ctx date fmt")

# ---------- 4. decimals off displayed part values ----------
rep("  <div class=\"dimhd\"><b>{e(d['label'])}</b><span class=\"num dimval\">{d['value']}</span></div>",
    "  <div class=\"dimhd\"><b>{e(d['label'])}</b><span class=\"num dimval\">{d['value']:.0f}</span></div>",
    "rating_block int")
rep("f'<span class=\"num dimval\">{d[\"value\"]}</span></div>{bar(d[\"value\"])}</div>'",
    "f'<span class=\"num dimval\">{d[\"value\"]:.0f}</span></div>{bar(d[\"value\"])}</div>'",
    "compare col int")
rep("        f'<div class=\"sprow\"><span>{e(d[\"label\"])}</span>'\n"
    "        f'<span class=\"num\">{d[\"value\"]}</span></div>' for d in parts_of(top))",
    "        f'<div class=\"sprow\"><span>{e(d[\"label\"])}</span>'\n"
    "        f'<span class=\"num\">{d[\"value\"]:.0f}</span></div>' for d in parts_of(top))",
    "specimen int")

p.write_text(s, encoding="utf-8")
for d in done:
    print(" ", d)
