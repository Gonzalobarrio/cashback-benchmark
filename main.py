import os
import pandas as pd
import numpy as np
from datetime import datetime
from scrapers.scraper_igraal    import scrape_igraal
from scrapers.scraper_letyshops import scrape_letyshops
from scrapers.scraper_picodi    import scrape_picodi
from scrapers.scraper_alerabat  import scrape_alerabat
from scrapers.scraper_goodie    import scrape_goodie

os.makedirs("data", exist_ok=True)
print("🚀 Starting daily cashback benchmark scraping...\n")

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def clean_zl(df, rate_col, type_col):
    """Null out fixed-amount zł rates (incomparable with %)."""
    df = df.copy()
    df[rate_col] = pd.to_numeric(df[rate_col], errors="coerce")
    mask = df[type_col].str.lower().str.contains("zł|zl", na=False)
    df.loc[mask, rate_col] = None
    return df


def sanity_check(df, rate_col, source: str):
    """Remove suspicious rates. Boosted rates exempt."""
    df = df.copy()
    threshold = {
        "letyshops" : 95,
        "picodi"    : 80,
        "alerabat"  : 80,
        "goodie"    : 80,
        "igraal"    : 95,
    }.get(source, 80)

    if source == "letyshops" and "letyshops_boosted" in df.columns:
        mask = (df[rate_col] > threshold) & (~df["letyshops_boosted"])
    else:
        mask = df[rate_col] > threshold

    if mask.any():
        print(f"   ⚠️  Sanity [{source}]: nulled {mask.sum()} "
              f"rates > {threshold}%: "
              f"{df.loc[mask, 'retailer'].tolist()}")
    df.loc[mask, rate_col] = None
    return df


def compute_status(row) -> tuple:
    """
    Returns (status, action_direction) based on:

    WITH margin data:
      worse rate + margin+  → ACT NOW  / UP
      worse rate + margin-  → REVIEW   / UP
      better rate + margin- → ACT NOW  / DOWN
      better rate + margin+ → OPTIMISE / NONE

    WITHOUT margin → use CPA IN as proxy:
      worse rate + rate < CPA  → ACT NOW  / UP
      worse rate + rate > CPA  → REVIEW   / UP
      better rate + rate < CPA → MONITOR  / NONE
      better rate + rate > CPA → OPTIMISE / NONE

    FALLBACK → only delta:
      delta >= 3  → ACT NOW
      delta 1-3   → REVIEW
      delta 0-1   → MONITOR
      delta < 0   → OPTIMISE
    """
    igraal_rate = pd.to_numeric(row.get("igraal_rate"),          errors="coerce")
    best_comp   = pd.to_numeric(row.get("best_competitor_rate"), errors="coerce")
    margin      = pd.to_numeric(row.get("margin_eur"),           errors="coerce")
    cpa_in      = pd.to_numeric(row.get("cpa_in"),               errors="coerce")

    # ── No iGraal rate → can't compute ───────────────────────────
    if pd.isna(igraal_rate):
        return "NO DATA", "NONE"

    # ── Competitive position ──────────────────────────────────────
    if pd.isna(best_comp):
        better_than_comp = True   # no competitor data → assume ok
    else:
        better_than_comp = igraal_rate >= best_comp

    # ══ WITH MARGIN DATA ══════════════════════════════════════════
    if pd.notna(margin):
        positive_margin = margin >= 0

        if not better_than_comp and positive_margin:
            return "ACT NOW", "UP"

        if not better_than_comp and not positive_margin:
            return "REVIEW", "UP"

        if better_than_comp and not positive_margin:
            return "ACT NOW", "DOWN"

        if better_than_comp and positive_margin:
            return "OPTIMISE", "NONE"

    # ══ WITHOUT MARGIN → use CPA IN ═══════════════════════════════
    if pd.notna(cpa_in) and cpa_in > 0:
        rate_above_cpa = igraal_rate > cpa_in

        if not better_than_comp and not rate_above_cpa:
            return "ACT NOW", "UP"

        if not better_than_comp and rate_above_cpa:
            return "REVIEW", "UP"

        if better_than_comp and not rate_above_cpa:
            return "MONITOR", "NONE"

        if better_than_comp and rate_above_cpa:
            return "OPTIMISE", "NONE"

    # ══ FALLBACK → delta only ═════════════════════════════════════
    delta = pd.to_numeric(row.get("delta"), errors="coerce")
    if pd.notna(delta):
        if delta >= 3:
            return "ACT NOW", "UP"
        if 1 <= delta < 3:
            return "REVIEW", "UP"
        if 0 <= delta < 1:
            return "MONITOR", "NONE"
        if delta < 0:
            return "OPTIMISE", "NONE"

    return "NO DATA", "NONE"


