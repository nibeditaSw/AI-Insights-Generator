"""AI Layer.

Design goal: every number the user sees is traceable to the uploaded report.

  1. build_package()   – aggregates only (no customer rows) → what the AI may see.
  2. exact_answer()    – deterministic engine: computes answers with pandas-derived
                         aggregates. No AI involved, so it cannot hallucinate.
  3. LLM calls         – robust OpenAI-compatible client (multi-key failover,
                         real error messages, Cloudflare-safe headers).
  4. verify_numbers()  – every figure in an AI reply must exist in the data.
                         Anything else is rejected and the exact answer is used.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from processing import (fmt_k, fmt_exact, group_indian, pct_change)

NM = {"ctr": "CTR", "cvr": "Conversion rate", "or": "Open rate",
      "unr": "Unsubscribe rate", "rev": "Revenue", "dr": "Delivery rate"}

NOT_SUFFICIENT = "The available data is not sufficient to answer this."

# ─────────────────────────────────────────────────────────────────────────────
# 1. ANALYSIS PACKAGE (aggregates only)
# ─────────────────────────────────────────────────────────────────────────────
_PKG_ROWS = 25          # keeps the prompt small enough for free-tier token limits


def _r(v, d=1):
    return round(v, d) if v is not None else None


def _row(x: dict) -> dict:
    out = {"name": x["k"], "sent": int(x["sent"]), "clicks": int(x["clicks"]),
           "conversions": int(x["conv"]), "revenue": int(round(x["rev"]))}
    for src, dst in (("ctr", "ctr_pct"), ("cvr", "conversion_pct"),
                     ("or", "open_rate_pct"), ("unr", "unsubscribe_rate_pct")):
        if x.get(src) is not None:
            out[dst] = round(x[src], 2)
    return out


def build_package(res: dict, pii_count: int) -> dict:
    tot, camps, per = res["tot"], res["camps"], res["per"]
    by_rev = sorted(camps, key=lambda x: x.get("rev", 0), reverse=True)
    pkg = {
        "report_type": "Campaign Performance",
        "period": res["period"],
        "campaigns_analyzed": len(camps),
        "definitions": {
            "ctr_pct": "clicks / delivered (or sent) x 100",
            "conversion_pct": "conversions / clicks x 100",
            "open_rate_pct": "opens / delivered (or sent) x 100",
            "sent": "messages sent (not unique people)",
        },
        "overall": {
            "messages_sent": int(tot["sent"]),
            "clicks": int(tot["clicks"]),
            "conversions": int(tot["conv"]),
            "revenue": int(round(tot.get("rev", 0))),
            **{dst: round(tot[src], 2) for src, dst in
               (("ctr", "ctr_pct"), ("cvr", "conversion_pct"), ("or", "open_rate_pct"),
                ("unr", "unsubscribe_rate_pct")) if tot.get(src) is not None},
        },
        "campaigns": [_row(x) for x in by_rev[:_PKG_ROWS]],
        "channels": [_row(x) for x in res["chans"][:_PKG_ROWS]],
        "segments": [_row(x) for x in res["segs"][:_PKG_ROWS]],
        "first_vs_second_half": (
            {"first_half": {"ctr_pct": _r(per["a"].get("ctr"), 2), "conversion_pct": _r(per["a"].get("cvr"), 2),
                            "revenue": int(round(per["a"].get("rev", 0)))},
             "second_half": {"ctr_pct": _r(per["b"].get("ctr"), 2), "conversion_pct": _r(per["b"].get("cvr"), 2),
                             "revenue": int(round(per["b"].get("rev", 0)))},
             "change_pct": {
                 "ctr": _r(pct_change(per["b"].get("ctr"), per["a"].get("ctr"))),
                 "conversion": _r(pct_change(per["b"].get("cvr"), per["a"].get("cvr"))),
                 "revenue": _r(pct_change(per["b"].get("rev"), per["a"].get("rev")))}}
            if per else None),
        "anomalies": [f"{a['camp']} – {NM[a['k']]} {a['v']:.2f}% vs avg {a['m']:.2f}%"
                      for a in res["an"][:5]],
        "data_notes": res.get("warnings", []),
        "pii_columns_removed": pii_count,
        "note": "Aggregated data only. No customer-level rows.",
    }
    if len(camps) > _PKG_ROWS:
        pkg["note"] += f" Campaign list truncated to top {_PKG_ROWS} by revenue."
    return pkg


# ─────────────────────────────────────────────────────────────────────────────
# 2. BUILT-IN INSIGHTS (deterministic)
# ─────────────────────────────────────────────────────────────────────────────
WHY = {
    "ctr": ["Creative, subject line, timing or audience mix may have shifted.",
            "Creative fatigue, list quality or send-time changes may be involved."],
    "cvr": ["Post-click experience, offer or audience intent may have improved.",
            "Landing page, offer or audience intent may have changed after the click."],
    "rev": ["Likely follows volume and conversion changes.",
            "Likely follows volume and conversion changes; check which campaigns contributed."],
}
ACT = {
    "ctr": ["Identify the top-CTR campaigns and reuse their creative/timing in the next test.",
            "Run an A/B test on subject line/creative and review send timing."],
    "cvr": ["Note what changed in offer or audience and keep it.",
            "Investigate the post-click funnel and compare offers across campaigns."],
    "rev": ["Double down on the campaigns driving the lift.",
            "Break revenue down by campaign to find where it dropped."],
}


def generate_insights(res: dict) -> list[dict]:
    I, camps, tot, per, Z = [], res["camps"], res["tot"], res["per"], res["Z"]
    cf = "High" if len(camps) >= 8 else "Medium"
    if per:
        for k, cg in [("ctr", "engagement"), ("cvr", "conversion"), ("rev", "revenue")]:
            if per["a"].get(k) is None:
                continue
            d = pct_change(per["b"].get(k), per["a"].get(k))
            if d is None or abs(d) < 5:
                continue
            up, i = d > 0, 0 if d > 0 else 1
            I.append({
                "cg": cg, "t": "good" if up else "bad",
                "title": f"{NM[k]} {'up' if up else 'down'} {abs(d):.0f}% in the later half",
                "data": f"{NM[k]}: {fmt_k(k, per['a'][k])} → {fmt_k(k, per['b'][k])} (first vs second half).",
                "why": WHY[k][i],
                "cannot": "This report has no creative, offer or audience-history data to confirm the cause.",
                "conf": "Medium", "action": ACT[k][i],
            })
    for a in res["an"][:4]:
        hi = a["z"] > 0
        I.append({
            "cg": "anomaly", "t": "bad" if (a["k"] == "unr" or not hi) else "warn",
            "title": f"{a['camp']}: {NM[a['k']]} unusually {'high' if hi else 'low'}",
            "data": f"{fmt_k(a['k'], a['v'])} vs campaign average {fmt_k(a['k'], a['m'])} ({abs(a['z']):.1f} std away).",
            "why": "Statistical outlier among campaigns; audience, offer or landing experience are candidate drivers.",
            "cannot": "The exact reason cannot be determined from this report alone.",
            "conf": cf,
            "action": f"Review {a['camp']}'s audience, offer and post-click journey.",
        })
    for x in res["hl"][:2]:
        I.append({
            "cg": "conversion", "t": "warn",
            "title": f"{x['k']}: strong clicks, weak conversion",
            "data": f"CTR {fmt_k('ctr', x['ctr'])} (above avg) but conversion {fmt_k('cvr', x['cvr'])} (below avg {fmt_k('cvr', Z['cvr']['m'])}).",
            "why": "Clicks are not turning into outcomes — possible landing-page, offer or intent mismatch.",
            "cannot": "Post-click behaviour is not in this report.",
            "conf": cf,
            "action": "Check landing page, offer and post-click funnel vs higher-converting campaigns.",
        })
    if res["m"].get("rev") and tot.get("rev"):
        r = max(camps, key=lambda x: x.get("rev", 0))
        I.append({
            "cg": "revenue", "t": "good",
            "title": f"{r['k']} led revenue",
            "data": f"{fmt_k('rev', r['rev'])} — {r['rev']/tot['rev']*100:.0f}% of total {fmt_k('rev', tot['rev'])}.",
            "why": "Share reflects both audience volume and conversion.",
            "cannot": "Whether it can scale is not answerable from this data.",
            "conf": "High",
            "action": "Test its strongest elements (offer, timing, segment) in upcoming campaigns.",
        })
    valid_ch = [x for x in res["chans"] if x.get("ctr") is not None and x["ctr"] <= 100]
    if len(valid_ch) > 1:
        b = max(valid_ch, key=lambda x: x["ctr"])
        others = ", ".join(f"{x['k']} {fmt_k('ctr', x['ctr'])}" for x in valid_ch if x is not b)
        I.append({
            "cg": "engagement", "t": "good",
            "title": f"{b['k']} had the highest CTR by channel",
            "data": f"{fmt_k('ctr', b['ctr'])} on {b['k']}; others: {others}.",
            "why": "Channel differences may reflect different audiences or content.",
            "cannot": "Channel effect cannot be separated from audience and creative differences.",
            "conf": "Medium",
            "action": "Run a like-for-like channel test with the same audience and offer.",
        })
    rank = {"bad": 0, "warn": 1, "good": 2}
    I.sort(key=lambda x: rank[x["t"]])
    return I


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXACT Q&A ENGINE (no AI → cannot hallucinate)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Exact:
    text: str
    must_include: list = field(default_factory=list)   # entity names an AI comment must not contradict


LABEL = {"rev": "revenue", "ctr": "CTR", "cvr": "conversion rate", "or": "open rate",
         "unr": "unsubscribe rate", "dr": "delivery rate", "sent": "messages sent",
         "clicks": "clicks", "conv": "conversions", "opens": "opens",
         "uns": "unsubscribes", "del": "delivered messages"}
# which detected column each metric needs
NEEDS = {"rev": "rev", "ctr": "click", "cvr": "conv", "or": "open", "unr": "uns", "dr": "del",
         "sent": "sent", "clicks": "click", "conv": "conv", "opens": "open", "uns": "uns", "del": "del"}
DISP = {"ctr": "CTR", "cvr": "Conversion rate", "or": "Open rate", "unr": "Unsubscribe rate",
        "dr": "Delivery rate", "rev": "Revenue", "sent": "Messages sent", "clicks": "Clicks",
        "conv": "Conversions", "opens": "Opens", "uns": "Unsubscribes", "del": "Delivered"}
ADDITIVE = {"rev", "sent", "clicks", "conv", "opens", "uns", "del"}

_HIGH = r"highest|top|best|most|max(?:imum)?|biggest|largest|greatest|strongest|leading|higher|higher|better|more"
_LOW = r"lowest|worst|least|min(?:imum)?|fewest|smallest|weakest|poor(?:est)?|lower|weak|less|fewer"


def _has(m: dict, k: str) -> bool:
    if not m.get(NEEDS[k]):
        return False
    if k in ("ctr", "or", "unr"):
        return bool(m.get("sent") or m.get("del"))
    if k == "dr":
        return bool(m.get("sent") and m.get("del"))
    if k == "cvr":
        return bool(m.get("click") or m.get("sent") or m.get("del"))
    return True


def _metric_keys(l: str, m: dict) -> list[str]:
    rate = bool(re.search(r"\brate\b|%|ratio|\bctr\b|\bcvr\b|click[- ]?through|percent", l))
    cnt = bool(re.search(r"how many|number of|count|total|volume", l))
    ks: list[str] = []
    if re.search(r"revenue|sales|gmv|order value|earn", l):
        ks.append("rev")
    if re.search(r"\bctr\b|click[- ]?through", l):
        ks.append("ctr")
    elif re.search(r"\bclicks?\b|clicked", l):
        ks.append("ctr" if rate else "clicks")
    if re.search(r"convers|convert|\bcvr\b|purchas", l):
        if rate or re.search(r"convert(s|ing)?\b|\bcvr\b", l):
            ks.append("cvr")
        elif cnt:
            ks.append("conv")
        else:
            ks += ["cvr", "conv"]
    if re.search(r"\bopens?\b|opened|open[- ]rate", l):
        ks += ["or"] if rate else (["opens"] if cnt else ["or", "opens"])
    if re.search(r"unsub", l):
        ks += ["unr"] if rate else (["uns"] if cnt else ["unr", "uns"])
    if re.search(r"deliver", l):
        ks += ["dr"] if rate else (["del"] if cnt else ["dr", "del"])
    if re.search(r"\bsent\b|messages|reach|audience size|impressions?|users", l):
        ks.append("sent")
    seen, out = set(), []
    for k in ks:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _entities(q: str, res: dict) -> list[tuple[str, str]]:
    """Return [(dimension, name)] for entity names mentioned verbatim in the question."""
    found, taken = [], q.lower()
    names = ([("camp", x["k"]) for x in res["camps"]] + [("chan", x["k"]) for x in res["chans"]]
             + [("seg", x["k"]) for x in res["segs"]])
    for dim, name in sorted(names, key=lambda t: len(t[1]), reverse=True):
        if not name or name in ("All", "(blank)"):
            continue
        pat = r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])"
        if re.search(pat, taken):
            found.append((dim, name))
            taken = re.sub(pat, " ", taken)
    return found


def _dim_items(res: dict, dim: str) -> list[dict]:
    return {"camp": res["camps"], "chan": res["chans"], "seg": res["segs"]}[dim]


def _rank(items: list[dict], k: str, high: bool = True) -> list[dict]:
    vals = [x for x in items if x.get(k) is not None]
    return sorted(vals, key=lambda x: x[k], reverse=high)


def _leaders(items: list[dict], k: str, high: bool) -> list[dict]:
    r = _rank(items, k, high)
    if not r:
        return []
    best = r[0][k]
    return [x for x in r if abs(x[k] - best) < 1e-9]


def _entity_block(res: dict, ents: list[tuple[str, str]], keys: list[str]) -> Exact:
    m, tot = res["m"], res["tot"]
    all_keys = ["sent", "ctr", "cvr", "or", "unr", "clicks", "conv", "rev"]
    keys = keys or [k for k in all_keys if _has(m, k)]
    keys = [k for k in keys if _has(m, k)] or [k for k in all_keys if _has(m, k)]
    rows = []
    for dim, name in ents:
        item = next(x for x in _dim_items(res, dim) if x["k"] == name)
        rows.append((dim, name, item))
    if len(rows) == 1:
        dim, name, it = rows[0]
        items = _dim_items(res, dim)
        lines = [f"**{name}**"]
        for k in keys:
            line = f"- {DISP[k]}: **{fmt_exact(k, it.get(k))}**"
            rk = _rank(items, k, True)
            if it.get(k) is not None and len(rk) > 1:
                pos = next((i for i, x in enumerate(rk) if x["k"] == name), None)
                if pos is not None:
                    line += f" (rank {pos + 1} of {len(rk)})"
            if k in ADDITIVE and tot.get(k):
                line += f", {it[k] / tot[k] * 100:.1f}% of total"
            lines.append(line)
        return Exact("\n".join(lines), [name])
    head = "| Metric | " + " | ".join(n for _, n, _ in rows) + " |"
    sep = "|---|" + "---|" * len(rows)
    body = ["| " + DISP[k] + " | " + " | ".join(fmt_exact(k, it.get(k)) for _, _, it in rows) + " |"
            for k in keys]
    return Exact("\n".join([head, sep] + body), [n for _, n, _ in rows])


def _period_answer(res: dict) -> Exact:
    p = res["per"]
    if not p:
        return Exact("There are no usable dates in this report, so changes over time can't be calculated.")
    lines = ["Second half vs first half of the dates in this report "
             "(no separate previous-period data was uploaded):"]
    for k in ("ctr", "cvr", "or", "unr", "rev", "sent"):
        a, b = p["a"].get(k), p["b"].get(k)
        if a is None or b is None or not _has(res["m"], k):
            continue
        ch = pct_change(b, a)
        chs = f" ({ch:+.1f}%)" if ch is not None else ""
        lines.append(f"- {DISP[k]}: {fmt_exact(k, a)} → {fmt_exact(k, b)}{chs}")
    return Exact("\n".join(lines))


def _table(res: dict, dim: str, keys: list[str], limit: int = 12) -> Exact:
    items = _dim_items(res, dim)
    dn = {"camp": "Campaign", "chan": "Channel", "seg": "Segment"}[dim]
    first = keys[0]
    rows = _rank(items, first, True)[:limit]
    head = f"| {dn} | " + " | ".join(DISP[k] for k in keys) + " |"
    sep = "|---|" + "---|" * len(keys)
    body = ["| " + x["k"] + " | " + " | ".join(fmt_exact(k, x.get(k)) for k in keys) + " |" for x in rows]
    note = f"\n\nSorted by {LABEL[first]}, highest first."
    if len(items) > limit:
        note += f" Showing top {limit} of {len(items)}."
    return Exact("\n".join([head, sep] + body) + note)


def _ranking(items, tot, keys, high, n, dn) -> Exact:
    out, must = [], []
    for k in keys:
        rk = _rank(items, k, high)
        if not rk:
            out.append(f"- {DISP[k]} isn't available for any {dn}.")
            continue
        if n > 1:
            lst = "; ".join(f"{i + 1}. **{x['k']}** ({fmt_exact(k, x[k])})" for i, x in enumerate(rk[:n]))
            out.append(f"- {'Top' if high else 'Bottom'} {min(n, len(rk))} {dn}s by {LABEL[k]}: {lst}")
            must += [x["k"] for x in rk[:n]]
            continue
        lead = _leaders(items, k, high)
        names = " & ".join(f"**{x['k']}**" for x in lead)
        tie = " (tie)" if len(lead) > 1 else ""
        line = f"- {names} had the {'highest' if high else 'lowest'} {LABEL[k]}{tie}: {fmt_exact(k, lead[0][k])}"
        if k in ADDITIVE and tot.get(k):
            line += f" ({lead[0][k] / tot[k] * 100:.1f}% of the total {fmt_exact(k, tot[k])})"
        nxt = [x for x in rk if x not in lead][:2]
        if nxt:
            line += ". Next: " + ", ".join(f"{x['k']} ({fmt_exact(k, x[k])})" for x in nxt)
        out.append(line)
        must += [x["k"] for x in lead]
    return Exact("\n".join(out), must)


def exact_answer(q: str, res: dict, insights: list[dict]) -> Optional[Exact]:
    """Answer from computed aggregates. Returns None when the question isn't understood."""
    l = re.sub(r"\s+", " ", q.lower()).strip()
    m, tot = res["m"], res["tot"]
    camps = res["camps"]

    # (a) named campaign / channel / segment
    ents = _entities(q, res)
    hi0, lo0 = re.search(rf"\b({_HIGH})\b", l), re.search(rf"\b({_LOW})\b", l)
    if ents:
        # "which campaign had the highest revenue on Email?" → rank campaigns INSIDE that channel/segment
        if (hi0 or lo0) and len(ents) == 1 and ents[0][0] in ("chan", "seg") \
                and not re.search(r"which (channel|segment)", l) and res.get("cross", {}).get(ents[0]):
            dk, dv = ents[0]
            items = res["cross"][ents[0]]
            ftot = next(x for x in _dim_items(res, dk) if x["k"] == dv)
            ks = [k for k in _metric_keys(l, m) if _has(m, k)] or [k for k in ("ctr", "cvr", "rev") if _has(m, k)]
            high = not (lo0 and not hi0)
            tn = re.search(r"(?:top|bottom)\s*(\d{1,2})|(\d{1,2})\s*(?:best|top|worst)", l)
            n = min(int((tn.group(1) or tn.group(2))), 10) if tn else 0
            ex = _ranking(items, ftot, ks, high, n, "campaign")
            ex.text = f"Within **{dv}** ({'channel' if dk == 'chan' else 'segment'}):\n" + ex.text
            ex.must_include.append(dv)
            return ex
        return _entity_block(res, ents, _metric_keys(l, m))

    # (b) special intents
    if re.search(r"high ctr.*low conv|low conv.*high ctr|clicks? but (low|poor|weak)|click.*not convert", l):
        if not res["hl"]:
            return Exact("No campaign combined above-average CTR with below-average conversion.")
        return Exact("Above-average CTR but below-average conversion:\n" + "\n".join(
            f"- **{x['k']}**: CTR {fmt_exact('ctr', x['ctr'])}, conversion {fmt_exact('cvr', x['cvr'])}"
            for x in res["hl"]) + "\n\nCheck the post-click experience (landing page, offer) for these.",
            [x["k"] for x in res["hl"]])
    if re.search(r"investigat|attention|anomal|unusual|problem|outlier|red flag|need.*(look|review)", l):
        if not res["an"]:
            return Exact("No campaign is outside the expected range (needs at least 5 campaigns to judge).")
        return Exact("Worth investigating:\n" + "\n".join(
            f"- **{a['camp']}** – {NM[a['k']]} {'high' if a['z'] > 0 else 'low'}: "
            f"{fmt_exact(a['k'], a['v'])} vs average {fmt_exact(a['k'], a['m'])}" for a in res["an"][:6]),
            list({a["camp"] for a in res["an"][:6]}))
    if re.search(r"chang|previous|prior|last period|over time|first half|second half|trend|growth|declin|"
                 r"\bdrop|increase|decrease", l):
        return _period_answer(res)
    if re.search(r"takeaway|summary|summar|overall insight|key insight|insights?\b|highlights?", l) and not _metric_keys(l, m):
        if not insights:
            return Exact("No notable insights were found in this report.")
        return Exact("\n".join(f"- **{i['title']}** — {i['data']}" for i in insights[:5]))

    # (c) metric questions
    keys = [k for k in _metric_keys(l, m)]
    dim = "chan" if re.search(r"channel|medium|platform", l) else \
          "seg" if re.search(r"segment|audience|cohort", l) else "camp"
    hi, lo = re.search(rf"\b({_HIGH})\b", l), re.search(rf"\b({_LOW})\b", l)
    if keys:
        missing = [k for k in keys if not _has(m, k)]
        keys = [k for k in keys if _has(m, k)]
        if not keys:
            return Exact(f"{DISP[missing[0]]} can't be calculated from this report (the needed columns are missing).")
        items = _dim_items(res, dim)
        if not items:
            return Exact(f"This report has no {'channel' if dim == 'chan' else 'segment'} column.")
        dn = {"camp": "campaign", "chan": "channel", "seg": "segment"}[dim]
        topn = re.search(r"(?:top|best|worst|bottom|lowest|highest)\s*(\d{1,2})|(\d{1,2})\s*(?:best|top|worst|lowest|highest)", l)
        # total / overall / average
        if re.search(r"\btotal\b|overall|altogether|in all|across all|how many|\bsum\b|\baverage\b|\bavg\b|\bmean\b", l) \
                and not (hi or lo):
            lines = []
            for k in keys:
                line = f"- Overall {LABEL[k]}: **{fmt_exact(k, tot.get(k))}**"
                if k not in ADDITIVE:
                    vals = [x[k] for x in items if x.get(k) is not None]
                    if vals:
                        line += f" (weighted across all data; simple average of {dn}s: {sum(vals) / len(vals):.2f}%)"
                lines.append(line)
            return Exact("\n".join(lines))
        if hi or lo:
            high = bool(hi) and not (lo and lo.start() < hi.start())
            if lo and not hi:
                high = False
            n = min(int((topn.group(1) or topn.group(2))), 10) if topn else 0
            return _ranking(items, tot, keys, high, n, dn)
        return _table(res, dim, keys[:4])

    # (d) no metric named
    if dim in ("chan", "seg") or re.search(r"perform|better|best|worst|winner|compare|comparison", l):
        d = dim if dim != "camp" or not re.search(r"campaign", l) else "camp"
        items = _dim_items(res, d)
        if not items:
            return Exact(f"This report has no {'channel' if d == 'chan' else 'segment'} column.")
        ks = [k for k in ("ctr", "cvr", "rev") if _has(m, k)]
        if not ks:
            return None
        if re.search(r"\bbetter\b|\bbest\b|perform|winner|worst|lowest", l):
            high = not re.search(r"worst|lowest|weak", l)
            lines, must = [], []
            for k in ks:
                lead = _leaders(items, k, high)
                if lead:
                    lines.append(f"- By {LABEL[k]}: **{' & '.join(x['k'] for x in lead)}** ({fmt_exact(k, lead[0][k])})")
                    must += [x["k"] for x in lead]
            if lines:
                return Exact(("Best" if high else "Weakest") + " performer depends on the metric:\n" + "\n".join(lines), must)
        return _table(res, d, ks)
    return None


