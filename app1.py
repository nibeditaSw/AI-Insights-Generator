# """AI Insights Generator Agent — Python + Streamlit.
# Principle (per BRD): Python calculates & validates, AI only explains. Raw data never reaches the AI.
# Run:  pip install -r requirements.txt  &&  streamlit run app.py
# """
# import json, os, re
# import numpy as np
# import pandas as pd
# import streamlit as st

# # ---------------- Metric rules (as defined for our reports) ----------------
# SUM_M = ["sent", "delivered", "conversion", "revenue"]
# AVG_M = ["delivery_rate", "conversion_rate", "abv", "ipt", "open_rate", "ctr", "unsubscribe_rate"]
# LABEL = {"sent": "Sent", "delivered": "Delivered", "conversion": "Conversion", "revenue": "Revenue",
#          "delivery_rate": "Delivery Rate", "conversion_rate": "Conversion Rate", "abv": "ABV", "ipt": "IPT",
#          "open_rate": "Open Rate", "ctr": "CTR", "unsubscribe_rate": "Unsubscribe Rate"}
# RATES = {"delivery_rate", "conversion_rate", "open_rate", "ctr", "unsubscribe_rate"}
# CAT = {"sent": "Performance", "delivered": "Performance", "delivery_rate": "Performance", "open_rate": "Engagement",
#        "ctr": "Engagement", "unsubscribe_rate": "Engagement", "conversion": "Conversion",
#        "conversion_rate": "Conversion", "revenue": "Revenue", "abv": "Revenue", "ipt": "Revenue"}
# ALIAS = {"sent": ["sent", "messagessent", "totalsent"], "delivered": ["delivered", "totaldelivered"],
#          "conversion": ["conversion", "conversions", "converted", "totalconversions"],
#          "revenue": ["revenue", "totalrevenue", "sales", "gmv"],
#          "delivery_rate": ["deliveryrate", "delivery", "deliveredrate"],
#          "conversion_rate": ["conversionrate", "cvr", "convrate"], "abv": ["abv", "averageordervalue", "aov"],
#          "ipt": ["ipt", "itemsperTransaction".lower(), "itemspertransaction"],
#          "open_rate": ["openrate", "or"], "ctr": ["ctr", "clickthroughrate", "clickrate"],
#          "unsubscribe_rate": ["unsubscriberate", "unsubrate", "unsubscribe"]}
# GOOD_DOWN = {"unsubscribe_rate"}
# ACTION = {"conversion_rate": "Review landing page, offer and post-click journey; compare with higher-converting campaigns.",
#           "conversion": "Check the conversion funnel and audience quality for the affected campaigns.",
#           "revenue": "Break revenue down by campaign/segment to find where the change came from.",
#           "ctr": "Review creative, subject line/CTA and send timing; run an A/B test.",
#           "open_rate": "Test subject lines and send time; check sender reputation.",
#           "delivery_rate": "Check list hygiene, sender/DLT setup and provider delivery reports.",
#           "abv": "Review offer/discount structure and product mix.", "ipt": "Test bundles and cross-sell recommendations.",
#           "unsubscribe_rate": "Review frequency and relevance; consider segment-level throttling.",
#           "sent": "Confirm whether the volume change was planned.", "delivered": "Verify delivery pipeline and volume plan."}
# PII_NAME = re.compile(r"(customer|user|client|first|last|full|contact)\s*name$|e-?mail|phone|mobile|msisdn|address|"
#                       r"\bip\b|(customer|user|order|device|subscriber|cust)\s*id$|imei|aadhaar|\bpan\b|dob|birth")
# EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
# PHONE = re.compile(r"^\+?\d[\d\s\-]{8,14}$")


# def norm(c): return re.sub(r"[^a-z0-9]", "", str(c).lower())


# def fmt(m, v):
#     if v is None or pd.isna(v): return "n/a"
#     if m in RATES: return f"{v:.2f}%"
#     if m in ("revenue", "abv"):
#         if m == "revenue" and abs(v) >= 1e7: return f"₹{v / 1e7:.2f}Cr"
#         if m == "revenue" and abs(v) >= 1e5: return f"₹{v / 1e5:.2f}L"
#         return f"₹{v:,.0f}" if m == "revenue" else f"₹{v:,.2f}"
#     return f"{v:,.0f}" if m in SUM_M else f"{v:,.2f}"


# def to_num(s):
#     if s.dtype.kind in "iuf": return s.astype(float)
#     return pd.to_numeric(s.astype(str).str.replace(r"[₹$,%\s]", "", regex=True), errors="coerce")


# # ---------------- Secure processing layer ----------------
# def load(file, sheet=None):
#     if file.name.lower().endswith((".xlsx", ".xls")): return pd.read_excel(file, sheet_name=sheet or 0)
#     return pd.read_csv(file)


# def find_campaign(df, mapping):
#     cols = [c for c in df.columns if c not in mapping]
#     for c in cols:
#         if norm(c) in ("campaignname", "campaign", "campaigntitle", "name", "journeyname", "flowname"): return c
#     for c in cols:
#         n = norm(c)
#         if any(k in n for k in ("campaign", "journey", "flow")) and not n.endswith("id") and "date" not in n: return c
#     return None


# def secure_prepare(raw, camp_col=None):
#     """Detect columns, remove PII, clean numbers, run quality checks. Returns (df, info)."""
#     df = raw.copy(); df.columns = [str(c).strip() for c in df.columns]
#     info = {"rows_raw": len(df), "pii_removed": [], "issues": [], "metrics": [], "dims": []}
#     mapping = {}
#     for c in df.columns:
#         for m, al in ALIAS.items():
#             if norm(c) in al and m not in mapping.values(): mapping[c] = m; break
#     camp = camp_col if camp_col in df.columns else find_campaign(df, mapping)
#     date = next((c for c in df.columns if any(k in norm(c) for k in ("date", "day", "sentat", "time")) and c not in mapping), None)
#     for c in list(df.columns):  # PII scan: column names + value patterns
#         if c in mapping or c in (camp, date): continue
#         hit = bool(PII_NAME.search(re.sub(r"[_\-]", " ", c.lower())))
#         if not hit and df[c].dtype == object:
#             v = df[c].dropna().astype(str).head(200)
#             hit = len(v) > 0 and (v.str.match(EMAIL).mean() > .3 or v.str.match(PHONE).mean() > .3)
#         if hit: info["pii_removed"].append(c); df = df.drop(columns=c)
#     df = df.rename(columns=mapping)
#     for m in [m for m in mapping.values()]:
#         df[m] = to_num(df[m])
#         if m in RATES and df[m].max() <= 1.0 and df[m].max() > 0: df[m] = df[m] * 100
#     info["metrics"] = [m for m in SUM_M + AVG_M if m in df.columns]
#     if camp: df = df.rename(columns={camp: "campaign"})
#     if date:
#         d = pd.to_datetime(df[date], errors="coerce", dayfirst=True)
#         if d.notna().mean() > .6: df = df.drop(columns=date); df["date"] = d
#     dup = int(df.duplicated().sum()); df = df.drop_duplicates()
#     if "date" in df:
#         df["weekday"] = df["date"].dt.day_name()
#         if df["date"].dt.hour.nunique() > 1: df["send_hour"] = df["date"].dt.hour.astype(str)
#     for c in df.columns:
#         if c not in info["metrics"] + ["campaign", "date"] and df[c].dtype == object and 2 <= df[c].nunique() <= 12:
#             info["dims"].append(c)
#     info["dims"] += [c for c in ("weekday", "send_hour") if c in df and 2 <= df[c].nunique() <= 24]
#     mets = df[info["metrics"]]
#     info["complete_pct"] = round(100 * mets.notna().all(axis=1).mean(), 1) if len(df) else 0
#     miss = mets.isna().sum(); info["missing"] = {LABEL[k]: int(v) for k, v in miss.items() if v}
#     info["duplicates"] = dup
#     for m in info["metrics"]:
#         if (df[m] < 0).any(): info["issues"].append(f"Negative values in {LABEL[m]}")
#         if m in RATES and (df[m] > 100).any(): info["issues"].append(f"{LABEL[m]} above 100% in some rows")
#     if {"sent", "delivered"} <= set(df.columns) and (df["delivered"] > df["sent"]).any():
#         info["issues"].append(f"Delivered > Sent in {int((df['delivered'] > df['sent']).sum())} rows")
#     if "conversion_rate" not in df and {"conversion", "delivered"} <= set(df.columns):
#         info["issues"].append("Conversion Rate column not found — not derived, to follow your averaging rule.")
#     info["has_date"], info["has_campaign"] = "date" in df, "campaign" in df
#     if not info["has_campaign"]: df["campaign"] = ["Row " + str(i + 1) for i in range(len(df))]
#     n = df["campaign"].nunique()
#     info["campaigns"] = n
#     ok = info["complete_pct"] >= 95 and not info["issues"] and n >= 10 and info["has_date"]
#     info["confidence"] = "High" if ok else ("Low" if info["complete_pct"] < 80 or n < 3 else "Medium")
#     return df, info


# def agg(df, by=None):
#     """Team rule: Sum -> Sent, Delivered, Conversion, Revenue | Average -> Delivery Rate, Conversion Rate, ABV, IPT (+other rates)."""
#     cols = {m: ("sum" if m in SUM_M else "mean") for m in SUM_M + AVG_M if m in df.columns}
#     if by is None: return pd.Series({m: (df[m].sum(min_count=1) if f == "sum" else df[m].mean()) for m, f in cols.items()})
#     return df.groupby(by).agg(cols)


# def pct(a, b): return np.nan if (a is None or pd.isna(a) or a == 0 or pd.isna(b)) else (b - a) / abs(a) * 100


# def rz(s):
#     med = s.median(); mad = (s - med).abs().median()
#     if mad == 0: sd = s.std(); return (s - med) / sd if sd else s * 0
#     return 0.6745 * (s - med) / mad


# # ---------------- Analytics engine (deterministic) ----------------
# def analyse(df, info):
#     R = {"overall": agg(df), "camp": agg(df, "campaign"), "changes": None, "periods": None, "trend": None,
#          "anomalies": [], "insights": [], "drivers": []}
#     M, camp, ins = info["metrics"], None, R["insights"]; camp = R["camp"]

