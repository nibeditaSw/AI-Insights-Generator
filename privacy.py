"""Secure Data Layer — FR-PR-01..05. Raw data never leaves this layer."""
import re
import pandas as pd

PII_RE = re.compile(
    r"name|e-?mail|phone|mobile|msisdn|customer.?id|cust.?id|user.?id|"
    r"order.?id|device.?id|address|ip.?addr|^ip$|\buid\b",
    re.I,
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EXCLUDE_RE = re.compile(r"campaign|segment|channel|(ad|adset|creative|offer|product|promo)[\s_]*name", re.I)


def detect_pii(df: pd.DataFrame) -> list[str]:
    """Return columns that look like PII by header or email-like content."""
    pii: list[str] = []
    n = min(len(df), 50)
    smp = df.head(n) if n else df
    for col in df.columns:
        c = str(col)
        if PII_RE.search(c) and not EXCLUDE_RE.search(c):
            pii.append(col)
            continue
        try:
            hits = smp[col].astype(str).str.match(EMAIL_RE).sum()
            if n > 0 and hits / max(n, 1) > 0.3:
                pii.append(col)
        except Exception:
            pass
    return pii


def secure_process(df: pd.DataFrame):
    """
    Returns (clean_df, pii_cols).
    clean_df drops PII columns — aggregation only, no customer rows sent to AI.
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    pii = detect_pii(df)
    clean = df.drop(columns=pii, errors="ignore")
    return clean, pii
