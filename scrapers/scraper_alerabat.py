import requests
from bs4 import BeautifulSoup
import re
import time
import pandas as pd
from datetime import datetime
from statistics import mode, StatisticsError

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}
ALERABAT_BASE    = "https://alerabat.com"
ALERABAT_LISTING = "https://alerabat.com/sklepy"

def get_alerabat_listing():
    r    = requests.get(ALERABAT_LISTING, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, shops = set(), {}
    for link in soup.find_all("a", href=re.compile(r"kody-promocyjne/[^/?#]+")):
        href = link.get("href", "")
        slug = href.split("kody-promocyjne/")[-1].strip("/")
        name = link.get_text(strip=True)
        if slug and slug not in seen and name:
            seen.add(slug)
            shops[slug] = {
                "name"        : name,
                "alerabat_url": href if href.startswith("http") else ALERABAT_BASE + href
            }
    return shops

def get_alerabat_rate(url):
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None
        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
        hits = re.findall(
            r"cashback\s+do\s+(\d+(?:[.,]\d+)?)\s*%",
            text, re.IGNORECASE
        )
        if hits:
            values = [float(h.replace(",", ".")) for h in hits]
            try:
                best = mode(values)
            except StatisticsError:
                best = values[0]
            return str(best), "up_to_%"
        is_real_page = any(kw in text.lower() for kw in [
            "kody rabatowe", "cashback", "kupony", "promocje"
        ])
        if is_real_page:
            return "no cashback", None
    except Exception as e:
        print(f"  Error {url}: {e}")
    return None, None

def find_alerabat_store(retailer_name, igraal_slug, listing):
    name_slug  = re.sub(r"[^a-z0-9]+", "-", retailer_name.lower()).strip("-")
    camel      = re.sub(r"([a-z])([A-Z])", r"\1-\2", retailer_name)
    camel_slug = re.sub(r"[^a-z0-9]+", "-", camel.lower()).strip("-")

    variants = list(dict.fromkeys([
        igraal_slug,           igraal_slug + "-pl",
        igraal_slug + "-com",  igraal_slug + "-net",
        name_slug,             name_slug + "-pl",
        name_slug + "-com",    name_slug + "-net",
        camel_slug,            camel_slug + "-pl",
    ]))

    for v in variants:
        if v in listing:
            rate, rtype = get_alerabat_rate(listing[v]["alerabat_url"])
            if rate:
                return rate, rtype, listing[v]["alerabat_url"]

    name_clean = re.sub(r"[^a-z0-9]", "", retailer_name.lower())
    for slug, data in listing.items():
        shop_clean = re.sub(r"[^a-z0-9]", "", data["name"].lower())
        if name_clean == shop_clean:
            rate, rtype = get_alerabat_rate(data["alerabat_url"])
            if rate:
                return rate, rtype, data["alerabat_url"]

    for v in variants:
        for path in ["kody-promocyjne", "kod-promocyjny", "kod-rabatowy"]:
            url  = f"{ALERABAT_BASE}/{path}/{v}"
            rate, rtype = get_alerabat_rate(url)
            if rate:
                return rate, rtype, url
            time.sleep(0.15)

    return "not_found", None, None

def scrape_alerabat(df_igraal):
    listing = get_alerabat_listing()
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    for _, row in df_igraal.iterrows():
        retailer = row["retailer"]
        slug     = row["slug"]
        rate, rtype, url = find_alerabat_store(retailer, slug, listing)
        results.append({
            "date"              : today,
            "retailer"          : retailer,
            "igraal_slug"       : slug,
            "alerabat_rate"     : rate if rate not in ("no cashback","not_found") else None,
            "alerabat_rate_type": rtype if rate not in ("no cashback","not_found") else rate,
            "alerabat_url"      : url,
        })
        time.sleep(0.4)
    return pd.DataFrame(results)

if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    df_ig = pd.read_csv("data/igraal_rates_latest.csv")
    df    = scrape_alerabat(df_ig)
    df.to_csv("data/alerabat_rates_latest.csv", index=False)
    print(f"✅ Alerabat: {len(df)} retailers")
