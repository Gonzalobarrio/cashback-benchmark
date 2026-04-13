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
PICODI_BASE    = "https://www.picodi.com"
PICODI_LISTING = "https://www.picodi.com/pl/sklepy"

def get_picodi_listing():
    r    = requests.get(PICODI_LISTING, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, shops = set(), {}
    for link in soup.find_all("a", href=re.compile(r"^/pl/[^/?#]{2,}$")):
        href = link.get("href", "")
        slug = href.replace("/pl/", "").strip("/")
        name = link.get_text(strip=True)
        if slug in ("sklepy","kategorie-sklepow","kontakt") or not slug:
            continue
        if slug not in seen:
            seen.add(slug)
            shops[slug] = {"name": name, "picodi_url": PICODI_BASE + href}
    return shops

def get_picodi_rate(url):
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None
        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")

        zl_hits = re.findall(
            r"cashback\s+(?:do\s+)?(\d+(?:[.,]\d+)?)\s*(?:PLN|zł|zl)",
            text, re.IGNORECASE
        )
        if zl_hits:
            return str(float(zl_hits[0].replace(",", "."))), "zł"

        DISCOUNT_WORDS = ["zniżki","zniżka","rabat","taniej","promocj","kupon","kod"]
        pct_values = []
        for m in re.finditer(
            r"cashback\s+(?:do\s+)?(\d+(?:[.,]\d+)?)\s*%", text, re.IGNORECASE
        ):
            context = text[max(0, m.start()-100):m.end()+100].lower()
            if any(w in context for w in DISCOUNT_WORDS):
                continue
            pct_values.append(float(m.group(1).replace(",", ".")))

        if not pct_values:
            all_hits = re.findall(
                r"cashback\s+(?:do\s+)?(\d+(?:[.,]\d+)?)\s*%", text, re.IGNORECASE
            )
            pct_values = [
                float(h.replace(",",".")) for h in all_hits
                if float(h.replace(",",".")) <= 50
            ]

        if pct_values:
            try:
                best = mode(pct_values)
            except StatisticsError:
                best = pct_values[0]
            has_do = bool(re.search(r"cashback\s+do\s+\d", text, re.IGNORECASE))
            return str(best), ("up_to_%" if has_do else "%")

    except Exception as e:
        print(f"  Error {url}: {e}")
    return "no cashback", None

def find_picodi_store(retailer_name, igraal_slug, listing):
    name_slug  = re.sub(r"[^a-z0-9]+", "-", retailer_name.lower()).strip("-")
    camel      = re.sub(r"([a-z])([A-Z])", r"\1-\2", retailer_name)
    camel_slug = re.sub(r"[^a-z0-9]+", "-", camel.lower()).strip("-")

    variants = list(dict.fromkeys([
        igraal_slug,        igraal_slug + "-pl",
        igraal_slug + "-com",
        name_slug,          name_slug + "-pl",
        camel_slug,         camel_slug + "-pl",
    ]))

    for v in variants:
        if v in listing:
            rate, rtype = get_picodi_rate(listing[v]["picodi_url"])
            if rate and rate not in ("no cashback", None):
                return rate, rtype, listing[v]["picodi_url"]

    name_clean = re.sub(r"[^a-z0-9]", "", retailer_name.lower())
    for slug, data in listing.items():
        shop_clean = re.sub(r"[^a-z0-9]", "", data["name"].lower())
        if name_clean == shop_clean:
            rate, rtype = get_picodi_rate(data["picodi_url"])
            if rate and rate not in ("no cashback", None):
                return rate, rtype, data["picodi_url"]

    for v in variants:
        url  = f"{PICODI_BASE}/pl/{v}"
        rate, rtype = get_picodi_rate(url)
        if rate and rate not in ("no cashback", None):
            return rate, rtype, url
        time.sleep(0.3)

    return "not_found", None, None

def scrape_picodi(df_igraal):
    listing = get_picodi_listing()
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    for _, row in df_igraal.iterrows():
        retailer = row["retailer"]
        slug     = row["slug"]
        rate, rtype, url = find_picodi_store(retailer, slug, listing)
        results.append({
            "date"            : today,
            "retailer"        : retailer,
            "igraal_slug"     : slug,
            "picodi_rate"     : rate if rate not in ("no cashback","not_found") else None,
            "picodi_rate_type": rtype if rate not in ("no cashback","not_found") else rate,
            "picodi_url"      : url,
        })
        time.sleep(0.4)
    return pd.DataFrame(results)

if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    df_ig = pd.read_csv("data/igraal_rates_latest.csv")
    df    = scrape_picodi(df_ig)
    df.to_csv("data/picodi_rates_latest.csv", index=False)
    print(f"✅ Picodi: {len(df)} retailers")
