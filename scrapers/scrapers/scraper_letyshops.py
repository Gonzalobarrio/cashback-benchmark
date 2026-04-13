import requests
from bs4 import BeautifulSoup
import re
import time
import json
import asyncio
import pandas as pd
from datetime import datetime
from statistics import mode, StatisticsError

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}
LETYSHOPS_BASE    = "https://letyshops.com"
LETYSHOPS_LISTING = "https://letyshops.com/pl/shops"
NO_CASHBACK_PL    = "w tej chwili nie ma cashbacku w tym sklepie"
NO_CASHBACK_EN    = "there is no cashback in this store at the moment"

LETYSHOPS_COOKIES = []  # se carga desde secrets

def get_letyshops_listing():
    r    = requests.get(LETYSHOPS_LISTING, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, shops = set(), {}
    shop_pattern = re.compile(r"^/pl/shops/[^/?#]+$")
    for link in soup.find_all("a", href=shop_pattern):
        href      = link.get("href", "")
        slug      = href.split("/pl/shops/")[-1].strip("/")
        link_text = link.get_text(strip=True)
        if slug in seen:
            continue
        seen.add(slug)
        rate_match = re.search(
            r"(?:do\s*)?(\d+(?:[.,]\d+)?)\s*%\s*cashback", link_text, re.IGNORECASE
        )
        has_do = bool(re.search(r"\bdo\b", link_text[:20], re.IGNORECASE))
        rate   = str(float(rate_match.group(1).replace(",", "."))) if rate_match else None
        shops[slug] = {
            "letyshops_rate"     : rate,
            "letyshops_rate_type": "up_to_%" if (rate and has_do) else ("%" if rate else None),
            "letyshops_url"      : LETYSHOPS_BASE + href,
        }
    return shops

def extract_rate_from_url(url):
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None
        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
        xa0_hits = re.findall(r"(\d+(?:[.,]\d+)?)\xa0%", text)
        if xa0_hits:
            values = [float(v.replace(",", ".")) for v in xa0_hits]
            return str(max(values)), "%"
        if NO_CASHBACK_PL in text.lower() or NO_CASHBACK_EN in text.lower():
            return "no cashback", None
    except Exception as e:
        print(f"  Error {url}: {e}")
    return None, None

def generate_slug_variants(retailer_name, igraal_slug):
    camel      = re.sub(r"([a-z])([A-Z])", r"\1-\2", retailer_name)
    camel_slug = re.sub(r"[^a-z0-9]+", "-", camel.lower()).strip("-")
    name_slug  = re.sub(r"[^a-z0-9]+", "-", retailer_name.lower()).strip("-")
    bases      = list(dict.fromkeys([igraal_slug, name_slug, camel_slug]))
    variants   = []
    for b in bases:
        variants.append(b + "-pl")
    for b in bases:
        variants.append(b + "-polska")
    for b in bases:
        variants.append(b)
    return list(dict.fromkeys(variants))

def find_letyshops_store(retailer_name, igraal_slug, listing):
    slug_variants     = generate_slug_variants(retailer_name, igraal_slug)
    found_no_cashback = False
    url_bases = [
        LETYSHOPS_BASE + "/pl/shops/",
        LETYSHOPS_BASE + "/pl-en/shops/",
    ]
    for slug in slug_variants:
        if slug in listing:
            rate, rtype = extract_rate_from_url(listing[slug]["letyshops_url"])
            if rate and rate not in ("no cashback", None):
                return rate, rtype, listing[slug]["letyshops_url"]
            if rate == "no cashback":
                found_no_cashback = True
    for slug in slug_variants:
        for base in url_bases:
            url  = base + slug
            rate, rtype = extract_rate_from_url(url)
            if rate and rate not in ("no cashback", None):
                return rate, rtype, url
            if rate == "no cashback":
                found_no_cashback = True
            time.sleep(0.3)
    if found_no_cashback:
        return "no cashback", None, None
    return "not_found", None, None

def scrape_letyshops(df_igraal):
    listing = get_letyshops_listing()
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    for _, row in df_igraal.iterrows():
        retailer = row["retailer"]
        slug     = row["slug"]
        rate, rtype, url = find_letyshops_store(retailer, slug, listing)
        results.append({
            "date"                : today,
            "retailer"            : retailer,
            "igraal_slug"         : slug,
            "letyshops_rate"      : rate if rate not in ("no cashback","not_found") else None,
            "letyshops_rate_type" : rtype if rate not in ("no cashback","not_found") else rate,
            "letyshops_url"       : url,
        })
        time.sleep(0.5)
    return pd.DataFrame(results)

if __name__ == "__main__":
    df_ig = pd.read_csv("data/igraal_rates_latest.csv")
    df    = scrape_letyshops(df_ig)
    df.to_csv("data/letyshops_rates_latest.csv", index=False)
    print(f"✅ Letyshops: {len(df)} retailers")
