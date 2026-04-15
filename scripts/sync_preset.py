#!/usr/bin/env python3
"""
Sync Preset (Apache Superset) data to GitHub CSVs.
Runs monthly via GitHub Actions.

Env vars required:
  PRESET_API_TOKEN       — Preset Manager API token name
  PRESET_API_SECRET      — Preset Manager API token secret
  PRESET_WORKSPACE_URL   — https://608a33d2.eu5a.app.preset.io
  GITHUB_TOKEN           — GitHub Personal Access Token (repo scope)
  GITHUB_REPO            — Gonzalobarrio/cashback-benchmark
"""

import os
import sys
import base64
import requests
import pandas as pd
from datetime import datetime
from io import StringIO

# ── Config ───────────────────────────────────────────────────────────
PRESET_API_TOKEN   = os.environ["PRESET_API_TOKEN"]
PRESET_API_SECRET  = os.environ["PRESET_API_SECRET"]
WORKSPACE_URL      = os.environ["PRESET_WORKSPACE_URL"].rstrip("/")
GITHUB_TOKEN       = os.environ["GITHUB_TOKEN"]
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "Gonzalobarrio/cashback-benchmark")
DATABASE_ID        = 2      # Amazon Athena (validado)
TODAY              = datetime.now().strftime("%Y%m%d")

# ── Auth ─────────────────────────────────────────────────────────────
def get_superset_jwt():
    """Manager JWT funciona directamente en Superset (validado)."""
    print("🔑 Authenticating with Preset...")
    r = requests.post(
        "https://api.app.preset.io/v1/auth/",
        json={"name": PRESET_API_TOKEN, "secret": PRESET_API_SECRET},
        timeout=30
    )
    r.raise_for_status()
    jwt = r.json()["payload"]["access_token"]
    print("  ✅ JWT OK")
    return jwt

# ── SQL Query ─────────────────────────────────────────────────────────
def run_sql(jwt, sql, query_limit=100000, timeout=120):
    """Execute SQL via Superset SQL Lab."""
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
        "Referer": WORKSPACE_URL
    }
    r = requests.post(
        f"{WORKSPACE_URL}/api/v1/sqllab/execute/",
        headers=headers,
        json={
            "database_id": DATABASE_ID,
            "sql": sql,
            "runAsync": False,
            "expand_data": True,
            "queryLimit": query_limit
        },
        timeout=timeout
    )
    r.raise_for_status()
    data = r.json()
    cols = [c["column_name"] for c in data["columns"]]
    rows = data["data"]
    df = pd.DataFrame(rows, columns=cols)
    return df

# ── Queries ──────────────────────────────────────────────────────────
SQL_FINANCIALS = """
SELECT 
    merchant_name_unified                               AS retailer,
    DATE_FORMAT(transaction_date, '%Y%m')               AS month,
    SUM(transaction_revenue_first_eur)                  AS revenue,
    SUM(transaction_gmv_first_total_eur)                AS gmv,
    SUM(transaction_revenue_first_eur) 
        - SUM(transaction_cashback_amount_eur)          AS margin,
    CASE 
        WHEN SUM(transaction_gmv_first_total_eur) > 0 
        THEN SUM(transaction_revenue_first_eur) 
             / SUM(transaction_gmv_first_total_eur) * 100
        ELSE 0 
    END                                                 AS cpa_in,
    COUNT(DISTINCT transaction_unique_id)               AS transactions,
    SUM(transaction_cashback_amount_eur)                AS cb_total
FROM datamarts_ssbi.transactions
WHERE domain_name = 'igraalpl'
  AND transaction_source = 'CB'
  AND transaction_date >= DATE_ADD('month', -18, CURRENT_DATE)
  AND merchant_name_unified IS NOT NULL
GROUP BY 
    merchant_name_unified,
    DATE_FORMAT(transaction_date, '%Y%m')
ORDER BY merchant_name_unified, month
"""

SQL_METADATA = """
WITH active_retailers AS (
    SELECT DISTINCT merchant_name_unified
    FROM datamarts_ssbi.transactions
    WHERE domain_name = 'igraalpl'
      AND transaction_source = 'CB'
      AND transaction_date >= DATE_ADD('month', -18, CURRENT_DATE)
),
latest_meta AS (
    SELECT 
        c.merchant_name_unified,
        c.merchant_affiliate_network_admin_panel,
        c.merchant_quality,
        c.merchant_vertical_salesforce,
        c.merchant_vertical_group_salesforce,
        c.is_merchant_active,
        c.is_merchant_monetized,
        ROW_NUMBER() OVER (
            PARTITION BY c.merchant_name_unified 
            ORDER BY c.reference_date DESC
        ) AS rn
    FROM datamarts_ssbi.connect_retailer_summary c
    INNER JOIN active_retailers a 
        ON c.merchant_name_unified = a.merchant_name_unified
    WHERE c.domain_name = 'igraalpl'
)
SELECT 
    merchant_name_unified           AS retailer,
    merchant_affiliate_network_admin_panel  AS affiliate_network,
    merchant_quality                AS quality,
    merchant_vertical_salesforce    AS category,
    merchant_vertical_group_salesforce AS category_group,
    is_merchant_active,
    is_merchant_monetized
FROM latest_meta
WHERE rn = 1
ORDER BY retailer
"""