#     def add(kind, cat, title, detail, conf, action=""): ins.append(dict(kind=kind, cat=cat, title=title, detail=detail, conf=conf, action=action))

#     if info["has_date"] and df["date"].dt.normalize().nunique() >= 4:  # previous vs current period
#         days = sorted(df["date"].dt.normalize().unique()); h = len(days) // 2
#         prev, cur = df[df["date"].dt.normalize().isin(days[:h])], df[df["date"].dt.normalize().isin(days[h:])]
#         pa, ca = agg(prev), agg(cur)
#         R["periods"] = f"{pd.Timestamp(days[0]):%d %b}–{pd.Timestamp(days[h - 1]):%d %b} vs {pd.Timestamp(days[h]):%d %b}–{pd.Timestamp(days[-1]):%d %b}"
#         R["changes"] = pd.DataFrame({"Previous": pa, "Current": ca, "Change %": [pct(pa[m], ca[m]) for m in pa.index]}).rename(index=LABEL)
#         R["trend"] = df.groupby(df["date"].dt.normalize()).apply(agg)
#         ch = sorted([(m, pct(pa[m], ca[m])) for m in pa.index if not pd.isna(pct(pa[m], ca[m])) and abs(pct(pa[m], ca[m])) >= 5], key=lambda x: -abs(x[1]))[:6]
#         for m, c in ch:
#             good = (c > 0) != (m in GOOD_DOWN)
#             add("positive" if good else "drop", CAT[m], f"{LABEL[m]} {'up' if c > 0 else 'down'} {abs(c):.1f}%",
#                 f"{fmt(m, pa[m])} → {fmt(m, ca[m])} ({R['periods']}).", "High" if len(days) >= 6 else "Medium", "" if good else ACTION[m])
#     if len(camp) >= 5:  # anomalies (robust z-score > 3.5 vs other campaigns)
#         for m in [x for x in ["revenue", "conversion_rate", "ctr", "open_rate", "delivery_rate", "unsubscribe_rate", "abv", "ipt"] if x in camp]:
#             s = camp[m].dropna()
#             if len(s) < 5: continue
#             z = rz(s)
#             for name in z[abs(z) > 3.5].index:
#                 R["anomalies"].append({"Campaign": name, "Metric": LABEL[m], "Value": fmt(m, s[name]), "Typical (median)": fmt(m, s.median()), "Score": round(float(z[name]), 1), "_m": m})
#         for a in sorted(R["anomalies"], key=lambda x: -abs(x["Score"]))[:4]:
#             hi = a["Score"] > 0
#             add("anomaly", "Anomalies", f"{a['Campaign']}: unusually {'high' if hi else 'low'} {a['Metric']}",
#                 f"{a['Value']} vs typical {a['Typical (median)']} across campaigns. The available data cannot confirm the cause.", "High",
#                 "Investigate audience, offer, creative and tracking for this campaign." if not hi else "Identify what worked (audience/creative/offer) and test it elsewhere.")
#     eng = next((m for m in ("ctr", "open_rate") if m in camp), None)
#     if eng and "conversion_rate" in camp and len(camp) >= 8:  # engagement vs conversion mismatch
#         e, c = camp[eng], camp["conversion_rate"]
#         bad = camp[(e >= e.quantile(.75)) & (c <= c.quantile(.25))].index.tolist()
#         if bad: add("drop", "Conversion", f"High {LABEL[eng]} but low Conversion Rate in {len(bad)} campaign(s)",
#                     "Campaigns: " + ", ".join(map(str, bad[:5])) + ". Clicks/opens are not turning into conversions.", "High", ACTION["conversion_rate"])
#     if "revenue" in camp and len(camp) >= 3:
#         rv = camp["revenue"].dropna().sort_values(ascending=False); tot = rv.sum()
#         if tot > 0:
#             add("strong", "Revenue", f"Top campaign: {rv.index[0]} ({fmt('revenue', rv.iloc[0])})",
#                 f"Top 3 campaigns contribute {rv.head(3).sum() / tot * 100:.0f}% of total revenue ({fmt('revenue', tot)}).", "High",
#                 "Heavy revenue concentration — reduce dependence on a few campaigns." if rv.head(3).sum() / tot > .6 else "Replicate what worked in the top campaign.")
#     for d in info["dims"]:  # possible drivers (associations only)
#         for m in [x for x in ("conversion_rate", "ctr", "open_rate", "revenue") if x in df]:
#             g = df.groupby(d)[m].agg(["mean", "count"]); g = g[g["count"] >= 3]
#             if len(g) >= 2 and g["mean"].min() > 0:
#                 gap = (g["mean"].max() - g["mean"].min()) / g["mean"].min() * 100
#                 if gap >= 15: R["drivers"].append((gap, d, m, g["mean"].idxmax(), g["mean"].idxmin(), g))
#     for gap, d, m, hi, lo, g in sorted(R["drivers"], key=lambda x: -x[0])[:3]:
#         lab = "avg revenue per record" if m == "revenue" else LABEL[m]
#         add("driver", CAT[m], f"Possible driver: {d.replace('_', ' ')} — {hi} vs {lo}",
#             f"{hi} had {gap:.0f}% higher {lab} than {lo} in this dataset. Audience, creative and offer may also contribute; causation is not confirmed.",
#             "Medium" if g["count"].min() >= 5 else "Low", f"Run a controlled test on {d.replace('_', ' ')} to validate.")
#     order = {"anomaly": 0, "drop": 1, "driver": 3, "positive": 2, "strong": 4}
#     ins.sort(key=lambda i: order[i["kind"]])
#     return R


# def package(df, info, R):
#     """Aggregated, PII-free AI Analysis Package — the ONLY thing the AI layer sees."""
#     top = R["camp"].reset_index().round(2).sort_values("revenue" if "revenue" in R["camp"] else R["camp"].columns[0], ascending=False).head(60)
#     return json.dumps({"report": {"campaigns": info["campaigns"], "metrics": [LABEL[m] for m in info["metrics"]], "rows": len(df),
#                                   "period": R["periods"], "data_confidence": info["confidence"], "issues": info["issues"] + [f"Missing: {k}={v}" for k, v in info["missing"].items()]},
#                        "overall": {LABEL[k]: fmt(k, v) for k, v in R["overall"].items()},
#                        "changes": None if R["changes"] is None else R["changes"].round(2).reset_index().to_dict("records"),
#                        "insights": R["insights"], "anomalies": [{k: v for k, v in a.items() if k != "_m"} for a in R["anomalies"]],
#                        "campaign_table": top.to_dict("records")}, default=str, ensure_ascii=False)


# # ---------------- AI layer ----------------
# SYSTEM = """You are a senior CRM/marketing analyst. You receive a pre-computed, PII-free analysis package (JSON). Rules:
# 1. Use ONLY numbers present in the package. Never calculate new aggregates or invent values; if unsure, say the data is insufficient.
# 2. Separate clearly: **What the data shows** (facts) / **Possible explanation** (hypothesis, say "in this dataset", never claim causation) / **Not confirmable**.
# 3. Label every insight with confidence High/Medium/Low. Sum metrics: Sent, Delivered, Conversion, Revenue. Average metrics: Delivery Rate, Conversion Rate, ABV, IPT.
# 4. Be concise, plain-language, action-oriented. Recommend investigations/tests, not guaranteed outcomes."""


# MODELS = ["claude-sonnet-5-5", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"]


# def ask_ai(key, user, history=None):
#     """Only the API key is needed. Tries available models automatically until one works."""
#     try:
#         import anthropic
#     except ImportError:
#         return "⚠️ Please run: pip install anthropic"
#     client, last = anthropic.Anthropic(api_key=key), None
#     msgs = (history or []) + [{"role": "user", "content": user}]
#     for m in [st.session_state.get("model_ok")] + MODELS:
#         if not m: continue
#         try:
#             r = client.messages.create(model=m, max_tokens=1500, system=SYSTEM, messages=msgs)
#             st.session_state["model_ok"] = m
#             return "".join(b.text for b in r.content if b.type == "text")
#         except anthropic.AuthenticationError:
#             return "⚠️ Invalid API key. Please check the key in the sidebar."
#         except (anthropic.NotFoundError, anthropic.PermissionDeniedError, anthropic.BadRequestError) as e:
#             last = e; st.session_state["model_ok"] = None; continue
#         except Exception as e:
#             return f"⚠️ AI layer unavailable: {e}"
#     return f"⚠️ None of the models are available for this API key. Last error: {last}"


# KEYS = sorted([(k, m) for m, ks in {"revenue": ["revenue", "sales"], "sent": ["sent"], "delivered": ["delivered"], "conversion_rate": ["conversion rate", "cvr"],
#                "conversion": ["conversions", "conversion"], "delivery_rate": ["delivery rate"], "abv": ["abv", "order value"], "ipt": ["ipt", "items per"],
#                "ctr": ["ctr", "click"], "open_rate": ["open rate", "open"], "unsubscribe_rate": ["unsub"]}.items() for k in ks], key=lambda x: -len(x[0]))


# def rule_answer(q, R):
#     """Exact answers computed in Python for ranking questions (no AI guesswork)."""
#     ql, camp = q.lower(), R["camp"]
#     hits = [n for n in camp.index if str(n).lower() in ql]
#     hits = [n for n in hits if not any(n != o and str(n).lower() in str(o).lower() for o in hits)]
#     if hits and not re.search(r"highest|lowest|top|bottom|best|worst", ql):
#         t = camp.loc[hits].T; t.index = [LABEL[i] for i in t.index]; t.columns = [str(c) for c in t.columns]
#         return "Numbers for " + ", ".join(map(str, hits)) + ":", t
#     if re.search(r"investigat|attention|anomal|unusual", ql):
#         a = pd.DataFrame(R["anomalies"]).drop(columns="_m", errors="ignore")
#         return ("Campaigns flagged as statistical outliers:", a) if len(a) else ("No campaign is a clear outlier in this report.", None)
#     m = next((m for k, m in KEYS if k in ql and m in camp), None)
#     if m:
#         n = int(nm.group(1)) if (nm := re.search(r"top\s*(\d+)|bottom\s*(\d+)|(\d+)\s*(?:best|worst)", ql)) and any(nm.groups()) else (1 if not re.search(r"top|bottom|best|worst|rank", ql) else 5)
#         low = bool(re.search(r"lowest|worst|least|minimum|bottom|min\b", ql)); hi = bool(re.search(r"highest|top|best|most|maximum|max\b|biggest", ql))
#         if low or hi:
#             t = camp[[m]].dropna().sort_values(m, ascending=low).head(n)
#             t[LABEL[m]] = t[m].map(lambda v: fmt(m, v)); t = t[[LABEL[m]]]
#             return f"{'Lowest' if low else 'Highest'} {LABEL[m]} ({'sum' if m in SUM_M else 'average'} per campaign):", t
#     return None


