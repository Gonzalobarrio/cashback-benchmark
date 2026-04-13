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
GOODIE_BASE    = "https://goodie.pl"
GOODIE_LISTING = "https://goodie.pl/cashback"

def get_goodie_listing():
    r    = requests.get(GOODIE_LISTING, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    shops = {}
    for link in soup.find_all("a", href=re.compile(r"^/marka/[^/?#]+$")):
        slug = link.get("href","").replace("/marka/","").strip("/")
        name = link.get_text(strip=True)
        if slug:
            shops[slug] = {"name": name or slug, "goodie_url": GOODIE_BASE + link.get("href","")}
    return shops

def get_goodie_rate(url):
    clean_url = url.split("?")[0]
    try:
        r    = requests.get(clean_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None
        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
        hits = re.findall(
            r"(?:do\s+)?(\d+(?:[.,]\d+)?)\s*%\s*zwrotu\s*cashback",
            text, re.IGNORECASE
        )
        if hits:
            values = [float(h.replace(",", ".")) for h in hits]
            try:
                best = mode(values)
            except StatisticsError:
                best = values[0]
            has_do = bool(re.search(r"\bdo\s+\d", text, re.IGNORECASE))
            return str(best), ("up_to_%" if has_do else "%")
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
        igraal_slug,        igraal_slug + "-pl",
        igraal_slug + "-com",
        name_slug,          name_slug + "-pl",
        name_slug + "-com", name_slug.replace("-",""),
        camel_slug,         camel_slug + "-pl",
    ]))

    for v in variants:
        if v in listing:
            rate, rtype = get_goodie_rate(listing[v]["goodie_url"])
            if rate:
                return rate, rtype, listing[v]["goodie_url"]

    name_clean = re.sub(r"[^a-z0-9]", "", retailer_name.lower())
    for slug, data in listing.items():
        shop_clean = re.sub(r"[^a-z0-9]", "", data["name"].lower())
        if name_clean == shop_clean:
            rate, rtype = get_goodie_rate(data["goodie_url"])
            if rate:
                return rate, rtype, data["goodie_url"]

    for v in variants:
        url  = f"{GOODIE_BASE}/marka/{v}"
        rate, rtype = get_goodie_rate(url)
        if rate:
            return rate, rtype, url
        time.sleep(0.2)

    return "not_found", None, None

def scrape_goodie(df_igraal):
    listing = get_goodie_listing()
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    for _, row in df_igraal.iterrows():
        retailer = row["retailer"]
        slug     = row["slug"]
        rate, rtype, url = find_goodie_store(retailer, slug, listing)
        results.append({
            "date"            : today,
            "retailer"        : retailer,
            "igraal_slug"     : slug,
            "goodie_rate"     : rate if rate not in ("no cashback","not_found") else None,
            "goodie_rate_type": rtype if rate not in ("no cashback","not_found") else rate,
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
    print(f"✅ Goodie: {len(df)} retailers")