# ── Build DataFrames ──────────────────────────────────────────────────
def build_financials(jwt):
    print("\n📊 Fetching financials from Preset...")
    df = run_sql(jwt, SQL_FINANCIALS)
    
    # Tipos correctos
    for col in ['revenue', 'gmv', 'margin', 'cpa_in', 'cb_total']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).round(2)
    df['transactions'] = pd.to_numeric(df['transactions'], errors='coerce').fillna(0).astype(int)
    
    print(f"  ✅ {len(df)} rows — {df['retailer'].nunique()} retailers")
    print(f"     Meses: {sorted(df['month'].unique())}")
    print(f"     Revenue: €{df['revenue'].sum():,.0f}")
    return df

def build_metadata(jwt, df_fin):
    print("\n📋 Fetching metadata from Preset...")
    df_meta = run_sql(jwt, SQL_METADATA, query_limit=10000, timeout=60)
    
    # Calcular aggregates desde financials
    df_agg = df_fin.groupby('retailer').agg(
        avg_cpa_in         = ('cpa_in',      'mean'),
        avg_margin_eur     = ('margin',       'mean'),
        avg_revenue_eur    = ('revenue',      'mean'),
        avg_gmv_eur        = ('gmv',          'mean'),
        avg_cb_total_eur   = ('cb_total',     'mean'),
        total_transactions = ('transactions', 'sum'),
        months_with_data   = ('month',        'count')
    ).reset_index()
    
    for col in ['avg_cpa_in', 'avg_margin_eur', 'avg_revenue_eur', 'avg_gmv_eur', 'avg_cb_total_eur']:
        df_agg[col] = df_agg[col].round(2)
    df_agg['total_transactions'] = df_agg['total_transactions'].astype(int)
    
    df_final = df_meta.merge(df_agg, on='retailer', how='left')
    df_final['margin_alert'] = df_final['avg_margin_eur'] < 0
    
    cols = [
        'retailer', 'affiliate_network', 'quality', 'category',
        'category_group', 'is_merchant_active', 'is_merchant_monetized',
        'avg_cpa_in', 'avg_margin_eur', 'avg_revenue_eur',
        'avg_gmv_eur', 'avg_cb_total_eur', 'total_transactions',
        'months_with_data', 'margin_alert'
    ]
    df_final = df_final[cols]
    
    print(f"  ✅ {len(df_final)} retailers")
    print(f"     margin_alert=True: {df_final['margin_alert'].sum()}")
    return df_final

# ── GitHub Upload ─────────────────────────────────────────────────────
def upload_to_github(df, repo_path, commit_msg):
    """Upload DataFrame as CSV to GitHub."""
    content = base64.b64encode(df.to_csv(index=False).encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"
    
    # Obtener SHA para update
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    
    payload = {"message": commit_msg, "content": content, "branch": "main"}
    if sha:
        payload["sha"] = sha
    
    r = requests.put(url, headers=headers, json=payload)
    
    if r.status_code in [200, 201]:
        action = "updated" if sha else "created"
        print(f"  ✅ {repo_path} {action}")
    else:
        print(f"  ❌ {repo_path}: {r.status_code} — {r.text[:200]}")
        sys.exit(1)

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f"🚀 Preset sync — {TODAY}")
    print(f"   Workspace: {WORKSPACE_URL}")
    print(f"   Repo: {GITHUB_REPO}")
    
    # Auth
    jwt = get_superset_jwt()
    
    # Fetch data
    df_fin  = build_financials(jwt)
    df_meta = build_metadata(jwt, df_fin)
    
    # Upload to GitHub
    print("\n📤 Uploading to GitHub...")
    commit_msg = f"chore: sync Preset data {TODAY} — {df_meta['retailer'].nunique()} retailers"
    
    upload_to_github(df_fin,  "data/retailer_financials.csv", commit_msg)
    upload_to_github(df_meta, "data/retailer_metadata.csv",   commit_msg)
    
    print(f"\n✅ Sync complete — {df_meta['retailer'].nunique()} retailers updated")
    print(f"   https://github.com/{GITHUB_REPO}/tree/main/data")

if __name__ == "__main__":
    main()