# def kpi_cards(R):
#     ms = [m for m in SUM_M + AVG_M if m in R["overall"].index]
#     for i in range(0, len(ms), 4):
#         cols = st.columns(4)
#         for c, m in zip(cols, ms[i:i + 4]):
#             ch = None if R["changes"] is None or LABEL[m] not in R["changes"].index else R["changes"].loc[LABEL[m], "Change %"]
#             c.metric(("Σ " if m in SUM_M else "Ø ") + LABEL[m], fmt(m, R["overall"][m]), None if ch is None or pd.isna(ch) else f"{ch:+.1f}%",
#                      delta_color="inverse" if m in GOOD_DOWN else "normal")


# def sample():
#     rng = np.random.default_rng(7); rows = []
#     for i in range(40):
#         sent = int(rng.integers(20000, 150000)); dr = rng.uniform(88, 98); dl = int(sent * dr / 100)
#         d = pd.Timestamp("2026-09-01") + pd.Timedelta(days=int(rng.integers(0, 28)), hours=int(rng.choice([9, 13, 19])))
#         ctr = rng.uniform(2, 5) * (1.25 if d.hour == 19 else 1); cr = rng.uniform(1.2, 2.6)
#         if i == 16: cr *= .3
#         if i == 5: ctr *= 2.8
#         conv = int(dl * cr / 100); abv = rng.uniform(450, 900)
#         rows.append({"Campaign Name": f"Campaign {i + 1}", "Date": d, "Channel": rng.choice(["Email", "SMS", "Push"]), "Contact Email": f"user{i}@mail.com",
#                      "Sent": sent, "Delivered": dl, "Delivery Rate": round(dr, 2), "CTR": round(ctr, 2), "Conversion": conv,
#                      "Conversion Rate": round(cr, 2), "ABV": round(abv, 2), "IPT": round(rng.uniform(1.2, 3), 2), "Revenue": round(conv * abv)})
#     return pd.DataFrame(rows)


# # ---------------- UI ----------------
# st.set_page_config(page_title="AI Insights Generator", page_icon="📊", layout="wide")
# st.title("📊 AI Insights Generator Agent")
# st.caption("Upload a report → secure processing → verified numbers → AI explains what happened, why it might have happened, and what to check next.")
# if (pw := os.getenv("APP_PASSWORD")) and st.sidebar.text_input("Access password", type="password") != pw:
#     st.info("Enter the access password in the sidebar."); st.stop()

# with st.sidebar:
#     st.header("⚙️ Settings")
#     key = st.text_input("Anthropic API key (optional)", type="password", value=os.getenv("ANTHROPIC_API_KEY", ""),
#                         help="Without a key, the app still gives fully calculated insights; AI adds narrative + free-form Q&A.")
#     focus = st.multiselect("Analysis focus", ["Full Analysis", "Performance", "Engagement", "Conversion", "Revenue", "Anomalies"], default=["Full Analysis"])
#     st.markdown("**Aggregation rules**  \nΣ Sum: Sent, Delivered, Conversion, Revenue  \nØ Average: Delivery Rate, Conversion Rate, ABV, IPT (other rates averaged too)")
#     st.success("🔒 Privacy: PII removed locally. AI receives only aggregated data. Nothing is written to disk.")
#     if st.button("🗑️ Clear data & chat"): st.session_state.clear(); st.rerun()

# up = st.file_uploader("Step 1 — Upload your report (CSV / XLSX)", type=["csv", "xlsx", "xls"])
# c1, c2 = st.columns([1, 5])
# use_sample = c1.button("Try sample data")
# sheet = None
# if up is not None and up.name.lower().endswith((".xlsx", ".xls")):
#     sheets = pd.ExcelFile(up).sheet_names
#     sheet = st.selectbox("Sheet", sheets) if len(sheets) > 1 else sheets[0]; up.seek(0)
# if use_sample: st.session_state["raw"] = sample(); st.session_state["ai"] = None; st.session_state["chat"] = []
# if up is not None and st.session_state.get("fname") != (up.name, sheet):
#     st.session_state.update(raw=load(up, sheet), fname=(up.name, sheet), ai=None, chat=[])
# if "raw" not in st.session_state: st.info("👆 Upload a report or click **Try sample data**."); st.stop()

# _cols = [str(c).strip() for c in st.session_state["raw"].columns]
# _pick = st.sidebar.selectbox("Campaign name column", ["Auto-detect"] + _cols, help="Campaign names are always kept (never treated as PII).")
# df, info = secure_prepare(st.session_state["raw"], None if _pick == "Auto-detect" else _pick)
# if not info["has_campaign"]: st.warning("No campaign-name column found — pick it in the sidebar ('Campaign name column').")
# if not info["metrics"]: st.error("No recognised metric columns (Sent, Delivered, Conversion, Revenue, rates…). Please check column names."); st.stop()
# R = analyse(df, info)
# if st.button("✨ Step 3 — Generate Insights", type="primary") or st.session_state.get("ran"):
#     st.session_state["ran"] = True
# else: st.write(f"Detected **{len(df)} rows**, **{info['campaigns']} campaigns**, metrics: {', '.join(LABEL[m] for m in info['metrics'])}. Choose focus in the sidebar, then generate."); st.stop()

# wanted = None if "Full Analysis" in focus or not focus else set(focus)
# show = [i for i in R["insights"] if wanted is None or i["cat"] in wanted]
# pkg = package(df, info, R)
# tabs = st.tabs(["🧭 Overview", "💡 Insights", "📈 Trends", "🚨 Anomalies", "⚖️ Compare", "💬 Ask Your Data", "⬇️ Export", "🔎 Campaign Search"])

# with tabs[0]:
#     st.subheader("Data understanding & quality")
#     a, b, c, d = st.columns(4)
#     a.metric("Campaigns", info["campaigns"]); b.metric("Complete records", f"{info['complete_pct']}%")
#     c.metric("Duplicates removed", info["duplicates"]); d.metric("Insight confidence", info["confidence"])
#     if info["has_date"]: st.write(f"📅 Date range: **{df['date'].min():%d %b %Y} → {df['date'].max():%d %b %Y}**" + (f" · comparing {R['periods']}" if R["periods"] else " · not enough dates for period comparison"))
#     else: st.warning("No date column found — trends and previous-period comparison are unavailable.")
#     for k, v in info["missing"].items(): st.warning(f"Missing values: {k} ({v} rows)")
#     for i in info["issues"]: st.warning(i)
#     if info["pii_removed"]: st.success(f"🔒 Removed before analysis (never sent to AI): {', '.join(info['pii_removed'])}")
#     st.subheader("Key KPIs"); kpi_cards(R)
#     st.subheader("🧠 AI executive summary")
#     if key:
#         if st.session_state.get("ai") is None:
#             with st.spinner("AI is analysing the processed package…"):
#                 st.session_state["ai"] = ask_ai(key, "Write an executive summary: What happened, Why it might have happened, What to look at next. Max 200 words.\n\nPACKAGE:\n" + pkg)
#         st.markdown(st.session_state["ai"])
#     else:
#         top = show[:3]; st.markdown("\n".join(f"- **{i['title']}** — {i['detail']}" for i in top) or "No major changes detected.")
#         st.caption("Add an API key in the sidebar for AI-written narrative. Numbers above are already fully calculated.")

# with tabs[1]:
#     if not show: st.info("No significant insights for the selected focus.")
#     icon = {"positive": "📈", "drop": "⚠️", "anomaly": "🚨", "strong": "🏆", "driver": "🔍"}
#     tag = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}
#     for i in show:
#         with st.container(border=True):
#             st.markdown(f"#### {icon[i['kind']]} {i['title']}")
#             st.markdown(f"**What the data shows:** {i['detail']}")
#             st.markdown(f"{tag[i['conf']]} **Confidence: {i['conf']}**" + (f"  \n➡️ **Next step:** {i['action']}" if i["action"] else ""))

# with tabs[2]:
#     if R["trend"] is None: st.info("Trends need a date column with at least 4 distinct days.")
#     else:
#         opts = [LABEL[m] for m in info["metrics"]]; sel = st.multiselect("Metrics", opts, default=opts[:1])
#         inv = {v: k for k, v in LABEL.items()}
#         for s in sel: st.markdown(f"**{s}** ({'sum' if inv[s] in SUM_M else 'average'} per day)"); st.line_chart(R["trend"][inv[s]])
#         st.subheader("Previous vs current period"); st.dataframe(R["changes"].style.format("{:,.2f}"), use_container_width=True)

# with tabs[3]:
#     if not R["anomalies"]: st.success("No clear outliers found.")
#     else:
#         st.caption("Outliers vs other campaigns (robust z-score > 3.5). Points to where to investigate; does not explain why.")
#         st.dataframe(pd.DataFrame(R["anomalies"]).drop(columns="_m").sort_values("Score", key=abs, ascending=False), use_container_width=True, hide_index=True)
#     st.subheader("Campaign leaderboard")
#     sm = st.selectbox("Rank by", [LABEL[m] for m in R["camp"].columns], key="rank")
#     col = {v: k for k, v in LABEL.items()}[sm]; st.bar_chart(R["camp"][col].sort_values(ascending=False).head(15))

# with tabs[4]:
#     names = sorted(R["camp"].index.astype(str)); x, y = st.columns(2)
#     A, B = x.selectbox("Campaign A", names, 0), y.selectbox("Campaign B", names, min(1, len(names) - 1))
#     cc = R["camp"].copy(); cc.index = cc.index.astype(str)
#     t = pd.DataFrame({A: cc.loc[A], B: cc.loc[B]}); t["Diff %"] = [pct(b, a) for a, b in zip(t[A], t[B])]
#     t.index = [LABEL[i] for i in t.index]; st.dataframe(t.style.format("{:,.2f}"), use_container_width=True)
#     big = t["Diff %"].abs().sort_values(ascending=False).dropna().head(3)
#     for k in big.index: st.write(f"• **{k}**: {B} is {t.loc[k, 'Diff %']:+.1f}% vs {A}")