def capabilities_hint(res: dict) -> str:
    ex = ["Which campaign had the highest revenue?", "Lowest conversion rate by channel",
          "Top 3 campaigns by CTR", "Compare " + " and ".join(x["k"] for x in res["camps"][:2]) if len(res["camps"]) > 1 else "",
          "What changed compared to the previous period?", "Which campaigns need investigation?"]
    return "Try, for example: " + " · ".join(f"*{e}*" for e in ex if e)


def answer_question(q: str, res: dict, insights: list[dict]) -> str:
    """Built-in (no-AI) answer, always safe."""
    ex = exact_answer(q, res, insights)
    if ex:
        return ex.text
    return NOT_SUFFICIENT + " " + capabilities_hint(res)


# ─────────────────────────────────────────────────────────────────────────────
# 4. LLM CLIENT (OpenAI-compatible) — robust, multi-key failover
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LLMConfig:
    api_keys: str = ""
    model: str = ""
    base_url: str = ""
    provider: str = ""

    @property
    def keys(self) -> list[str]:
        return _get_keys_list(self.api_keys, self.provider)

    @property
    def usable(self) -> bool:
        is_local = any(h in (self.base_url or "") for h in ("localhost", "127.0.0.1"))
        return bool(self.base_url and self.model and (self.keys or is_local))


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    error: str = ""                      # user-facing, already explained
    attempts: list = field(default_factory=list)
    latency: float = 0.0
    key_index: int = 0
    fatal: bool = False                  # True = another key won't help (bad model / URL)


