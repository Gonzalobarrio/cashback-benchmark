import requests
from bs4 import BeautifulSoup
import re
import time
import pandas as pd
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}
GOODIE_BASE    = "https://goodie.pl"
GOODIE_LISTING = "https://goodie.pl/cashback"


def get_goodie_listing():
    r    = requests.get(GOODIE_LISTING, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    shops = {}
    for link in soup.find_all("a", href=re.compile(r"^/marka/[^/?#]+$")):
        slug = link.get("href", "").replace("/marka/", "").strip("/")
        name = link.get_text(strip=True)
        if slug:
            shops[slug] = {
                "name"      : name or slug,
                "goodie_url": GOODIE_BASE + link.get("href", "")
            }
    return shops


def get_goodie_rate(url):
    clean_url = url.split("?")[0]
    try:
        r = requests.get(clean_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None

        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")

        # ── Priority 1: BOOST pattern ──────────────────────────────────────
        # Page text: "20% up to 2.2% return cashback"
        #         or "up to 30% up to 16% return cashback"
        # The FIRST number is the active boost; the second (strikethrough) is the base.
        # We capture group(2) = boost value; group(1) tells us if boost itself is "up to".
        boost_match = re.search(
            r"(up\s+to\s+)?(\d+(?:[.,]\d+)?)\s*%\s+up\s+to\s+\d+(?:[.,]\d+)?\s*%"
            r"\s*(?:zwrotu\s*|return\s*)?cashback",
            text, re.IGNORECASE
        )
        if boost_match:
            is_up_to = bool(boost_match.group(1))
            val = float(boost_match.group(2).replace(",", "."))
            if 0 < val <= 100:
                print(f"    ⚡ boost detected: {val}{'% (up_to)' if is_up_to else '%'}")
                return str(val), "up_to_%" if is_up_to else "%"

        # ── Priority 2: All cashback rates → take MAXIMUM ──────────────────
        # Handles PL ("zwrotu cashback") AND EN ("return cashback" / bare "cashback")
        # When boost is active: boost% > base%, so max() = boost rate ✓
        # When no boost: single rate, max() = that rate ✓
        all_rates = []
        for m in re.finditer(
            r"(?:do\s+|up\s+to\s+)?(\d+(?:[.,]\d+)?)\s*%\s*"
            r"(?:zwrotu\s*|return\s*)?cashback",
            text, re.IGNORECASE
        ):
            val = float(m.group(1).replace(",", "."))
            if 0 < val <= 100:
                all_rates.append(val)

        if all_rates:
            best = max(all_rates)
            has_up_to = bool(re.search(
                r"\bdo\s+\d|\bup\s+to\s+\d", text, re.IGNORECASE
            ))
            return str(best), "up_to_%" if has_up_to else "%"

        # ── Fallback: cashback page but no parseable rate ──────────────────
        if "cashback" in text.lower():
            return "no cashback", None

    except Exception as e:
        print(f"  Error {url}: {e}")
    return None, None


def find_goodie_store(retailer_name, igraal_slug, listing):
    name_slug  = re.sub(r"[^a-z0-9]+", "-", retailer_name.lower()).strip("-")
    camel      = re.sub(r"([a-z])([A-Z])", r"\1-\2", retailer_name)
    camel_slug = re.sub(r"[^a-z0-9]+", "-", camel.lower()).strip("-")

    variants = list(dict.fromkeys([
        igraal_slug,             igraal_slug + "-pl",
        igraal_slug + "-com",
        name_slug,               name_slug + "-pl",
        name_slug + "-com",      name_slug.replace("-", ""),
        camel_slug,              camel_slug + "-pl",
    ]))

    # Pass 1 — match against listing dict (fast, no extra requests)
    for v in variants:
        if v in listing:
            rate, rtype = get_goodie_rate(listing[v]["goodie_url"])
            if rate:
                return rate, rtype, listing[v]["goodie_url"]

    # Pass 2 — fuzzy name match in listing
    name_clean = re.sub(r"[^a-z0-9]", "", retailer_name.lower())
    for slug, data in listing.items():
        shop_clean = re.sub(r"[^a-z0-9]", "", data["name"].lower())
        if name_clean == shop_clean:
            rate, rtype = get_goodie_rate(data["goodie_url"])
            if rate:
                return rate, rtype, data["goodie_url"]

    # Pass 3 — brute-force URL variants
    for v in variants:
        url = f"{GOODIE_BASE}/marka/{v}"
        rate, rtype = get_goodie_rate(url)
        if rate:
            return rate, rtype, url
        time.sleep(0.2)

    return "not_found", None, None


def scrape_goodie(df_igraal):
    listing = get_goodie_listing()
    print(f"  📋 Goodie listing: {len(listing)} shops found")
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    total   = len(df_igraal)

    for i, (_, row) in enumerate(df_igraal.iterrows(), 1):
        retailer = row["retailer"]
        slug     = row["slug"]
        print(f"  [{i:>3}/{total}] {retailer} ({slug})", end=" → ")

        rate, rtype, url = find_goodie_store(retailer, slug, listing)

        if rate == "not_found":
            print("❓ not found")
        elif rate == "no cashback":
            print("🚫 no cashback")
        else:
            print(f"✅ {rate} ({rtype})")

        results.append({
            "date"            : today,
            "retailer"        : retailer,
            "igraal_slug"     : slug,
            "goodie_rate"     : rate if rate not in ("no cashback", "not_found") else None,
            "goodie_rate_type": rtype if rate not in ("no cashback", "not_found") else rate,
            "goodie_url"      : url,
        })
        time.sleep(0.4)

    return pd.DataFrame(results)


if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    df_ig = pd.read_csv("data/igraal_rates_latest.csv")
    df    = scrape_goodie(df_ig)
    df.to_csv("data/goodie_rates_latest.csv", index=False)

    found  = (df["goodie_rate_type"].notna() & ~df["goodie_rate_type"].isin(["no cashback","not_found"])).sum()
    nc     = (df["goodie_rate_type"] == "no cashback").sum()
    nf     = (df["goodie_rate_type"] == "not_found").sum()
    boosts = df["goodie_rate_type"].eq("%").sum() + df["goodie_rate_type"].eq("up_to_%").sum()

    print(f"\n✅ Goodie: {len(df)} retailers procesados")
    print(f"   ✅ Con rate    : {found}  (incl. {boosts} boosts detectados)")
    print(f"   🚫 No cashback: {nc}")
    print(f"   ❓ Not found  : {nf}")