# ══════════════════════════════════════════════════════════════════════════════
# 1. SCRAPE ALL SOURCES
# ══════════════════════════════════════════════════════════════════════════════

print("1/5 Scraping iGraal...")
df_ig = scrape_igraal()
print(f"   ✅ {len(df_ig)} retailers\n")

print("2/5 Scraping Letyshops...")
df_lt = scrape_letyshops(df_ig)
print(f"   ✅ {len(df_lt)} retailers\n")

print("3/5 Scraping Picodi...")
df_pc = scrape_picodi(df_ig)
print(f"   ✅ {len(df_pc)} retailers\n")

print("4/5 Scraping Alerabat...")
df_al = scrape_alerabat(df_ig)
print(f"   ✅ {len(df_al)} retailers\n")

print("5/5 Scraping Goodie...")
df_gd = scrape_goodie(df_ig)
print(f"   ✅ {len(df_gd)} retailers\n")

# ══════════════════════════════════════════════════════════════════════════════
# 2. CLEAN (BEFORE saving _latest)
# ══════════════════════════════════════════════════════════════════════════════

df_ig = clean_zl(df_ig, "igraal_rate",    "cashback_type")
df_lt = clean_zl(df_lt, "letyshops_rate", "letyshops_rate_type")
df_pc = clean_zl(df_pc, "picodi_rate",    "picodi_rate_type")
df_al = clean_zl(df_al, "alerabat_rate",  "alerabat_rate_type")
df_gd = clean_zl(df_gd, "goodie_rate",    "goodie_rate_type")

df_ig = sanity_check(df_ig, "igraal_rate",    "igraal")
df_lt = sanity_check(df_lt, "letyshops_rate", "letyshops")
df_pc = sanity_check(df_pc, "picodi_rate",    "picodi")
df_al = sanity_check(df_al, "alerabat_rate",  "alerabat")
df_gd = sanity_check(df_gd, "goodie_rate",    "goodie")

# ══════════════════════════════════════════════════════════════════════════════
# 3. SAVE _latest.csv (AFTER cleaning)
# ══════════════════════════════════════════════════════════════════════════════

df_ig.to_csv("data/igraal_rates_latest.csv",    index=False)
df_lt.to_csv("data/letyshops_rates_latest.csv", index=False)
df_pc.to_csv("data/picodi_rates_latest.csv",    index=False)
df_al.to_csv("data/alerabat_rates_latest.csv",  index=False)
df_gd.to_csv("data/goodie_rates_latest.csv",    index=False)
print("✅ All _latest.csv saved (cleaned)\n")

# ══════════════════════════════════════════════════════════════════════════════
# 4. BUILD BENCHMARK
# ══════════════════════════════════════════════════════════════════════════════

print("📊 Building benchmark dataset...")
df = df_ig[["retailer", "igraal_rate", "cashback_type"]].copy()

df = df.merge(
    df_lt[["retailer", "letyshops_rate", "letyshops_rate_type",
           "letyshops_boosted", "letyshops_url"]],
    on="retailer", how="left"
)
df = df.merge(
    df_pc[["retailer", "picodi_rate", "picodi_rate_type", "picodi_url"]],
    on="retailer", how="left"
)
df = df.merge(
    df_al[["retailer", "alerabat_rate", "alerabat_rate_type", "alerabat_url"]],
    on="retailer", how="left"
)
df = df.merge(
    df_gd[["retailer", "goodie_rate", "goodie_rate_type", "goodie_url"]],
    on="retailer", how="left"
)