_UAS = ["Mozilla/5.0 (compatible; AIInsightsGenerator/1.1)",
        "OpenAI/Python 1.55.0",
        "curl/8.5.0"]


def _get_keys_list(api_key_str: str, provider: str = "") -> list[str]:
    def split(s: str) -> list[str]:
        out = []
        for k in re.split(r"[,;\n]+", s or ""):
            k = re.sub(r"\s+", "", k).strip("\"'")
            if k.lower().startswith("bearer"):
                k = k[6:]
            if k:
                out.append(k)
        return out

    keys = split(api_key_str)
    if not keys:
        env = ["LLM_API_KEY", "LLM_API_KEYS"]
        p = provider.lower()
        env += (["GEMINI_API_KEY", "GOOGLE_API_KEY"] if "gemini" in p else
                ["GROQ_API_KEY"] if "groq" in p else
                ["OPENAI_API_KEY", "OPENROUTER_API_KEY"] if "openai" in p or "openrouter" in p else [])
        for ev in env:
            keys += split(os.getenv(ev, ""))
    return list(dict.fromkeys(keys))


def normalize_base_url(url: str) -> str:
    """Forgiving: fixes trailing slash, a pasted /chat/completions, and missing /v1 on Groq."""
    u = (url or "").strip().rstrip("/")
    u = re.sub(r"/chat/completions$", "", u)
    if re.fullmatch(r"https?://api\.groq\.com/openai", u):
        u += "/v1"
    return u