# with tabs[5]:
#     st.caption("Try: *Which campaign generated the highest revenue?* · *Top 5 by conversion rate* · *Which campaigns need investigation?*")
#     hist = st.session_state.setdefault("chat", [])
#     for h in hist:
#         with st.chat_message(h["role"]): st.markdown(h["content"])
#     if q := st.chat_input("Ask about your report…"):
#         hist.append({"role": "user", "content": q})
#         with st.chat_message("user"): st.markdown(q)
#         with st.chat_message("assistant"):
#             ra = rule_answer(q, R)
#             if ra:
#                 st.markdown(ra[0] + "  \n*(calculated directly from your data)*")
#                 if ra[1] is not None: st.dataframe(ra[1])
#                 ans = ra[0] + (("\n\n" + ra[1].to_markdown()) if ra[1] is not None else "")
#             elif key:
#                 ans = ask_ai(key, f"PACKAGE:\n{pkg}\n\nQUESTION: {q}", [{"role": h["role"], "content": h["content"]} for h in hist[-7:-1]]); st.markdown(ans)
#             else: ans = "I can answer ranking/anomaly questions without AI (e.g. *highest revenue campaign*). For open-ended questions add an API key in the sidebar."; st.markdown(ans)
#         hist.append({"role": "assistant", "content": ans})

# with tabs[6]:
#     md = ["# Insights Report", f"Campaigns: {info['campaigns']} · Confidence: {info['confidence']}", "", "## KPIs"] + [f"- {LABEL[k]}: {fmt(k, v)}" for k, v in R["overall"].items()] + ["", "## Insights"]
#     for i in show: md += [f"### {i['title']}", i["detail"], f"Confidence: {i['conf']}", f"Next step: {i['action']}" if i["action"] else "", ""]
#     if st.session_state.get("ai"): md += ["## AI Summary", st.session_state["ai"]]
#     st.download_button("Download report (.md)", "\n".join(md), "insights_report.md")
#     st.download_button("Download campaign-level summary (.csv, PII-free)", R["camp"].round(2).to_csv(), "campaign_summary.csv")
#     with st.expander("Preview: exactly what the AI receives"): st.code(pkg[:4000], language="json")

# with tabs[7]:
#     st.caption("Search by campaign name (partial match, not case-sensitive). Names are kept exactly as in your report.")
#     qs = st.text_input("Campaign name", placeholder="e.g. Diwali, Cart, Campaign 17")
#     ct = R["camp"].copy(); ct.index = ct.index.astype(str)
#     hit = ct[ct.index.str.contains(qs, case=False, regex=False)] if qs else ct
#     st.write(f"{len(hit)} of {len(ct)} campaigns")
#     st.dataframe(hit.rename(columns=LABEL).round(2), use_container_width=True)
#     if qs and len(hit) == 1 and info["has_date"]:
#         one = df[df["campaign"].astype(str) == hit.index[0]]
#         st.markdown(f"**Daily view: {hit.index[0]}**"); st.dataframe(one.drop(columns=["weekday", "send_hour"], errors="ignore"), use_container_width=True, hide_index=True)



"""AI Insights Generator Agent — Python + Streamlit.
Principle (per BRD): Python calculates & validates, AI only explains. Raw data never reaches the AI.
Run:  pip install -r requirements.txt  &&  streamlit run app.py
"""
import io, json, os, re
import numpy as np
import pandas as pd
import streamlit as st

# ---------------- Metric rules (as defined for our reports) ----------------
SUM_M = ["sent", "delivered", "conversion", "revenue"]
AVG_M = ["delivery_rate", "conversion_rate", "abv", "ipt", "open_rate", "ctr", "unsubscribe_rate"]
LABEL = {"sent": "Sent", "delivered": "Delivered", "conversion": "Conversion", "revenue": "Revenue",
         "delivery_rate": "Delivery Rate", "conversion_rate": "Conversion Rate", "abv": "ABV", "ipt": "IPT",
         "open_rate": "Open Rate", "ctr": "CTR", "unsubscribe_rate": "Unsubscribe Rate"}
RATES = {"delivery_rate", "conversion_rate", "open_rate", "ctr", "unsubscribe_rate"}
CAT = {"sent": "Performance", "delivered": "Performance", "delivery_rate": "Performance", "open_rate": "Engagement",
       "ctr": "Engagement", "unsubscribe_rate": "Engagement", "conversion": "Conversion",
       "conversion_rate": "Conversion", "revenue": "Revenue", "abv": "Revenue", "ipt": "Revenue"}
ALIAS = {"sent": ["sent", "messagessent", "totalsent"], "delivered": ["delivered", "totaldelivered"],
         "conversion": ["conversion", "conversions", "converted", "totalconversions"],
         "revenue": ["revenue", "totalrevenue", "sales", "gmv"],
         "delivery_rate": ["deliveryrate", "delivery", "deliveredrate"],
         "conversion_rate": ["conversionrate", "cvr", "convrate"], "abv": ["abv", "averageordervalue", "aov"],
         "ipt": ["ipt", "itemsperTransaction".lower(), "itemspertransaction"],
         "open_rate": ["openrate", "or"], "ctr": ["ctr", "clickthroughrate", "clickrate"],
         "unsubscribe_rate": ["unsubscriberate", "unsubrate", "unsubscribe"]}
GOOD_DOWN = {"unsubscribe_rate"}
KNOWN = set(SUM_M + AVG_M)
MONEY = {"revenue", "abv"}
ACTION = {"conversion_rate": "Review landing page, offer and post-click journey; compare with higher-converting campaigns.",
          "conversion": "Check the conversion funnel and audience quality for the affected campaigns.",
          "revenue": "Break revenue down by campaign/segment to find where the change came from.",
          "ctr": "Review creative, subject line/CTA and send timing; run an A/B test.",
          "open_rate": "Test subject lines and send time; check sender reputation.",
          "delivery_rate": "Check list hygiene, sender/DLT setup and provider delivery reports.",
          "abv": "Review offer/discount structure and product mix.", "ipt": "Test bundles and cross-sell recommendations.",
          "unsubscribe_rate": "Review frequency and relevance; consider segment-level throttling.",
          "sent": "Confirm whether the volume change was planned.", "delivered": "Verify delivery pipeline and volume plan."}
PII_NAME = re.compile(r"(customer|user|client|first|last|full|contact)\s*name$|e-?mail|phone|mobile|msisdn|address|"
                      r"\bip\b|(customer|user|order|device|subscriber|cust)\s*id$|imei|aadhaar|\bpan\b|dob|birth")
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
PHONE = re.compile(r"^\+?\d[\d\s\-]{8,14}$")


def norm(c): return re.sub(r"[^a-z0-9]", "", str(c).lower())


def fmt(m, v):
    if v is None or pd.isna(v): return "n/a"
    if m in RATES: return f"{v:.2f}%"
    if m in MONEY:
        if m in SUM_M and abs(v) >= 1e7: return f"₹{v / 1e7:.2f}Cr"
        if m in SUM_M and abs(v) >= 1e5: return f"₹{v / 1e5:.2f}L"
        return f"₹{v:,.0f}" if m in SUM_M else f"₹{v:,.2f}"
    if m in SUM_M: return f"{v:,.0f}" if abs(v) >= 1000 or float(v).is_integer() else f"{v:,.2f}"
    return f"{v:,.2f}"


def to_num(s):
    if s.dtype.kind in "iuf": return s.astype(float)
    return pd.to_numeric(s.astype(str).str.replace(r"[₹$,%\s]", "", regex=True), errors="coerce")


# ---------------- Secure processing layer ----------------
def load(file, sheet=None):
    if file.name.lower().endswith((".xlsx", ".xls")): return pd.read_excel(file, sheet_name=sheet or 0)
    return pd.read_csv(file)


def find_campaign(df, mapping):
    cols = [c for c in df.columns if c not in mapping]
    for c in cols:
        if norm(c) in ("campaignname", "campaign", "campaigntitle", "name", "journeyname", "flowname"): return c
    for c in cols:
        n = norm(c)
        if any(k in n for k in ("campaign", "journey", "flow")) and not n.endswith("id") and "date" not in n: return c
    return None


def is_pii(df, c):
    if PII_NAME.search(re.sub(r"[_\-]", " ", str(c).lower())): return True
    if not pd.api.types.is_numeric_dtype(df[c]):
        v = df[c].dropna().astype(str).head(200)
        return len(v) > 0 and (v.str.match(EMAIL).mean() > .3 or v.str.match(PHONE).mean() > .3)
    return False


def find_date(df, mapping, camp):
    import warnings
    cols = [c for c in df.columns if c not in mapping and c != camp]
    cols.sort(key=lambda c: not any(k in norm(c) for k in ("date", "time", "day", "month", "period")))
    for c in cols:
        if pd.api.types.is_datetime64_any_dtype(df[c]): return c
        if pd.api.types.is_numeric_dtype(df[c]): continue
        v = df[c].dropna().astype(str).head(200)
        if len(v) < 2 or v.str.contains(r"[-/:]|[A-Za-z]{3}").mean() < .8: continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore"); ok = pd.to_datetime(v, errors="coerce", dayfirst=True).notna().mean()
        if ok >= .8: return c
    return None