# ── Numeric conversion ────────────────────────────────────────────
competitor_cols = ["letyshops_rate", "picodi_rate",
                   "alerabat_rate",  "goodie_rate"]
df[competitor_cols] = df[competitor_cols].apply(pd.to_numeric, errors="coerce")
df["igraal_rate"]   = pd.to_numeric(df["igraal_rate"], errors="coerce")

# ── Best competitor rate ──────────────────────────────────────────
df["best_competitor_rate"] = df[competitor_cols].max(axis=1)

# ── Best competitor name ──────────────────────────────────────────
def get_best_competitor_name(row):
    candidates = {
        "letyshops": row["letyshops_rate"],
        "picodi"   : row["picodi_rate"],
        "alerabat" : row["alerabat_rate"],
        "goodie"   : row["goodie_rate"],
    }
    valid = {k: v for k, v in candidates.items() if pd.notna(v)}
    if not valid:
        return None
    return max(valid, key=valid.get)

df["best_competitor"] = df.apply(get_best_competitor_name, axis=1)

def flag_boost(row):
    if row.get("best_competitor") == "letyshops" and row.get("letyshops_boosted"):
        return "letyshops 🔥"
    return row.get("best_competitor")

df["best_competitor"] = df.apply(flag_boost, axis=1)

# ── Delta ─────────────────────────────────────────────────────────
df["delta"] = (df["best_competitor_rate"] - df["igraal_rate"]).round(2)

# ── Merge financials ──────────────────────────────────────────────
financials_file = "data/retailer_financials.csv"
if os.path.exists(financials_file):
    df_fin = pd.read_csv(financials_file)
    df_fin["month"] = df_fin["month"].astype(str)

    df_fin_agg = df_fin.groupby("retailer").agg(
        margin_eur   = ("margin",       "sum"),
        cpa_in       = ("cpa_in",       "last"),
        revenue      = ("revenue",      "sum"),
        gmv          = ("gmv",          "sum"),
        transactions = ("transactions", "sum"),
        cb_total     = ("cb_total",     "sum"),
    ).reset_index()

    print(f"   📋 Financials: {len(df_fin_agg)} retailers | "
          f"months: {df_fin['month'].nunique()} | "
          f"latest: {df_fin['month'].max()}")

    df = df.merge(df_fin_agg, on="retailer", how="left")

    with_margin = df["margin_eur"].notna().sum()
    print(f"✅ Financials merged — {with_margin} retailers with margin data")

else:
    df["margin_eur"]   = np.nan
    df["cpa_in"]       = np.nan
    df["revenue"]      = np.nan
    df["gmv"]          = np.nan
    df["transactions"] = np.nan
    df["cb_total"]     = np.nan
    print("⚠️  retailer_financials.csv not found — status will use delta only")

# ── Compute status ────────────────────────────────────────────────
status_results         = df.apply(compute_status, axis=1)
df["status"]           = status_results.apply(lambda x: x[0])
df["action_direction"] = status_results.apply(lambda x: x[1])

# ── is_best_rate flag ─────────────────────────────────────────────
df["is_best_rate"] = (
    df["igraal_rate"].notna() &
    df["best_competitor_rate"].notna() &
    (df["igraal_rate"] >= df["best_competitor_rate"])
).astype(bool)

# ── Legacy alert column (backwards compatibility) ─────────────────
df["alert"] = df["delta"].apply(
    lambda d: "LOWER" if pd.notna(d) and d > 0 else "OK"
)

df["date"] = datetime.today().strftime("%Y-%m-%d")

# ── Column order ──────────────────────────────────────────────────
col_order = [
    "date", "retailer", "igraal_rate", "cashback_type",
    "letyshops_rate", "letyshops_rate_type", "letyshops_boosted",
    "picodi_rate",    "picodi_rate_type",
    "alerabat_rate",  "alerabat_rate_type",
    "goodie_rate",    "goodie_rate_type",
    "best_competitor", "best_competitor_rate",
    "delta", "alert",
    "margin_eur", "cpa_in", "revenue", "gmv", "transactions", "cb_total",
    "status", "action_direction", "is_best_rate",
    "letyshops_url", "picodi_url", "alerabat_url", "goodie_url",
]
df = df[[c for c in col_order if c in df.columns]]
df = df.sort_values("delta", ascending=False)
df.to_csv("data/benchmark_data.csv", index=False)

