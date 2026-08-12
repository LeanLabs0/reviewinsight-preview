"""Label every review for Results-specific and Resonance.

Two of the four Rs need the review text read. A cheap model does the reading;
Python does every calculation. The model only ever emits a label plus the exact
words it based that label on, and we reject any label whose quoted evidence is
not literally present in the review. That keeps a hallucinating classifier from
silently inventing a score.

Results are cached by hash of the review text, so the same review always gets
the same label and a re-run costs nothing.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ENV = Path(r"C:\Users\Sistemas\AIS-OS\projects\lean-labs\factor8_app\.env")
KEY = next(l.split("=", 1)[1].strip()
           for l in ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
           if l.startswith("FACTOR8_OPENROUTER_API_KEY="))
MODEL = "anthropic/claude-haiku-4.5"
PROMPT_VERSION = "clf-v1"
CACHE = HERE / "data" / "labels"
BATCH = 8
SEM = asyncio.Semaphore(6)

SYSTEM = """You label B2B software reviews. You never score anything and you never summarise.

For each review return two labels.

results_specific: true only if the review names a concrete outcome a stranger could check.
A number with a unit, a time saved, a before and after state, a named replaced tool, a
percentage change. "cut onboarding from two weeks to three days", "40% more leads",
"replaced three tools", "saves 12 hours a week" are all true. "saves time", "great ROI",
"very efficient", "improved our workflow", "increased productivity" are all false, because
nothing in them can be checked.

resonance: how the reviewer feels, on four levels.
  detractor - would not recommend, or clearly negative overall
  lukewarm  - it works, but hedged and flat. "it's fine", "does the job", "adequate"
  satisfied - clearly positive, no advocacy language
  advocate  - recommends it, or uses strong language, or would choose it again

For each label quote the exact words from the review that decided it, copied character for
character from the review text. Never paraphrase the evidence. If nothing in the review
supports results_specific, set results_evidence to null.

Return only a JSON array, one object per review, in the order given."""

SCHEMA_HINT = """Return exactly this shape:
[{"id":"<id>","results_specific":true|false,"results_evidence":"<exact quote>"|null,
  "resonance":"detractor|lukewarm|satisfied|advocate","resonance_evidence":"<exact quote>"}]"""


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def key_of(text: str) -> str:
    return hashlib.sha256((PROMPT_VERSION + "\n" + norm(text)).encode()).hexdigest()


def cached(text: str):
    f = CACHE / key_of(text)[:2] / f"{key_of(text)}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def put(text: str, label: dict) -> None:
    k = key_of(text)
    f = CACHE / k[:2] / f"{k}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(label), encoding="utf-8")


async def call(client, batch: list[tuple[str, str]]) -> dict[str, dict]:
    body = "\n\n".join(f"### {rid}\n{txt[:1500]}" for rid, txt in batch)
    async with SEM:
        for attempt in range(3):
            try:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {KEY}",
                             "Content-Type": "application/json"},
                    json={"model": MODEL, "temperature": 0, "max_tokens": 2000,
                          "messages": [{"role": "system", "content": SYSTEM},
                                       {"role": "user", "content": SCHEMA_HINT + "\n\n" + body}]},
                    timeout=180.0)
                if r.status_code != 200:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                txt = r.json()["choices"][0]["message"]["content"]
                m = re.search(r"\[.*\]", txt, re.S)
                if not m:
                    continue
                items = json.loads(m.group(0))
                return {str(it.get("id")): it for it in items if isinstance(it, dict)}
            except Exception:
                await asyncio.sleep(3 * (attempt + 1))
    return {}


def valid(label: dict, text: str) -> bool:
    """Every quoted evidence string must really appear in the review."""
    hay = norm(text)
    if label.get("resonance") not in ("detractor", "lukewarm", "satisfied", "advocate"):
        return False
    re_ev = norm(label.get("resonance_evidence") or "")
    if not re_ev or re_ev not in hay:
        return False
    if label.get("results_specific"):
        rs_ev = norm(label.get("results_evidence") or "")
        if not rs_ev or rs_ev not in hay:
            return False
    return True


async def main() -> None:
    files = sorted((HERE / "data" / "reviews").glob("*.json"))
    todo: list[tuple[str, str]] = []
    index: dict[str, tuple[Path, int]] = {}
    store: dict[Path, dict] = {}

    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        store[f] = d
        for i, rv in enumerate(d["reviews"]):
            txt = rv.get("text")
            if not txt or len(txt) < 40:
                continue
            hit = cached(txt)
            if hit:
                rv["label"] = hit
                continue
            rid = f"{f.stem}:{i}"
            index[rid] = (f, i)
            todo.append((rid, txt))

    print(f"{len(todo)} reviews to label, {sum(1 for d in store.values() for r in d['reviews'] if r.get('label'))} already cached")

    ok = rejected = 0
    if todo:
        batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(*[call(client, b) for b in batches])
        for b, res in zip(batches, results):
            for rid, txt in b:
                lab = res.get(rid)
                if not lab or not valid(lab, txt):
                    rejected += 1
                    continue
                clean = {"results_specific": bool(lab["results_specific"]),
                         "resonance": lab["resonance"],
                         "results_evidence": lab.get("results_evidence"),
                         "resonance_evidence": lab.get("resonance_evidence")}
                put(txt, clean)
                f, i = index[rid]
                store[f]["reviews"][i]["label"] = clean
                ok += 1

    for f, d in store.items():
        f.write_text(json.dumps(d, indent=2), encoding="utf-8")

    lab = sum(1 for d in store.values() for r in d["reviews"] if r.get("label"))
    tot = sum(1 for d in store.values() for r in d["reviews"] if (r.get("text") or ""))
    print(f"newly labelled {ok}, rejected {rejected}")
    print(f"labelled {lab} of {tot} reviews with text ({lab / max(tot,1):.0%})")


if __name__ == "__main__":
    asyncio.run(main())