def auto_metrics(df, info, ov):
    """Schema-agnostic: any numeric column becomes a metric; Sum vs Average inferred from name + values (editable by user)."""
    info["auto_agg"], info["ignored"], info["notes"] = {}, [], []
    for m in info["metrics"]: info["auto_agg"][m] = "sum" if m in SUM_M else "avg"
    for c in list(df.columns):
        if c in ("campaign", "date") or c in info["metrics"]: continue
        v = df[c]
        if pd.api.types.is_datetime64_any_dtype(v): continue
        if not pd.api.types.is_numeric_dtype(v):
            n = to_num(v)
            if v.notna().sum() == 0 or n.notna().sum() / v.notna().sum() < .9: continue
            v = n
        low, tok = c.lower(), set(re.split(r"[^a-z%]+", c.lower()))
        if v.notna().sum() == 0 or re.search(r"(^|[\s_\-])(id|no|num|number|code|pin|zip|pincode)$", low) or re.search(r"[a-z]Id$", c):
            df = df.drop(columns=c); info["ignored"].append(c); continue
        df[c] = v.astype(float); nn = df[c].dropna()
        rate = any(k in low for k in ("rate", "pct", "percent", "%")) or bool(tok & {"ctr", "cvr"})
        avg = rate or any(k in low for k in ("avg", "average", "mean", "ratio", "score", "rating", "price", "roas", "duration", "share")) or bool(tok & {"per", "cpc", "cpm", "cpa", "cac", "ltv", "age", "nps", "abv", "aov", "ipt"})
        summ = any(k in low for k in ("total", "count", "revenue", "sales", "spend", "amount", "quantity", "volume", "booking", "conver", "impression", "install", "session")) or bool(tok & {"sent", "delivered", "clicks", "opens", "orders", "units", "qty", "users", "visits", "leads", "views", "cost"})
        integer = len(nn) > 0 and (nn % 1 == 0).all() and (nn >= 0).all()
        info["auto_agg"][c] = "avg" if avg else ("sum" if (summ or integer) else "avg")
        if rate:
            RATES.add(c)
            if 0 < nn.max() <= 1: df[c] = df[c] * 100
        if re.search(r"revenue|sales|amount|price|cost|spend|gmv|value|profit|income|fee|budget|cpc|cpm|cpa|cac|ltv|aov|abv", low): MONEY.add(c)
        if re.search(r"unsub|bounce|churn|cost|cpc|cpa|cpm|cac|complaint|refund|return|cancel|error|latency|defect|loss", low): GOOD_DOWN.add(c)
        LABEL[c] = c; info["metrics"].append(c)
        CAT[c] = ("Revenue" if c in MONEY else "Conversion" if re.search(r"conver|order|purchase|lead|install|booking", low) else
                  "Engagement" if re.search(r"click|open|ctr|view|impress|engage|unsub|session|visit", low) else
                  "Performance" if re.search(r"sent|deliver|reach|volume", low) else "Other")
    for m in list(info["metrics"]):  # apply user overrides + register aggregation rule
        for L in (SUM_M, AVG_M):
            if m in L: L.remove(m)
        o = ov.get(m)
        if o == "ignore": info["metrics"].remove(m); df = df.drop(columns=m); continue
        (SUM_M if (o if o in ("sum", "avg") else info["auto_agg"][m]) == "sum" else AVG_M).append(m)
    return df


def secure_prepare(raw, camp_col=None, ov=None):
    """Detect columns, remove PII, clean numbers, run quality checks. Returns (df, info)."""
    df = raw.copy(); df.columns = [str(c).strip() for c in df.columns]
    info = {"rows_raw": len(df), "pii_removed": [], "issues": [], "metrics": [], "dims": []}
    mapping = {}
    for c in df.columns:
        for m, al in ALIAS.items():
            if norm(c) in al and m not in mapping.values(): mapping[c] = m; break
    camp = camp_col if camp_col in df.columns else find_campaign(df, mapping)
    date = find_date(df, mapping, camp)
    if camp is None:  # generic fallback: most distinct text column that is not PII/date
        cand = [c for c in df.columns if c not in mapping and c != date and not pd.api.types.is_numeric_dtype(df[c]) and not is_pii(df, c) and 2 <= df[c].nunique() <= max(2, int(len(df) * .98))]
        camp = max(cand, key=lambda c: df[c].nunique()) if cand else None
    info["camp_name"], info["date_name"] = camp, date
    for c in list(df.columns):  # PII scan: column names + value patterns
        if c in mapping or c in (camp, date): continue
        if is_pii(df, c): info["pii_removed"].append(c); df = df.drop(columns=c)
    df = df.rename(columns=mapping)
    for m in [m for m in mapping.values()]:
        df[m] = to_num(df[m])
        if m in RATES and df[m].max() <= 1.0 and df[m].max() > 0: df[m] = df[m] * 100
    info["metrics"] = [m for m in SUM_M + AVG_M if m in df.columns]
    if camp: df = df.rename(columns={camp: "campaign"})
    if date:
        d = pd.to_datetime(df[date], errors="coerce", dayfirst=True)
        if d.notna().mean() > .6: df = df.drop(columns=date); df["date"] = d
    df = auto_metrics(df, info, ov or {})
    dup = int(df.duplicated().sum()); df = df.drop_duplicates()
    if "date" in df:
        df["weekday"] = df["date"].dt.day_name()
        if df["date"].dt.hour.nunique() > 1: df["send_hour"] = df["date"].dt.hour.astype(str)
    for c in df.columns:
        if c not in info["metrics"] + ["campaign", "date", "weekday", "send_hour"] and not pd.api.types.is_numeric_dtype(df[c]) \
                and not pd.api.types.is_datetime64_any_dtype(df[c]) and 2 <= df[c].nunique() <= 15 and df[c].nunique() < len(df):
            info["dims"].append(c)
    info["dims"] += [c for c in ("weekday", "send_hour") if c in df and 2 <= df[c].nunique() <= 24]
    mets = df[info["metrics"]]
    info["complete_pct"] = round(100 * mets.notna().all(axis=1).mean(), 1) if len(df) else 0
    miss = mets.isna().sum(); info["missing"] = {LABEL[k]: int(v) for k, v in miss.items() if v}
    info["duplicates"] = dup
    for m in info["metrics"]:
        if df[m].nunique(dropna=True) <= 1: info["notes"].append(f"'{LABEL[m]}' has the same value in every row, so there is nothing to compare.")
    if len(df) < 10: info["notes"].append("Very small dataset — treat findings as indicative only.")
    if info["ignored"]: info["notes"].append("Ignored as identifiers/empty: " + ", ".join(info["ignored"]))
    for m in info["metrics"]:
        if m in KNOWN and (df[m] < 0).any(): info["issues"].append(f"Negative values in {LABEL[m]}")
        if m in RATES and m in KNOWN and (df[m] > 100).any(): info["issues"].append(f"{LABEL[m]} above 100% in some rows")
    if {"sent", "delivered"} <= set(df.columns) and (df["delivered"] > df["sent"]).any():
        info["issues"].append(f"Delivered > Sent in {int((df['delivered'] > df['sent']).sum())} rows")
    if "conversion_rate" not in df and {"conversion", "delivered"} <= set(df.columns):
        info["issues"].append("Conversion Rate column not found — not derived, to follow your averaging rule.")
    info["has_date"], info["has_campaign"] = "date" in df, "campaign" in df
    if not info["has_campaign"]: df["campaign"] = ["Row " + str(i + 1) for i in range(len(df))]
    n = df["campaign"].nunique()
    info["campaigns"] = n
    ok = info["complete_pct"] >= 95 and not info["issues"] and n >= 10 and info["has_date"]
    info["confidence"] = "High" if ok else ("Low" if info["complete_pct"] < 80 or n < 3 else "Medium")
    rl = ([{"Column": info["camp_name"], "Role": "Name / item", "Aggregation": "-"}] if info["has_campaign"] else []) + \
         ([{"Column": info["date_name"], "Role": "Date", "Aggregation": "-"}] if info["has_date"] else [])
    rl += [{"Column": LABEL[m], "Role": "Metric", "Aggregation": "sum" if m in SUM_M else "avg"} for m in info["metrics"]]
    rl += [{"Column": c, "Role": "Dimension", "Aggregation": "-"} for c in info["dims"] if c not in ("weekday", "send_hour")]
    rl += [{"Column": c, "Role": "Removed (PII)", "Aggregation": "-"} for c in info["pii_removed"]]
    info["roles"] = rl
    return df, info


def agg(df, by=None):
    """Team rule: Sum -> Sent, Delivered, Conversion, Revenue | Average -> Delivery Rate, Conversion Rate, ABV, IPT (+other rates)."""
    cols = {m: ("sum" if m in SUM_M else "mean") for m in SUM_M + AVG_M if m in df.columns}
    if by is None: return pd.Series({m: (df[m].sum(min_count=1) if f == "sum" else df[m].mean()) for m, f in cols.items()})
    return df.groupby(by).agg(cols)


def pct(a, b): return np.nan if (a is None or pd.isna(a) or a == 0 or pd.isna(b)) else (b - a) / abs(a) * 100


def rz(s):
    med = s.median(); mad = (s - med).abs().median()
    if mad == 0: sd = s.std(); return (s - med) / sd if sd else s * 0
    return 0.6745 * (s - med) / mad


