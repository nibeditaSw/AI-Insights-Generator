"""Data Processing Layer: clean, aggregate, KPIs, trends, anomalies.

Accuracy rules enforced here:
  * A rate is only computed when its denominator exists (no silent "/ 1" fallback).
  * Blank rows and "Total"/"Grand total" rows are removed so nothing is double-counted.
  * Rate-like columns (e.g. "Open Rate %") are never mistaken for count columns.
  * Every impossible value (a rate above 100 %) is reported as a data warning.
"""
import re
import numpy as np
import pandas as pd

METRIC_KEYS = ["sent", "del", "open", "click", "conv", "rev", "uns"]

# words that show a column is a ratio / cost / date, i.e. NOT a raw count
_RATEISH = r"rate|%|ratio|pct|percent|(?<![a-z])per(?![a-z])|avg|average|cost|cpc|cpm|cpa|roas|ctr|cvr|ctor|share|growth|change"
_TIMEISH = r"date|time|day|month|week|year"


def _p(x: str) -> str:
    """Whole-word match that also treats '_' as a separator (Emails_Sent)."""
    return rf"(?<![a-z])(?:{x})(?![a-z])"


def _find(cols, pattern, exclude=None, taken=()):
    for c in cols:
        if c in taken:
            continue
        s = str(c)
        if re.search(pattern, s, re.I) and not (exclude and re.search(exclude, s, re.I)):
            return c
    return None


def detect_columns(df: pd.DataFrame) -> dict:
    cols = list(df.columns)
    taken: set = set()
    m: dict = {}

    def pick(key, pattern, exclude=None):
        c = _find(cols, pattern, exclude, taken)
        m[key] = c
        if c is not None:
            taken.add(c)

    # dimensions first, then metrics (so one column is never used twice)
    pick("camp", rf"campaign|camp.?name|ad.?name|{_p('name')}")
    pick("date", rf"{_p('date|day|time|timestamp')}|date")
    pick("chan", r"channel|medium|source|platform")
    pick("seg", r"segment|audience(?!.?size)|target")
    cnt_ex = f"{_RATEISH}|{_TIMEISH}"
    pick("sent", rf"{_p('sent|attempted|reached|impressions?')}|audience.?size|total.?messages", cnt_ex)
    pick("del", _p(r"deliver(?:ed|y|ies)?"), cnt_ex)
    pick("open", _p("opens?|opened"), cnt_ex)
    pick("click", _p("clicks?|clicked"), cnt_ex)
    pick("rev", rf"revenue|gmv|{_p('sales')}|order.?value", f"{_RATEISH}|{_TIMEISH}")
    pick("conv", _p("conversions?|purchases?|orders?"), f"{cnt_ex}|value|amount|revenue|sales")
    pick("uns", r"unsub", cnt_ex)
    if not m["click"] and not m["sent"]:
        raise ValueError(
            "Could not find count columns (Sent, Delivered, Clicks, Conversions, Revenue…). "
            "Check that the headers contain those words and hold counts, not only rates."
        )
    return m


