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

# 1. iGraal
print("1/5 Scraping iGraal...")
df_ig = scrape_igraal()
df_ig.to_csv("data/igraal_rates_latest.csv", index=False)
print(f"   ✅ {len(df_ig)} retailers\n")

# 2. Letyshops
print("2/5 Scraping Letyshops...")
df_lt = scrape_letyshops(df_ig)
df_lt.to_csv("data/letyshops_rates_latest.csv", index=False)
print(f"   ✅ {len(df_lt)} retailers\n")

# 3. Picodi
print("3/5 Scraping Picodi...")
df_pc = scrape_picodi(df_ig)
df_pc.to_csv("data/picodi_rates_latest.csv", index=False)
print(f"   ✅ {len(df_pc)} retailers\n")

# 4. Alerabat
print("4/5 Scraping Alerabat...")
df_al = scrape_alerabat(df_ig)
df_al.to_csv("data/alerabat_rates_latest.csv", index=False)
print(f"   ✅ {len(df_al)} retailers\n")

# 5. Goodie
print("5/5 Scraping Goodie...")
df_gd = scrape_goodie(df_ig)
df_gd.to_csv("data/goodie_rates_latest.csv", index=False)
print(f"   ✅ {len(df_gd)} retailers\n")

# ── Clean zł rates ────────────────────────────────────────────────
def clean_zl(df, rate_col, type_col):
    df = df.copy()
    df[rate_col] = pd.to_numeric(df[rate_col], errors="coerce")
    mask = df[type_col].str.lower().str.contains("zł|zl", na=False)
    df.loc[mask, rate_col] = None
    return df

df_ig = clean_zl(df_ig, "igraal_rate",    "cashback_type")
df_lt = clean_zl(df_lt, "letyshops_rate",  "letyshops_rate_type")
df_pc = clean_zl(df_pc, "picodi_rate",     "picodi_rate_type")
df_al = clean_zl(df_al, "alerabat_rate",   "alerabat_rate_type")
df_gd = clean_zl(df_gd, "goodie_rate",     "goodie_rate_type")

# ── Sanity check — rates > 50% sospechosos ────────────────────────
def sanity_check(df, rate_col):
    df = df.copy()
    df.loc[df[rate_col] > 50, rate_col] = None
    return df

df_lt = sanity_check(df_lt, "letyshops_rate")
df_pc = sanity_check(df_pc, "picodi_rate")
df_al = sanity_check(df_al, "alerabat_rate")
df_gd = sanity_check(df_gd, "goodie_rate")

# ── Build benchmark ───────────────────────────────────────────────
print("📊 Building benchmark dataset...")
df = df_ig[["retailer","igraal_rate","cashback_type"]].copy()
df = df.merge(df_lt[["retailer","letyshops_rate","letyshops_rate_type"]], on="retailer", how="left")
df = df.merge(df_pc[["retailer","picodi_rate","picodi_rate_type"]],       on="retailer", how="left")
df = df.merge(df_al[["retailer","alerabat_rate","alerabat_rate_type"]],   on="retailer", how="left")
df = df.merge(df_gd[["retailer","goodie_rate","goodie_rate_type"]],       on="retailer", how="left")

competitor_cols = ["letyshops_rate","picodi_rate","alerabat_rate","goodie_rate"]
df["best_competitor_rate"] = df[competitor_cols].max(axis=1)
df["delta"] = (df["best_competitor_rate"] - df["igraal_rate"]).round(2)
df["alert"] = df.apply(
    lambda r: "LOWER" if pd.notna(r["delta"]) and pd.notna(r["igraal_rate"]) and r["delta"] > 0 else "OK",
    axis=1
)
df["date"] = datetime.today().strftime("%Y-%m-%d")
df = df.sort_values("delta", ascending=False)
df.to_csv("data/benchmark_data.csv", index=False)

# ── Historical ────────────────────────────────────────────────────
history_file = "data/benchmark_history.csv"
if os.path.exists(history_file):
    df_history = pd.read_csv(history_file)
    df_history = pd.concat([df_history, df], ignore_index=True)
    df_history = df_history.drop_duplicates(subset=["date","retailer"], keep="last")
else:
    df_history = df.copy()
df_history.to_csv(history_file, index=False)

# ── Merge con metadata de Preset ─────────────────────────────────
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
        left_on="retailer_preset",
        right_on="retailer",
        how="left",
        suffixes=("","_meta")
    )
    df_enriched.drop(columns=["retailer_preset","retailer_meta"], errors="ignore", inplace=True)
    df_enriched.to_csv("data/benchmark_data_enriched.csv", index=False)
    print(f"✅ benchmark_data_enriched.csv — {df_enriched['affiliate_network'].notna().sum()} retailers enriched")
else:
    print("⚠️ retailer_metadata.csv not found — skipping enrichment")

print(f"\n✅ benchmark_data.csv saved — {len(df)} retailers")
print(f"✅ benchmark_history.csv — {len(df_history)} rows total")
print(f"   ⚠️  LOWER: {(df['alert']=='LOWER').sum()}")
print(f"   ✅ OK:    {(df['alert']=='OK').sum()}")