# ══════════════════════════════════════════════════════════════════════════════
# 5. HISTORY
# ══════════════════════════════════════════════════════════════════════════════

history_file = "data/benchmark_history.csv"
if os.path.exists(history_file):
    df_history = pd.read_csv(history_file)
    df_history = pd.concat([df_history, df], ignore_index=True)
    df_history = df_history.drop_duplicates(
        subset=["date", "retailer"], keep="last"
    )
else:
    df_history = df.copy()
df_history.to_csv(history_file, index=False)

# ══════════════════════════════════════════════════════════════════════════════
# 6. ENRICHED
# ══════════════════════════════════════════════════════════════════════════════

NAME_MAP = {
    "ALAB Laboratoria" : "Alab",
    "AUTODOC"          : "Autodoc",
    "Adidas"           : "adidas",
    "BeDiet"           : "beDiet",
    "Brasty"           : "BRASTY",
    "CDkeys"           : "CDKeys",
    "Canal Plus"       : "CANAL+",
    "DHgate"           : "DHGate",
    "DeLonghi"         : "Delonghi",
    "Dstreet"          : "DSTREET",
    "Foreo"            : "FOREO",
    "Kiwi"             : "Kiwi.com",
    "Lookfantastic"    : "LookFantastic",
    "Lounge by Zalando": "Zalando Lounge",
    "NEONAIL"          : "NeoNail",
    "Ninja"            : "Ninja Kitchen",
    "SHEIN"            : "Shein",
    "Senpo.pl"         : "Senpo",
    "Sun & Snow"       : "Sun&Snow",
    "Surfshark"        : "SurfShark",
    "Van Graaf"        : "Van GRAAF",
    "Wolt"             : "WOLT",
    "eBilet"           : "E-Bilet",
    "home&you"         : "home and you",
    "norton"           : "Norton",
}

metadata_file = "data/retailer_metadata.csv"
if os.path.exists(metadata_file):
    df_meta = pd.read_csv(metadata_file)
    df["retailer_preset"] = df["retailer"].map(NAME_MAP).fillna(df["retailer"])
    df_enriched = df.merge(
        df_meta,
        left_on ="retailer_preset",
        right_on="retailer",
        how="left",
        suffixes=("", "_meta")
    )
    df_enriched.drop(
        columns=["retailer_preset", "retailer_meta"],
        errors="ignore", inplace=True
    )
    df_enriched.to_csv("data/benchmark_data_enriched.csv", index=False)
    print(f"✅ benchmark_data_enriched.csv — "
          f"{df_enriched['affiliate_network'].notna().sum()} "
          f"retailers enriched")
else:
    print("⚠️  retailer_metadata.csv not found — skipping enrichment")

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

boosted_today   = df.get("letyshops_boosted", pd.Series(dtype=bool)).sum()
best_rate_count = df["is_best_rate"].sum()

print(f"\n✅ benchmark_data.csv    — {len(df)} retailers")
print(f"✅ benchmark_history.csv — {len(df_history)} rows total")
print(f"")
print(f"   📊 STATUS BREAKDOWN:")
for status in ["ACT NOW", "REVIEW", "MONITOR", "OPTIMISE", "NO DATA"]:
    count = (df["status"] == status).sum()
    emoji = {
        "ACT NOW" : "🔴",
        "REVIEW"  : "🟡",
        "MONITOR" : "🔵",
        "OPTIMISE": "🟣",
        "NO DATA" : "⚪",
    }.get(status, "  ")
    print(f"   {emoji} {status:<12} : {count}")
print(f"")
print(f"   🏆 Best Rate (iGraal leads) : {best_rate_count}")
print(f"   🔥 Boosted rates today      : {int(boosted_today)}")