def _body_message(raw: bytes) -> str:
    txt = raw.decode("utf-8", "ignore").strip()
    if not txt:
        return ""
    if txt[:1] in "[{":
        try:
            j = json.loads(txt)
            if isinstance(j, list) and j:
                j = j[0]
            e = j.get("error", j) if isinstance(j, dict) else j
            if isinstance(e, dict):
                return str(e.get("message") or e.get("error") or e)[:300]
            return str(e)[:300]
        except Exception:
            pass
    if "<html" in txt.lower() or "error code: 1010" in txt.lower() or "cloudflare" in txt.lower():
        return "Blocked by the provider's firewall (Cloudflare) before reaching the API."
    return txt[:300]


def _explain(status: int, msg: str) -> str:
    base = {
        400: "Bad request – the model name or request format is wrong.",
        401: "Invalid API key – check it was copied completely, with no extra characters.",
        402: "Payment required – this provider needs credit for that model.",
        403: "Access forbidden – the provider refused this request (blocked client, restricted key or region).",
        404: "Not found – the Base URL or Model name is wrong (try the 'List models' button).",
        408: "Timed out.",
        413: "Request too large for this model's free limit – choose a different model.",
        429: "Rate limit or daily quota reached – wait a minute, or add another key.",
    }.get(status, "Server error at the provider – try again shortly." if status >= 500 else "Request failed.")
    return f"{base}" + (f" Provider says: “{msg}”" if msg else "")


