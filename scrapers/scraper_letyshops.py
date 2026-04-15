import requests
from bs4 import BeautifulSoup
import re
import time
import pandas as pd
from datetime import datetime
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}
LETYSHOPS_BASE    = "https://letyshops.com"
LETYSHOPS_LISTING = "https://letyshops.com/pl/shops"
NO_CASHBACK_PHRASES = [
    "w tej chwili nie ma cashbacku w tym sklepie",
    "there is no cashback in this store at the moment",
]

# ══════════════════════════════════════════════════════════════════════════════
# SHARED RATE PARSER  (used by both listing + individual page)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_rate(text: str):
    """
    Extract the best cashback rate from arbitrary text.
    Priority: zł > up_to_% > plain %
    Returns (rate_str, rate_type) or (None, None).
    """
    # ── Fixed zł ─────────────────────────────────────────────────────────────
    zl = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?zł\s*cashback",
        text, re.IGNORECASE
    )
    if zl:
        return str(float(zl.group(1).replace(",", "."))), "zł"

    # ── up_to % — "do X%" / "up to X%" ───────────────────────────────────────
    up = re.search(
        r"(?:do|up\s+to)\s+(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%",
        text, re.IGNORECASE
    )
    if up:
        return str(float(up.group(1).replace(",", "."))), "up_to_%"

    # ── Plain % with "cashback" nearby ────────────────────────────────────────
    pct_cb = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%\s*cashback",
        text, re.IGNORECASE
    )
    if pct_cb:
        return str(float(pct_cb.group(1).replace(",", "."))), "%"

    # ── Any % fallback (take max, cap at 100) ─────────────────────────────────
    hits = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%", text)
    if hits:
        values = [float(v.replace(",", ".")) for v in hits if float(v.replace(",", ".")) <= 100]
        if values:
            return str(max(values)), "%"

    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# LISTING PAGE
# ══════════════════════════════════════════════════════════════════════════════

def get_letyshops_listing() -> dict:
    """
    Scrape /pl/shops and return a dict keyed by slug.
    Rate extracted from link text via shared _parse_rate().
    """
    r    = requests.get(LETYSHOPS_LISTING, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, shops = set(), {}
    pattern = re.compile(r"^/pl/shops/[^/?#]+$")

    for link in soup.find_all("a", href=pattern):
        href = link.get("href", "")
        slug = href.split("/pl/shops/")[-1].strip("/")
        if slug in seen:
            continue
        seen.add(slug)

        rate, rtype = _parse_rate(link.get_text(separator=" ", strip=True))
        shops[slug] = {
            "letyshops_rate"     : rate,
            "letyshops_rate_type": rtype,
            "letyshops_url"      : LETYSHOPS_BASE + href,
        }

    print(f"  📋 Listing: {len(shops)} shops found")
    return shops


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL PAGE
# ══════════════════════════════════════════════════════════════════════════════

def extract_rate_from_url(url: str):
    """
    Fetch an individual shop page.
    Returns (rate_str, rate_type), ("no cashback", None), or (None, None).
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None

        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")

        # No-cashback check first (avoids false positives)
        tl = text.lower()
        if any(phrase in tl for phrase in NO_CASHBACK_PHRASES):
            return "no cashback", None

        return _parse_rate(text)

    except Exception as e:
        print(f"    ⚠ Error fetching {url}: {e}")
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# SLUG LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def generate_slug_variants(retailer_name: str, igraal_slug: str) -> list:
    camel_slug = re.sub(r"[^a-z0-9]+", "-",
                        re.sub(r"([a-z])([A-Z])", r"\1-\2", retailer_name).lower()
                        ).strip("-")
    name_slug  = re.sub(r"[^a-z0-9]+", "-", retailer_name.lower()).strip("-")
    bases      = list(dict.fromkeys([igraal_slug, name_slug, camel_slug]))

    variants = (
        [b + "-pl"     for b in bases] +
        [b + "-polska" for b in bases] +
        [b             for b in bases]
    )
    return list(dict.fromkeys(variants))


# ══════════════════════════════════════════════════════════════════════════════
# STORE RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

def find_letyshops_store(retailer_name: str, igraal_slug: str, listing: dict):
    """
    Resolution order:
      1. Listing hit WITH rate  → return immediately (no extra HTTP)
      2. Listing hit, no rate   → scrape individual page once
      3. Direct URL probing     → try /pl/shops/ and /pl-en/shops/ variants
    Returns (rate, rate_type, url).
    """
    variants          = generate_slug_variants(retailer_name, igraal_slug)
    found_no_cashback = False

    # ── Pass 1: listing ───────────────────────────────────────────────────────
    for slug in variants:
        if slug not in listing:
            continue
        info = listing[slug]
        if info["letyshops_rate"]:                          # ✅ rate in listing
            return info["letyshops_rate"], info["letyshops_rate_type"], info["letyshops_url"]

        # Listing entry exists but no rate → scrape individual page
        rate, rtype = extract_rate_from_url(info["letyshops_url"])
        if rate and rate != "no cashback":
            return rate, rtype, info["letyshops_url"]
        if rate == "no cashback":
            found_no_cashback = True

    # ── Pass 2: direct URL probing ────────────────────────────────────────────
    url_bases = [
        LETYSHOPS_BASE + "/pl/shops/",
        LETYSHOPS_BASE + "/pl-en/shops/",
    ]
    for slug in variants:
        for base in url_bases:
            url = base + slug
            rate, rtype = extract_rate_from_url(url)
            if rate and rate != "no cashback":
                return rate, rtype, url
            if rate == "no cashback":
                found_no_cashback = True
            time.sleep(0.3)

    if found_no_cashback:
        return "no cashback", None, None
    return "not_found", None, None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_letyshops(df_igraal: pd.DataFrame) -> pd.DataFrame:
    listing = get_letyshops_listing()
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    total   = len(df_igraal)

    for i, (_, row) in enumerate(df_igraal.iterrows(), 1):
        retailer = row["retailer"]
        slug     = row["slug"]
        print(f"  [{i:>3}/{total}] {retailer} ({slug})", end=" → ")

        rate, rtype, url = find_letyshops_store(retailer, slug, listing)
        print(rate or "—")

        results.append({
            "date"               : today,
            "retailer"           : retailer,
            "igraal_slug"        : slug,
            # rate column: numeric value or None
            "letyshops_rate"     : rate if rate not in ("no cashback", "not_found") else None,
            # type column: "%" / "up_to_%" / "zł" / "no cashback" / "not_found"
            "letyshops_rate_type": rtype if rate not in ("no cashback", "not_found") else rate,
            "letyshops_url"      : url,
        })
        time.sleep(0.5)

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    df_ig  = pd.read_csv("data/igraal_rates_latest.csv")
    df_out = scrape_letyshops(df_ig)

    # Date-stamped filename — preserves history
    fname = f"data/letyshops_rates_{datetime.today().strftime('%Y%m%d')}.csv"
    df_out.to_csv(fname, index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    found = df_out["letyshops_rate_type"].isin(["%", "up_to_%", "zł"]).sum()
    nc    = (df_out["letyshops_rate_type"] == "no cashback").sum()
    nf    = (df_out["letyshops_rate_type"] == "not_found").sum()
    print(f"\n✅  Saved → {fname}")
    print(f"   Rates found : {found}")
    print(f"   No cashback : {nc}")
    print(f"   Not found   : {nf}")