# ---------------- Analytics engine (deterministic) ----------------
def analyse(df, info):
    R = {"overall": agg(df), "camp": agg(df, "campaign"), "changes": None, "periods": None, "trend": None,
         "anomalies": [], "insights": [], "drivers": []}
    M, camp, ins = info["metrics"], None, R["insights"]; camp = R["camp"]

    def add(kind, cat, title, detail, conf, action=""): ins.append(dict(kind=kind, cat=cat, title=title, detail=detail, conf=conf, action=action))

    if info["has_date"] and df["date"].dt.normalize().nunique() >= 4:  # previous vs current period
        days = sorted(df["date"].dt.normalize().unique()); h = len(days) // 2
        prev, cur = df[df["date"].dt.normalize().isin(days[:h])], df[df["date"].dt.normalize().isin(days[h:])]
        pa, ca = agg(prev), agg(cur)
        R["periods"] = f"{pd.Timestamp(days[0]):%d %b}–{pd.Timestamp(days[h - 1]):%d %b} vs {pd.Timestamp(days[h]):%d %b}–{pd.Timestamp(days[-1]):%d %b}"
        R["changes"] = pd.DataFrame({"Previous": pa, "Current": ca, "Change %": [pct(pa[m], ca[m]) for m in pa.index]}).rename(index=LABEL)
        R["trend"] = df.groupby(df["date"].dt.normalize()).apply(agg)
        ch = sorted([(m, pct(pa[m], ca[m])) for m in pa.index if not pd.isna(pct(pa[m], ca[m])) and abs(pct(pa[m], ca[m])) >= 5], key=lambda x: -abs(x[1]))[:6]
        for m, c in ch:
            good = (c > 0) != (m in GOOD_DOWN)
            add("positive" if good else "drop", CAT[m], f"{LABEL[m]} {'up' if c > 0 else 'down'} {abs(c):.1f}%",
                f"{fmt(m, pa[m])} → {fmt(m, ca[m])} ({R['periods']}).", "High" if len(days) >= 6 else "Medium", "" if good else ACTION.get(m, "Investigate which campaigns/segments drive this change."))
    if len(camp) >= 5:  # anomalies (robust z-score > 3.5 vs other campaigns)
        for m in [x for x in M if x in camp]:
            s = camp[m].dropna()
            if len(s) < 5: continue
            z = rz(s)
            for name in z[abs(z) > 3.5].index:
                R["anomalies"].append({"Campaign": name, "Metric": LABEL[m], "Value": fmt(m, s[name]), "Typical (median)": fmt(m, s.median()), "Score": round(float(z[name]), 1), "_m": m})
        for a in sorted(R["anomalies"], key=lambda x: -abs(x["Score"]))[:4]:
            hi = a["Score"] > 0
            add("anomaly", "Anomalies", f"{a['Campaign']}: unusually {'high' if hi else 'low'} {a['Metric']}",
                f"{a['Value']} vs typical {a['Typical (median)']} across campaigns. The available data cannot confirm the cause.", "High",
                "Investigate audience, offer, creative and tracking for this campaign." if not hi else "Identify what worked (audience/creative/offer) and test it elsewhere.")
    eng = next((m for m in ("ctr", "open_rate") if m in camp), None)
    if eng and "conversion_rate" in camp and len(camp) >= 8:  # engagement vs conversion mismatch
        e, c = camp[eng], camp["conversion_rate"]
        bad = camp[(e >= e.quantile(.75)) & (c <= c.quantile(.25))].index.tolist()
        if bad: add("drop", "Conversion", f"High {LABEL[eng]} but low Conversion Rate in {len(bad)} campaign(s)",
                    "Campaigns: " + ", ".join(map(str, bad[:5])) + ". Clicks/opens are not turning into conversions.", "High", ACTION["conversion_rate"])
    pm = next((m for m in ["revenue"] + SUM_M + M if m in camp), None)
    if pm and len(camp) >= 3:
        rv = camp[pm].dropna().sort_values(ascending=False); tot = rv.sum()
        if pm in SUM_M and tot > 0:
            add("strong", CAT[pm], f"Top by {LABEL[pm]}: {rv.index[0]} ({fmt(pm, rv.iloc[0])})",
                f"Top 3 contribute {rv.head(3).sum() / tot * 100:.0f}% of total {LABEL[pm]} ({fmt(pm, tot)}); lowest is {rv.index[-1]} ({fmt(pm, rv.iloc[-1])}).", "High",
                "Heavy concentration — reduce dependence on a few items." if rv.head(3).sum() / tot > .6 else "Replicate what worked in the top performer.")
        elif len(rv) >= 2:
            add("strong", CAT[pm], f"Best {LABEL[pm]}: {rv.index[0]} ({fmt(pm, rv.iloc[0])})", f"Lowest is {rv.index[-1]} ({fmt(pm, rv.iloc[-1])}); median {fmt(pm, rv.median())}.", "High", "")
    for d in info["dims"]:  # possible drivers (associations only)
        for m in M[:8]:
            g = df.groupby(d)[m].agg(["mean", "count"]); g = g[g["count"] >= 3]
            if len(g) >= 2 and g["mean"].min() > 0:
                gap = (g["mean"].max() - g["mean"].min()) / g["mean"].min() * 100
                if gap >= 15: R["drivers"].append((gap, d, m, g["mean"].idxmax(), g["mean"].idxmin(), g))
    for gap, d, m, hi, lo, g in sorted(R["drivers"], key=lambda x: -x[0])[:3]:
        lab = f"avg {LABEL[m]} per record" if m in SUM_M else LABEL[m]
        add("driver", CAT[m], f"Possible driver: {d.replace('_', ' ')} — {hi} vs {lo}",
            f"{hi} had {gap:.0f}% higher {lab} than {lo} in this dataset. Audience, creative and offer may also contribute; causation is not confirmed.",
            "Medium" if g["count"].min() >= 5 else "Low", f"Run a controlled test on {d.replace('_', ' ')} to validate.")
    cols = [m for m in M if m in camp and camp[m].nunique() > 2]
    if len(camp) >= 8 and len(cols) >= 2:
        cm = camp[cols].corr()
        pr = [(abs(cm.loc[a, b]), a, b, cm.loc[a, b]) for i, a in enumerate(cols) for b in cols[i + 1:] if 0.7 <= abs(cm.loc[a, b]) < 0.98]
        for _, a, b, r in sorted(pr, reverse=True)[:2]:
            add("driver", "Other", f"Relationship: {LABEL[a]} and {LABEL[b]} move {'together' if r > 0 else 'in opposite directions'}",
                f"Correlation {r:.2f} across {len(camp)} items. Correlation does not prove causation.", "Medium" if abs(r) >= .85 and len(camp) >= 15 else "Low",
                "Validate with a segment-level check or a controlled test.")
    order = {"anomaly": 0, "drop": 1, "driver": 3, "positive": 2, "strong": 4}
    ins.sort(key=lambda i: order[i["kind"]])
    return R


def package(df, info, R, budget=None):
    """Aggregated, PII-free AI Analysis Package — the ONLY thing the AI layer sees.
    budget=None -> full package. budget=<chars> -> shrinks step by step so big real-world reports still fit small-model limits (Groq)."""
    camp = R["camp"]; key = "revenue" if "revenue" in camp else camp.columns[0]
    ct = camp.reset_index().sort_values(key, ascending=False)
    chg = None if R["changes"] is None else R["changes"].reindex(R["changes"]["Change %"].abs().sort_values(ascending=False).index)

    def mk(n, ni, nc, ch, nm=99):
        tbl = ct[[ct.columns[0]] + list(camp.columns[:nc])].head(n).round(2).to_dict("records") if n else []
        return json.dumps({"report": {"campaigns": info["campaigns"], "n_metrics": len(info["metrics"]), "rows": len(df),
                                      "period": R["periods"], "data_confidence": info["confidence"], "issues": (info["issues"] + [f"Missing: {k}={v}" for k, v in info["missing"].items()])[:6]},
                           "overall": {LABEL[k]: fmt(k, v) for k, v in list(R["overall"].items())[:nm]},
                           "aggregation": {LABEL[m]: ("sum" if m in SUM_M else "average") for m in info["metrics"][:nm]},
                           "changes": None if chg is None else chg.round(2).reset_index().head(ch).to_dict("records"),
                           "insights": [{**i, "detail": i["detail"][:160]} for i in R["insights"][:ni]],
                           "anomalies": [{k: v for k, v in a.items() if k != "_m"} for a in R["anomalies"][:8]],
                           "campaign_table": tbl}, default=str, ensure_ascii=False)
    if budget is None: return mk(60, 99, 99, 99)
    for lv in [(15, 10, 99, 12, 99), (10, 6, 8, 8, 20), (6, 5, 5, 6, 12), (0, 4, 0, 4, 8)]:
        out = mk(*lv)
        if len(out) <= budget: return out
    return out


# ---------------- AI layer ----------------
SYSTEM = """You are a senior data & business analyst (marketing, sales, operations, finance or any other report). You receive a pre-computed, PII-free analysis package (JSON). Rules:
1. Use ONLY numbers present in the package. Never calculate new aggregates or invent values; if unsure, say the data is insufficient.
2. Separate clearly: **What the data shows** (facts) / **Possible explanation** (hypothesis, say "in this dataset", never claim causation) / **Not confirmable**.
3. Label every insight with confidence High/Medium/Low. Each metric's aggregation (sum or average) is given in the package's 'aggregation' field; respect it.
4. Be concise, plain-language, action-oriented. Recommend investigations/tests, not guaranteed outcomes."""


MODELS = ["claude-sonnet-5-5", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"]


def ask_claude(key, user, history=None):
    """Only the API key is needed. Tries available models automatically until one works."""
    try:
        import anthropic
    except ImportError:
        return "⚠️ Please run: pip install anthropic"
    client, last = anthropic.Anthropic(api_key=key), None
    msgs = (history or []) + [{"role": "user", "content": user}]
    for m in [st.session_state.get("model_ok")] + MODELS:
        if not m: continue
        try:
            r = client.messages.create(model=m, max_tokens=1500, system=SYSTEM, messages=msgs)
            st.session_state["model_ok"] = m
            return "".join(b.text for b in r.content if b.type == "text")
        except anthropic.AuthenticationError:
            return "⚠️ Invalid API key. Please check the key in the sidebar."
        except (anthropic.NotFoundError, anthropic.PermissionDeniedError, anthropic.BadRequestError) as e:
            last = e; st.session_state["model_ok"] = None; continue
        except Exception as e:
            return f"⚠️ AI layer unavailable: {e}"
    return f"⚠️ None of the models are available for this API key. Last error: {last}"


SUMMARY_PROMPT = """Write an executive summary in exactly this format (max 300 words, plain language, use exact numbers and names from the package):
**Headline:** one sentence with the overall picture.
**What happened:** 3-5 bullets — biggest changes, top/bottom performers, anomalies (with numbers and names).
**Why it might have happened:** 2-3 hypotheses, each labelled (Confidence: High/Medium/Low) and worded as 'in this dataset', never as proven cause.
**What to do next:** 3 specific actions/tests, each tied to a finding.
**Data caveats:** missing data, small sample or anything that limits the conclusions.

PACKAGE:
"""


def groq_models(key):
    """Ask Groq which chat models THIS key can use (names change over time), best ones first."""
    import requests
    r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    if r.status_code != 200: return r.status_code, []
    bad = ("whisper", "tts", "guard", "orpheus", "embed", "playai", "safeguard", "allam")
    ms = [m for m in r.json().get("data", []) if m.get("active", True) and not any(x in m["id"].lower() for x in bad)]

    def size(m):  # generic: prefer bigger models (parameter count in id, e.g. "70b"), then longer context — no model names used
        z = re.search(r"(\d+(?:\.\d+)?)b", m["id"].lower())
        return (-(float(z.group(1)) if z else 0), -(m.get("context_window") or 0))
    return 200, [m["id"] for m in sorted(ms, key=size)]


def ask_groq(key, user, history=None):
    """Groq (OpenAI-compatible). Only the key is needed — available models are fetched automatically."""
    import requests
    if not st.session_state.get("groq_list") or st.session_state.get("groq_key") != key:
        try: code, lst = groq_models(key)
        except Exception as e: return f"⚠️ Could not reach Groq: {e}"
        if code == 401: return "⚠️ Invalid Groq API key. Please check the key in the sidebar."
        if not lst: return f"⚠️ Could not get the model list from Groq (status {code}). Check the key/network and press Regenerate."
        st.session_state["groq_list"], st.session_state["groq_key"] = lst, key
    msgs = [{"role": "system", "content": SYSTEM}] + (history or []) + [{"role": "user", "content": user}]
    order = list(dict.fromkeys([st.session_state.get("groq_ok")] + st.session_state["groq_list"][:6])); errs = []
    for m in [x for x in order if x]:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                              json={"model": m, "messages": msgs, "temperature": 0, "max_tokens": 1000}, timeout=90)
        except Exception as e:
            return f"⚠️ Could not reach Groq: {e}"
        if r.status_code == 200:
            st.session_state["groq_ok"] = m
            return r.json()["choices"][0]["message"]["content"] or ""
        if r.status_code == 401: return "⚠️ Invalid Groq API key. Please check the key in the sidebar."
        errs.append(f"{m} → {r.status_code}"); st.session_state["groq_ok"] = None
    return "⚠️ Groq could not answer (" + "; ".join(errs) + "). If it says 429, wait a minute (free-tier limit) and press Regenerate."