def _post(url: str, key: str, payload: dict, timeout: int = 45):
    """Returns (status, body_bytes). Retries with alternate User-Agents if a firewall returns 403."""
    data = json.dumps(payload).encode()
    last = (0, b"")
    for ua in _UAS:
        h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": ua}
        if key:
            h["Authorization"] = f"Bearer {key}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            last = (e.code, body)
            firewall = e.code == 403 and (b"<html" in body.lower() or b"1010" in body or not body.strip())
            if firewall:
                continue          # try next User-Agent
            return last
    return last


def _call(prompt: str, cfg: LLMConfig, *, system: str = "", temperature: float = 0.2,
          max_tokens: int = 700) -> LLMResult:
    base = normalize_base_url(cfg.base_url)
    keys = cfg.keys
    is_local = any(h in base for h in ("localhost", "127.0.0.1"))
    if not base or not cfg.model:
        return LLMResult(False, error="Base URL or model is missing.", fatal=True)
    if not keys and not is_local:
        return LLMResult(False, error="No API key entered.", fatal=True)
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    payload = {"model": cfg.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
    attempts = []
    t0 = time.time()
    for idx, key in enumerate(keys or [""]):
        tag = f"Key #{idx + 1} (…{key[-4:]})" if key else "Endpoint"
        for retry in range(2):
            try:
                status, raw = _post(base + "/chat/completions", key, payload)
            except Exception as e:   # network / DNS / SSL / timeout
                msg = str(e)
                if "CERTIFICATE_VERIFY_FAILED" in msg:
                    msg += " – your Python cannot verify HTTPS certificates (install/update `certifi` or your OS certificates)."
                attempts.append(f"{tag}: connection problem – {msg}")
                break
            if status == 200:
                try:
                    out = json.loads(raw.decode())
                    txt = (out["choices"][0]["message"]["content"] or "").strip()
                    if txt:
                        return LLMResult(True, txt, attempts=attempts, latency=time.time() - t0, key_index=idx)
                    attempts.append(f"{tag}: the model returned an empty answer.")
                except Exception:
                    attempts.append(f"{tag}: unexpected response format from the provider.")
                break
            msg = _body_message(raw)
            attempts.append(f"{tag}: HTTP {status}. {_explain(status, msg)}")
            if status in (400, 404, 413, 422):      # config problem → other keys won't help
                return LLMResult(False, error="\n".join(attempts), attempts=attempts, fatal=True,
                                 latency=time.time() - t0)
            if status == 429 and retry == 0 and len(keys) <= 1:
                time.sleep(4)                       # brief single retry when there is no other key
                continue
            break
    return LLMResult(False, error=f"All {len(keys) or 1} API key(s) failed.\n" + "\n".join(attempts),
                     attempts=attempts, latency=time.time() - t0)


def test_connection(cfg: LLMConfig) -> LLMResult:
    r = _call("Reply with the single word: OK", cfg, temperature=0, max_tokens=5)
    return r


def list_models(cfg: LLMConfig) -> tuple[list[str], str]:
    base = normalize_base_url(cfg.base_url)
    keys = cfg.keys or [""]
    err = ""
    for key in keys:
        for ua in _UAS:
            h = {"Accept": "application/json", "User-Agent": ua}
            if key:
                h["Authorization"] = f"Bearer {key}"
            try:
                with urllib.request.urlopen(urllib.request.Request(base + "/models", headers=h), timeout=20) as r:
                    j = json.loads(r.read().decode())
                ids = [str(x.get("id", "")).replace("models/", "") for x in j.get("data", [])]
                return sorted(i for i in ids if i), ""
            except urllib.error.HTTPError as e:
                b = e.read() or b""
                err = f"HTTP {e.code}. {_explain(e.code, _body_message(b))}"
                if e.code != 403:
                    break
            except Exception as e:
                err = str(e)
                break
    return [], err


# ─────────────────────────────────────────────────────────────────────────────
# 5. NUMBER VERIFICATION — the accuracy guard
# ─────────────────────────────────────────────────────────────────────────────
_NUM = re.compile(r"(₹|rs\.?\s?)?\s?(\d[\d,]*(?:\.\d+)?)\s?(crore|cr|lakh|lac|l|k|m|%)?(?![a-z0-9])", re.I)
_MULT = {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "lac": 1e5, "k": 1e3, "m": 1e6}


def _numbers(text: str) -> list[dict]:
    out = []
    for mt in _NUM.finditer(text):
        cur, raw, suf = mt.group(1), mt.group(2), (mt.group(3) or "").lower()
        clean = raw.replace(",", "")
        try:
            val = float(clean)
        except ValueError:
            continue
        dec = len(clean.split(".")[1]) if "." in clean else 0
        mult = _MULT.get(suf, 1.0)
        pct = suf == "%"
        out.append({"tok": mt.group(0).strip(), "v": val * mult, "tol": 0.5 * (10 ** -dec) * mult + 1e-9,
                    "sig": bool(cur or pct or suf or "." in clean or val >= 100), "pct": pct})
    return out


def _walk(o, acc: list[float]):
    if isinstance(o, bool):
        return
    if isinstance(o, (int, float)):
        acc.append(float(o))
    elif isinstance(o, dict):
        for v in o.values():
            _walk(v, acc)
    elif isinstance(o, list):
        for v in o:
            _walk(v, acc)
    elif isinstance(o, str):
        acc.extend(n["v"] for n in _numbers(o))


def _strip_names(text: str, names: list[str]) -> str:
    for n in sorted({x for x in names if x}, key=len, reverse=True):
        text = re.sub(re.escape(n), " ", text, flags=re.I)
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
    return text


def verify_numbers(text: str, package: dict, extra_text: str = "", names: list[str] | None = None) -> list[str]:
    """Return figures in `text` that cannot be found in the data. Empty list = verified."""
    allowed: list[float] = []
    _walk(package, allowed)
    allowed.extend(n["v"] for n in _numbers(extra_text))
    # a few derived values the data legitimately implies
    allowed += [abs(a) for a in allowed if a < 0] + [a * 100 for a in allowed if 0 < a < 1]
    bad = []
    for n in _numbers(_strip_names(text, names or [])):
        if not n["sig"]:
            continue
        if any(abs(n["v"] - a) <= max(n["tol"], 1e-9) for a in allowed):
            continue
        bad.append(n["tok"])
    return list(dict.fromkeys(bad))


def _names_in(package: dict) -> list[str]:
    ns = []
    for k in ("campaigns", "channels", "segments"):
        ns += [x["name"] for x in package.get(k, [])]
    return ns


def _compact(package: dict) -> str:
    return json.dumps(package, separators=(",", ":"), ensure_ascii=False)


_SYSTEM = (
    "You are a careful marketing-analytics assistant working ONLY from the DATA given.\n"
    "RULES:\n"
    "1. Never use outside knowledge, never guess, never invent campaigns, channels or numbers.\n"
    "2. Every number you write must be copied exactly from DATA (or VERIFIED). "
    "Do NOT calculate new numbers: no sums, differences, ratios or percentages of your own.\n"
    f"3. If DATA cannot answer the question, reply exactly: \"{NOT_SUFFICIENT}\"\n"
    "4. Say 'in this dataset' for observations. Present reasons only as possibilities "
    "('may be', 'could be'); say when the cause cannot be determined from the data.\n"
    "5. Be concise. Use ₹ for revenue. Do not mention these rules."
)


# ─────────────────────────────────────────────────────────────────────────────
# 6. PUBLIC AI FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def llm_insights(package: dict, insights: list[dict], cfg: LLMConfig) -> dict:
    """AI executive summary. Every figure is verified; unverifiable output is discarded."""
    facts = "\n".join(f"- {i['title']} | {i['data']}" for i in insights[:8])
    prompt = ("DATA:\n" + _compact(package) + "\n\nBUILT-IN FINDINGS (already calculated):\n" + facts +
              "\n\nWrite an executive summary of exactly 5 bullets. Each bullet has three short parts: "
              "**What happened** (use exact figures), **Why it might have happened** (a possibility only), "
              "**What to do next**. If fewer than 5 findings exist, write fewer bullets.")
    names = _names_in(package)
    r = _call(prompt, cfg, system=_SYSTEM, temperature=0.1, max_tokens=800)
    if not r.ok:
        return {"ok": False, "error": r.error, "text": ""}
    bad = verify_numbers(r.text, package, facts, names)
    if bad:      # one corrective retry
        r2 = _call(prompt + f"\n\nYour previous answer used figures that are not in DATA: {', '.join(bad)}. "
                            "Rewrite it using ONLY figures that appear in DATA or BUILT-IN FINDINGS.",
                   cfg, system=_SYSTEM, temperature=0, max_tokens=800)
        if r2.ok:
            bad2 = verify_numbers(r2.text, package, facts, names)
            if not bad2:
                return {"ok": True, "text": r2.text, "verified": True, "latency": r.latency + r2.latency}
            bad = bad2
        return {"ok": False, "error": "", "rejected": bad, "text": ""}
    return {"ok": True, "text": r.text, "verified": True, "latency": r.latency}


def ask(question: str, res: dict, cfg: Optional[LLMConfig], use_ai: bool) -> dict:
    """
    Returns {text, kind, ai_note, ai_text, error, notes}
      kind: 'exact' | 'ai' | 'none'
    """
    package, insights = res["pkg"], res["insights"]
    ex = exact_answer(question, res, insights)
    ai_on = bool(use_ai and cfg and cfg.usable)
    out = {"kind": "none", "text": "", "ai_text": "", "error": "", "notes": []}
    names = _names_in(package)

    if ex and not ai_on:
        return {**out, "kind": "exact", "text": ex.text}
    if not ex and not ai_on:
        return {**out, "text": NOT_SUFFICIENT + " " + capabilities_hint(res)}

    if ex:
        prompt = ("DATA:\n" + _compact(package) + "\n\nQUESTION: " + question +
                  "\n\nVERIFIED (calculated by code, already shown to the user):\n" + ex.text +
                  "\n\nAdd ONE or TWO sentences of useful business interpretation or a suggested next step. "
                  "Do not repeat the answer. Do not write any number. Any reason must be a possibility, not a fact.")
        r = _call(prompt, cfg, system=_SYSTEM, temperature=0.2, max_tokens=200)
        out.update(kind="exact", text=ex.text)
        if not r.ok:
            out["error"] = r.error
            return out
        bad = verify_numbers(r.text, package, ex.text, names)
        if bad:
            out["notes"].append("AI commentary hidden: it contained figures that are not in your data.")
        elif NOT_SUFFICIENT.lower() in r.text.lower():
            pass
        else:
            out["ai_text"] = r.text
        return out

    prompt = ("DATA:\n" + _compact(package) + "\n\nQUESTION: " + question +
              "\n\nAnswer from DATA only. Quote figures exactly as they appear.")
    r = _call(prompt, cfg, system=_SYSTEM, temperature=0, max_tokens=500)
    if not r.ok:
        out["error"] = r.error
        out["text"] = NOT_SUFFICIENT + " " + capabilities_hint(res)
        return out
    bad = verify_numbers(r.text, package, "", names)
    if bad:
        out["notes"].append("The AI's draft used figures that could not be verified against your data "
                            f"({', '.join(bad[:4])}), so it was discarded to keep answers accurate.")
        out["text"] = NOT_SUFFICIENT + " " + capabilities_hint(res)
        return out
    return {**out, "kind": "ai", "text": r.text}