def to_num(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").fillna(0)
    cleaned = s.astype(str).str.replace(r"[₹$,%\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def _num_or_nan(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    return pd.to_numeric(s.astype(str).str.replace(r"[₹$,%\s]", "", regex=True), errors="coerce")


_TOTAL_RE = re.compile(r"^\s*(grand\s*total|sub\s*total|totals?|overall|average|avg|mean)\s*$", re.I)


def _metrics(sub: pd.DataFrame, m: dict) -> dict:
    def S(k):
        return float(to_num(sub[m[k]]).sum()) if m.get(k) else 0.0

    sent, dele = S("sent"), S("del")
    base = dele or sent            # denominator for engagement rates
    clicks, conv, opens, uns = S("click"), S("conv"), S("open"), S("uns")
    if m.get("conv"):
        if m.get("click"):
            cvr = (conv / clicks * 100) if clicks else None
        else:
            cvr = (conv / base * 100) if base else None
    else:
        cvr = None
    return {
        "n": len(sub),
        "sent": sent, "del": dele, "opens": opens,
        "clicks": clicks, "conv": conv, "rev": S("rev"), "uns": uns,
        "dr": (dele / sent * 100) if (sent and m.get("del")) else None,
        "or": (opens / base * 100) if (m.get("open") and base) else None,
        "ctr": (clicks / base * 100) if (m.get("click") and base) else None,
        "cvr": cvr,
        "unr": (uns / base * 100) if (m.get("uns") and base) else None,
    }


def pct_change(b, a):
    if a in (None, 0) or b is None:
        return None
    try:
        return (b - a) / abs(a) * 100
    except ZeroDivisionError:
        return None


def fmt_indian(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "–"
    if abs(n) >= 1e7:
        return f"{n/1e7:.2f}Cr"
    if abs(n) >= 1e5:
        return f"{n/1e5:.1f}L"
    if abs(n) >= 1e3:
        return f"{n/1e3:.1f}K"
    return f"{round(n)}"


def group_indian(n) -> str:
    """Exact integer with Indian digit grouping: 1234567 -> 12,34,567."""
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return "–"
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return ("-" if n < 0 else "") + s


def fmt_k(k, v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    if k == "rev":
        return "₹" + fmt_indian(v)
    if k in ("sent", "del", "clicks", "conv", "opens", "uns", "n"):
        return fmt_indian(v)
    return f"{v:.2f}%"


def fmt_exact(k, v) -> str:
    """Full-precision display used in Ask Your Data answers."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    if k == "rev":
        return "₹" + group_indian(v)
    if k in ("sent", "del", "clicks", "conv", "opens", "uns", "n"):
        return group_indian(v)
    return f"{v:.2f}%"


def sample_data(n_campaigns=10, seed=7) -> pd.DataFrame:
    import random
    rng = random.Random(seed)
    rows = []
    chs, sg = ["Email", "Push", "SMS"], ["New", "Returning"]
    for c in range(1, n_campaigns + 1):
        for d in range(1, 15, 2):
            late = d > 7
            sent = round(20000 + rng.random() * 40000)
            dele = round(sent * (0.95 + rng.random() * 0.04))
            ctr = (0.03 + rng.random() * 0.015) * (1.14 if late else 1)
            cvr = (0.02 + rng.random() * 0.008) * (0.88 if late else 1)
            if c == 7:
                cvr *= 0.3
            un = 0.002 + rng.random() * 0.001
            if c == 4:
                un *= 5
            cl = round(dele * ctr)
            cv = round(cl * cvr * 8)
            rows.append({
                "Campaign": f"Campaign {c}",
                "Date": f"2026-09-{d:02d}",
                "Channel": chs[c % 3], "Segment": sg[c % 2],
                "Customer ID": 800000 + c * 100 + d,
                "Email": f"user{c}{d}@example.com",
                "Sent": sent, "Delivered": dele,
                "Opens": round(dele * (0.25 + rng.random() * 0.1)),
                "Clicks": cl, "Conversions": cv,
                "Revenue": cv * round(450 + rng.random() * 300),
                "Unsubscribes": round(dele * un),
            })
    return pd.DataFrame(rows)


def _clean_rows(clean: pd.DataFrame, m: dict):
    """Drop blank rows and total/summary rows. Returns (df, dropped_blank, dropped_total)."""
    metric_cols = [m[k] for k in METRIC_KEYS if m.get(k)]
    text_cols = [m[k] for k in ("camp", "date", "chan", "seg") if m.get(k)]
    if not len(clean):
        return clean, 0, 0
    if metric_cols:
        blank = pd.concat([_num_or_nan(clean[c]).isna() for c in metric_cols], axis=1).all(axis=1)
    else:
        blank = pd.Series(False, index=clean.index)
    is_total = pd.Series(False, index=clean.index)
    for c in text_cols:
        is_total |= clean[c].astype(str).str.match(_TOTAL_RE)
    keep = ~(blank | is_total)
    return clean[keep].copy(), int(blank.sum()), int((is_total & ~blank).sum())


def analyze(clean: pd.DataFrame, m: dict) -> dict:
    clean, dropped_blank, dropped_total = _clean_rows(clean, m)
    if clean.empty:
        raise ValueError("No usable data rows were found after removing blank and total rows.")

    used = [v for v in m.values() if v]
    text_cols = {m["camp"], m["date"], m["chan"], m["seg"]} - {None}
    miss, cells = 0, 0
    for h in used:
        s = clean[h]
        cells += len(s)
        if h in text_cols:
            miss += int((s.isna() | s.astype(str).str.strip().eq("")).sum())
        else:
            miss += int(_num_or_nan(s).isna().sum())
    dup = int(clean.duplicated().sum())

    # group labels: blanks become "(blank)" instead of "nan"
    work = clean.copy()
    for k in ("camp", "chan", "seg"):
        if m.get(k):
            col = work[m[k]]
            lab = col.astype(str).str.strip()
            lab = lab.where(~(col.isna() | lab.eq("") | lab.str.lower().eq("nan")), "(blank)")
            work[m[k]] = lab

    def grp(by):
        out = []
        for k, sub in work.groupby(by, dropna=False, sort=True):
            d = _metrics(sub, m)
            d["k"] = str(k)
            out.append(d)
        return out

    camps = grp(m["camp"]) if m["camp"] else [{"k": "All", **_metrics(work, m)}]
    chans = grp(m["chan"]) if m["chan"] else []
    segs = grp(m["seg"]) if m["seg"] else []
    tot = _metrics(work, m)

    # campaign results inside each channel / segment (powers "highest revenue on Email")
    cross = {}
    if m["camp"]:
        for dk in ("chan", "seg"):
            if not m.get(dk):
                continue
            for dv, dsub in work.groupby(m[dk], sort=True):
                items = []
                for ck, csub in dsub.groupby(m["camp"], sort=True):
                    d = _metrics(csub, m)
                    d["k"] = str(ck)
                    items.append(d)
                cross[(dk, str(dv))] = items

    per, daily = None, []
    if m["date"]:
        t = pd.to_datetime(work[m["date"]], errors="coerce")
        ok = work[t.notna()].copy()
        ok["_t"] = t[t.notna()]
        if len(ok) >= 4:
            ts = ok["_t"].sort_values()
            mid = ts.iloc[len(ts) // 2]
            a, b = ok[ok["_t"] < mid], ok[ok["_t"] >= mid]
            if len(a) and len(b):
                per = {"a": _metrics(a, m), "b": _metrics(b, m)}
            for d, sub in sorted(ok.groupby(ok["_t"].dt.date)):
                row = _metrics(sub, m)
                row["d"] = str(d)
                daily.append(row)

    # anomalies: |z| >= 1.5 on ctr/cvr/unr, needs >= 5 campaigns
    an, Z = [], {}
    if len(camps) >= 5:
        for k in ("ctr", "cvr", "unr"):
            vals = [c[k] for c in camps if c.get(k) is not None]
            if len(vals) < 5:
                continue
            mu, sd = float(np.mean(vals)), float(np.std(vals)) or 1.0
            Z[k] = {"m": mu, "s": sd}
            for c in camps:
                if c.get(k) is None:
                    continue
                z = (c[k] - mu) / sd
                if abs(z) >= 1.5 and not (k == "unr" and z < 0):
                    an.append({"camp": c["k"], "k": k, "z": z, "v": c[k], "m": mu})
    an.sort(key=lambda x: abs(x["z"]), reverse=True)

    hl = []
    if "ctr" in Z and "cvr" in Z:
        hl = [c for c in camps
              if (c.get("ctr") is not None and c.get("cvr") is not None)
              and (c["ctr"] - Z["ctr"]["m"]) / Z["ctr"]["s"] > 0.5
              and (c["cvr"] - Z["cvr"]["m"]) / Z["cvr"]["s"] < -0.5][:2]

    # ---- data warnings (shown in the UI and passed to the AI) ----
    warnings = []
    if dropped_blank:
        warnings.append(f"{dropped_blank} blank row(s) ignored.")
    if dropped_total:
        warnings.append(f"{dropped_total} 'Total' / summary row(s) ignored so figures are not double-counted.")
    if not (m.get("sent") or m.get("del")):
        warnings.append("No Sent or Delivered column found, so CTR, open rate and unsubscribe rate cannot be calculated.")
    if m.get("conv") and not m.get("click") and (m.get("sent") or m.get("del")):
        warnings.append("No Clicks column found; conversion rate uses conversions ÷ delivered/sent.")
    for lab, key in (("CTR", "ctr"), ("Open rate", "or"), ("Delivery rate", "dr"), ("Unsubscribe rate", "unr")):
        bad = [c["k"] for c in camps if c.get(key) is not None and c[key] > 100.0001]
        if tot.get(key) is not None and tot[key] > 100.0001:
            bad = ["overall"] + bad
        if bad:
            warnings.append(f"{lab} is above 100% for {', '.join(bad[:3])}"
                            f"{'…' if len(bad) > 3 else ''} — check that the count columns are correct.")

    score = (1 if per else 0) + (1 if len(camps) >= 8 else 0) + (1 if cells and miss / cells < 0.02 else 0)
    conf = "High" if score >= 3 else "Medium" if score == 2 else "Low"
    if warnings and any("above 100%" in w or "cannot be calculated" in w for w in warnings):
        conf = "Low"
    period = f"{daily[0]['d']} to {daily[-1]['d']}" if daily else "not detected"
    return {
        "m": m, "miss": miss, "cells": cells or 1, "dup": dup, "n": len(clean),
        "camps": camps, "chans": chans, "segs": segs, "tot": tot, "cross": cross,
        "per": per, "daily": daily, "an": an, "hl": hl, "Z": Z,
        "conf": conf, "period": period, "warnings": warnings,
        "dropped_blank": dropped_blank, "dropped_total": dropped_total,
    }