def ask_ai(key, make, history=None):
    """make(pkg_json) -> prompt text. For Groq the package is shrunk automatically if the request is too large (413)."""
    pk = st.session_state["_pk"]
    if st.session_state.get("provider") == "Groq":
        hist = [{"role": h["role"], "content": h["content"][:800]} for h in (history or [])]
        for b in (6000, 3500, 1800):
            out = ask_groq(key, make(pk(b)), hist)
            if not (out.startswith("⚠️") and "413" in out): return out
        return out
    return ask_claude(key, make(pk()), history)


KEYS = sorted([(k, m) for m, ks in {"revenue": ["revenue", "sales"], "sent": ["sent"], "delivered": ["delivered"], "conversion_rate": ["conversion rate", "cvr"],
               "conversion": ["conversions", "conversion"], "delivery_rate": ["delivery rate"], "abv": ["abv", "order value"], "ipt": ["ipt", "items per"],
               "ctr": ["ctr", "click"], "open_rate": ["open rate", "open"], "unsubscribe_rate": ["unsub"]}.items() for k in ks], key=lambda x: -len(x[0]))


def rule_answer(q, R):
    """Exact answers computed in Python for ranking questions (no AI guesswork)."""
    ql, camp = q.lower(), R["camp"]
    hits = [n for n in camp.index if str(n).lower() in ql]
    hits = [n for n in hits if not any(n != o and str(n).lower() in str(o).lower() for o in hits)]
    if hits and not re.search(r"highest|lowest|top|bottom|best|worst", ql):
        t = camp.loc[hits].T; t.index = [LABEL[i] for i in t.index]; t.columns = [str(c) for c in t.columns]
        return "Numbers for " + ", ".join(map(str, hits)) + ":", t
    if re.search(r"investigat|attention|anomal|unusual", ql):
        a = pd.DataFrame(R["anomalies"]).drop(columns="_m", errors="ignore")
        return ("Campaigns flagged as statistical outliers:", a) if len(a) else ("No campaign is a clear outlier in this report.", None)
    m = next((c for c in sorted(camp.columns, key=lambda c: -len(str(LABEL.get(c, c)))) if str(LABEL.get(c, c)).lower() in ql), None) or \
        next((m for k, m in KEYS if k in ql and m in camp), None)
    if m:
        n = int(nm.group(1)) if (nm := re.search(r"top\s*(\d+)|bottom\s*(\d+)|(\d+)\s*(?:best|worst)", ql)) and any(nm.groups()) else (1 if not re.search(r"top|bottom|best|worst|rank", ql) else 5)
        low = bool(re.search(r"lowest|worst|least|minimum|bottom|min\b", ql)); hi = bool(re.search(r"highest|top|best|most|maximum|max\b|biggest", ql))
        if low or hi:
            t = camp[[m]].dropna().sort_values(m, ascending=low).head(n)
            t[LABEL[m]] = t[m].map(lambda v: fmt(m, v)); t = t[[LABEL[m]]]
            return f"{'Lowest' if low else 'Highest'} {LABEL[m]} ({'sum' if m in SUM_M else 'average'} per campaign):", t
    return None


def kpi_cards(R):
    ms = [m for m in SUM_M + AVG_M if m in R["overall"].index]
    for i in range(0, len(ms), 4):
        cols = st.columns(4)
        for c, m in zip(cols, ms[i:i + 4]):
            ch = None if R["changes"] is None or LABEL[m] not in R["changes"].index else R["changes"].loc[LABEL[m], "Change %"]
            c.metric(("Σ " if m in SUM_M else "Ø ") + LABEL[m], fmt(m, R["overall"][m]), None if ch is None or pd.isna(ch) else f"{ch:+.1f}%",
                     delta_color="inverse" if m in GOOD_DOWN else "normal")


def sample():
    rng = np.random.default_rng(7); rows = []
    for i in range(40):
        sent = int(rng.integers(20000, 150000)); dr = rng.uniform(88, 98); dl = int(sent * dr / 100)
        d = pd.Timestamp("2026-09-01") + pd.Timedelta(days=int(rng.integers(0, 28)), hours=int(rng.choice([9, 13, 19])))
        ctr = rng.uniform(2, 5) * (1.25 if d.hour == 19 else 1); cr = rng.uniform(1.2, 2.6)
        if i == 16: cr *= .3
        if i == 5: ctr *= 2.8
        conv = int(dl * cr / 100); abv = rng.uniform(450, 900)
        rows.append({"Campaign Name": f"Campaign {i + 1}", "Date": d, "Channel": rng.choice(["Email", "SMS", "Push"]), "Contact Email": f"user{i}@mail.com",
                     "Sent": sent, "Delivered": dl, "Delivery Rate": round(dr, 2), "CTR": round(ctr, 2), "Conversion": conv,
                     "Conversion Rate": round(cr, 2), "ABV": round(abv, 2), "IPT": round(rng.uniform(1.2, 3), 2), "Revenue": round(conv * abv)})
    return pd.DataFrame(rows)


# ---------------- UI ----------------
st.set_page_config(page_title="AI Insights Generator", page_icon="📊", layout="wide")
st.title("📊 AI Insights Generator Agent")
st.caption("Upload a report → secure processing → verified numbers → AI explains what happened, why it might have happened, and what to check next.")
if (pw := os.getenv("APP_PASSWORD")) and st.sidebar.text_input("Access password", type="password") != pw:
    st.info("Enter the access password in the sidebar."); st.stop()

with st.sidebar:
    st.header("⚙️ Settings")
    provider = st.radio("AI provider", ["Claude (Anthropic)", "Groq"], horizontal=True)
    st.session_state["provider"] = provider
    key = st.text_input(f"{provider.split()[0]} API key (optional)", type="password",
                        value=os.getenv("GROQ_API_KEY" if provider == "Groq" else "ANTHROPIC_API_KEY", ""),
                        help="Only the key is needed — the model is chosen automatically. Without a key you still get all calculated insights; AI adds narrative + free-form Q&A.")
    focus = st.multiselect("Analysis focus", ["Full Analysis", "Performance", "Engagement", "Conversion", "Revenue", "Anomalies", "Other"], default=["Full Analysis"])
    st.markdown("**Aggregation rules**  \nΣ Sum: Sent, Delivered, Conversion, Revenue  \nØ Average: Delivery Rate, Conversion Rate, ABV, IPT  \nAny other numeric column is auto-classified (editable in Overview → “How I understood your report”).")
    st.success("🔒 Privacy: PII removed locally. AI receives only aggregated data. Nothing is written to disk.")
    if st.button("🗑️ Clear data & chat"): st.session_state.clear(); st.rerun()

up = st.file_uploader("Step 1 — Upload your report (CSV / XLSX)", type=["csv", "xlsx", "xls"])
c1, c2, c3, _ = st.columns([1, 1.3, 1.3, 3])
use_sample = c1.button("Try sample data")
_sm = sample(); _xb = io.BytesIO()
with pd.ExcelWriter(_xb, engine="openpyxl") as _w: _sm.to_excel(_w, index=False, sheet_name="Sample")
c2.download_button("⬇️ Sample file (CSV)", _sm.to_csv(index=False).encode("utf-8-sig"), "sample_campaign_report.csv", mime="text/csv")
c3.download_button("⬇️ Sample file (Excel)", _xb.getvalue(), "sample_campaign_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
sheet = None
if up is not None and up.name.lower().endswith((".xlsx", ".xls")):
    sheets = pd.ExcelFile(up).sheet_names
    sheet = st.selectbox("Sheet", sheets) if len(sheets) > 1 else sheets[0]; up.seek(0)
if use_sample: st.session_state["raw"] = sample(); st.session_state["ai"] = None; st.session_state["chat"] = []; st.session_state["agg_override"] = {}
if up is not None and st.session_state.get("fname") != (up.name, sheet):
    st.session_state.update(raw=load(up, sheet), fname=(up.name, sheet), ai=None, chat=[], agg_override={})
if "raw" not in st.session_state: st.info("👆 Upload a report or click **Try sample data**."); st.stop()

_cols = [str(c).strip() for c in st.session_state["raw"].columns]
_pick = st.sidebar.selectbox("Campaign name column", ["Auto-detect"] + _cols, help="Campaign names are always kept (never treated as PII).")
df, info = secure_prepare(st.session_state["raw"], None if _pick == "Auto-detect" else _pick, st.session_state.get("agg_override", {}))
if not info["has_campaign"]: st.warning("No campaign-name column found — pick it in the sidebar ('Campaign name column').")
if not info["metrics"]: st.error("No numeric columns found in this report, so there is nothing to calculate. Please check the file / sheet."); st.stop()
R = analyse(df, info)
if st.button("✨ Step 3 — Generate Insights", type="primary") or st.session_state.get("ran"):
    st.session_state["ran"] = True
else: st.write(f"Detected **{len(df)} rows**, **{info['campaigns']} campaigns**, metrics: {', '.join(LABEL[m] for m in info['metrics'])}. Choose focus in the sidebar, then generate."); st.stop()

wanted = None if "Full Analysis" in focus or not focus else set(focus)
show = [i for i in R["insights"] if wanted is None or i["cat"] in wanted]
st.session_state["_pk"] = lambda budget=None: package(df, info, R, budget)
pkg = st.session_state["_pk"](6000 if provider == "Groq" else None)  # preview of what the AI receives
tabs = st.tabs(["🧭 Overview", "💡 Insights", "📈 Trends", "🚨 Anomalies", "⚖️ Compare", "💬 Ask Your Data", "⬇️ Export", "🔎 Campaign Search"])

with tabs[0]:
    st.subheader("Data understanding & quality")
    a, b, c, d = st.columns(4)
    a.metric("Campaigns", info["campaigns"]); b.metric("Complete records", f"{info['complete_pct']}%")
    c.metric("Duplicates removed", info["duplicates"]); d.metric("Insight confidence", info["confidence"])
    if info["has_date"]: st.write(f"📅 Date range: **{df['date'].min():%d %b %Y} → {df['date'].max():%d %b %Y}**" + (f" · comparing {R['periods']}" if R["periods"] else " · not enough dates for period comparison"))
    else: st.warning("No date column found — trends and previous-period comparison are unavailable.")
    for k, v in info["missing"].items(): st.warning(f"Missing values: {k} ({v} rows)")
    for i in info["issues"]: st.warning(i)
    for i in info["notes"]: st.info(i)
    with st.expander("🧩 How I understood your report (change Sum / Average if needed)"):
        ed = st.data_editor(pd.DataFrame(info["roles"]), hide_index=True, use_container_width=True, disabled=["Column", "Role"],
                            column_config={"Aggregation": st.column_config.SelectboxColumn(options=["sum", "avg", "ignore", "-"])})
        back = {LABEL[m]: m for m in info["metrics"]}
        cur = dict(st.session_state.get("agg_override", {}))
        for r in ed.itertuples():
            if r.Role == "Metric" and r.Column in back and r.Aggregation in ("sum", "avg", "ignore"):
                k = back[r.Column]
                if r.Aggregation == info["auto_agg"].get(k): cur.pop(k, None)
                else: cur[k] = r.Aggregation
        if cur != st.session_state.get("agg_override", {}): st.session_state["agg_override"] = cur; st.rerun()
        if cur and st.button("↩︎ Reset to auto-detected"): st.session_state["agg_override"] = {}; st.rerun()
    if info["pii_removed"]: st.success(f"🔒 Removed before analysis (never sent to AI): {', '.join(info['pii_removed'])}")
    st.subheader("Key KPIs"); kpi_cards(R)
    st.subheader("🧠 AI executive summary")
    calc = "\n".join(f"- **{i['title']}** — {i['detail']}" for i in show[:6]) or "No major changes detected."
    if key:
        if st.session_state.get("ai") is None or st.session_state.get("ai_prov") != provider:
            with st.spinner("AI is analysing the processed package…"):
                st.session_state["ai_prov"] = provider; st.session_state["ai"] = ask_ai(key, lambda p: SUMMARY_PROMPT + p)
        ai = st.session_state["ai"]
        if ai.startswith("⚠️"): st.warning(ai); st.markdown("**Calculated insights (no AI needed):**"); st.markdown(calc)
        else: st.markdown(ai)
        if st.button("🔄 Regenerate AI summary"): st.session_state["ai"] = None; st.rerun()
    else:
        st.markdown(calc)
        st.caption("Add an API key in the sidebar for AI-written narrative. Numbers above are already fully calculated.")

with tabs[1]:
    if not show: st.info("No significant insights for the selected focus.")
    icon = {"positive": "📈", "drop": "⚠️", "anomaly": "🚨", "strong": "🏆", "driver": "🔍"}
    tag = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}
    for i in show:
        with st.container(border=True):
            st.markdown(f"#### {icon[i['kind']]} {i['title']}")
            st.markdown(f"**What the data shows:** {i['detail']}")
            st.markdown(f"{tag[i['conf']]} **Confidence: {i['conf']}**" + (f"  \n➡️ **Next step:** {i['action']}" if i["action"] else ""))

with tabs[2]:
    if R["trend"] is None: st.info("Trends need a date column with at least 4 distinct days.")
    else:
        opts = [LABEL[m] for m in info["metrics"]]; sel = st.multiselect("Metrics", opts, default=opts[:1])
        inv = {v: k for k, v in LABEL.items()}
        for s in sel: st.markdown(f"**{s}** ({'sum' if inv[s] in SUM_M else 'average'} per day)"); st.line_chart(R["trend"][inv[s]])
        st.subheader("Previous vs current period"); st.dataframe(R["changes"].style.format("{:,.2f}"), use_container_width=True)

with tabs[3]:
    if not R["anomalies"]: st.success("No clear outliers found.")
    else:
        st.caption("Outliers vs other campaigns (robust z-score > 3.5). Points to where to investigate; does not explain why.")
        st.dataframe(pd.DataFrame(R["anomalies"]).drop(columns="_m").sort_values("Score", key=abs, ascending=False), use_container_width=True, hide_index=True)
    st.subheader("Campaign leaderboard")
    sm = st.selectbox("Rank by", [LABEL[m] for m in R["camp"].columns], key="rank")
    col = {v: k for k, v in LABEL.items()}[sm]; st.bar_chart(R["camp"][col].sort_values(ascending=False).head(15))

with tabs[4]:
    names = sorted(R["camp"].index.astype(str)); x, y = st.columns(2)
    A, B = x.selectbox("Campaign A", names, 0), y.selectbox("Campaign B", names, min(1, len(names) - 1))
    cc = R["camp"].copy(); cc.index = cc.index.astype(str)
    t = pd.DataFrame({A: cc.loc[A], B: cc.loc[B]}); t["Diff %"] = [pct(b, a) for a, b in zip(t[A], t[B])]
    t.index = [LABEL[i] for i in t.index]; st.dataframe(t.style.format("{:,.2f}"), use_container_width=True)
    big = t["Diff %"].abs().sort_values(ascending=False).dropna().head(3)
    for k in big.index: st.write(f"• **{k}**: {B} is {t.loc[k, 'Diff %']:+.1f}% vs {A}")

with tabs[5]:
    st.caption("Try: *Which campaign generated the highest revenue?* · *Top 5 by conversion rate* · *Which campaigns need investigation?*")
    hist = st.session_state.setdefault("chat", [])
    for h in hist:
        with st.chat_message(h["role"]): st.markdown(h["content"])
    if q := st.chat_input("Ask about your report…"):
        hist.append({"role": "user", "content": q})
        with st.chat_message("user"): st.markdown(q)
        with st.chat_message("assistant"):
            ra = rule_answer(q, R)
            if ra:
                st.markdown(ra[0] + "  \n*(calculated directly from your data)*")
                if ra[1] is not None: st.dataframe(ra[1])
                ans = ra[0] + (("\n\n" + ra[1].to_markdown()) if ra[1] is not None else "")
            elif key:
                ans = ask_ai(key, lambda p: f"PACKAGE:\n{p}\n\nQUESTION: {q}", [{"role": h["role"], "content": h["content"]} for h in hist[-7:-1]]); st.markdown(ans)
            else: ans = "I can answer ranking/anomaly questions without AI (e.g. *highest revenue campaign*). For open-ended questions add an API key in the sidebar."; st.markdown(ans)
        hist.append({"role": "assistant", "content": ans})

with tabs[6]:
    def plain(t): return re.sub(r"^#+\s*", "", re.sub(r"\*\*|__|`", "", t), flags=re.M)
    ln = "-" * 60
    tx = ["AI INSIGHTS REPORT", "=" * 60, f"Generated: {pd.Timestamp.now():%d %b %Y, %H:%M}",
          f"Campaigns/items analysed: {info['campaigns']}  |  Rows: {len(df)}  |  Insight confidence: {info['confidence']}"]
    if R["periods"]: tx.append(f"Period compared: {R['periods']}")
    tx += ["", "KPIs", ln] + [f"{LABEL[k]} ({'sum' if k in SUM_M else 'avg'}): {fmt(k, v)}" for k, v in R["overall"].items()]
    tx += ["", "KEY INSIGHTS", ln]
    for n, i in enumerate(show, 1):
        tx += [f"{n}. {i['title']}  [Confidence: {i['conf']}]", f"   What the data shows: {i['detail']}"] + ([f"   Next step: {i['action']}"] if i["action"] else []) + [""]
    if R["anomalies"]: tx += ["ANOMALIES", ln] + [f"- {a['Campaign']}: {a['Metric']} = {a['Value']} (typical {a['Typical (median)']})" for a in R["anomalies"]] + [""]
    dq = list(info["issues"]) + [f"Missing values: {k} ({v} rows)" for k, v in info["missing"].items()] + info["notes"]
    if dq: tx += ["DATA QUALITY NOTES", ln] + [f"- {x}" for x in dq] + [""]
    ai_txt = st.session_state.get("ai")
    if ai_txt and not ai_txt.startswith("⚠️"): tx += ["AI SUMMARY", ln, plain(ai_txt)]
    st.download_button("Download insight report (.txt)", "\n".join(tx).encode("utf-8-sig"), "insights_report.txt", mime="text/plain")
    st.download_button("Download campaign-level summary (.csv, PII-free)", R["camp"].round(2).to_csv(), "campaign_summary.csv")
    with st.expander("Preview: exactly what the AI receives"): st.code(pkg[:4000], language="json")

with tabs[7]:
    st.caption("Search by campaign name (partial match, not case-sensitive). Names are kept exactly as in your report.")
    qs = st.text_input("Campaign name", placeholder="e.g. Diwali, Cart, Campaign 17")
    ct = R["camp"].copy(); ct.index = ct.index.astype(str)
    hit = ct[ct.index.str.contains(qs, case=False, regex=False)] if qs else ct
    st.write(f"{len(hit)} of {len(ct)} campaigns")
    st.dataframe(hit.rename(columns=LABEL).round(2), use_container_width=True)
    if qs and len(hit) == 1 and info["has_date"]:
        one = df[df["campaign"].astype(str) == hit.index[0]]
        st.markdown(f"**Daily view: {hit.index[0]}**"); st.dataframe(one.drop(columns=["weekday", "send_hour"], errors="ignore"), use_container_width=True, hide_index=True)