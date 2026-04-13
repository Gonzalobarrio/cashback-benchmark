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
BASE_URL    = "https://igraal.pl"
LISTING_URL = "https://igraal.pl/wszystkie-sklepy"
NOISE_KEYWORDS = ["OFERTA DNIA", "oferta dnia"]

def get_all_retailers():
    r    = requests.get(LISTING_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, retailers = set(), []
    for link in soup.find_all("a", href=re.compile(r"/wszystkie-sklepy/[^/?#]+")):
        href = link.get("href", "")
        slug = href.split("/wszystkie-sklepy/")[-1].strip("/")
        full_url = href if href.startswith("http") else BASE_URL + href
        if slug and slug not in seen:
            seen.add(slug)
            retailers.append({"name": link.get_text(strip=True) or slug,
                               "slug": slug, "url": full_url})
    return retailers

def get_cashback_rate(url):
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=" ")

        zl_hits = re.findall(
            r"cashback\s+(?:do\s+)?(\d+(?:[.,]\d+)?)\s*(?:PLN|zł|zl)",
            text, re.IGNORECASE
        )
        if zl_hits:
            return str(float(zl_hits[0].replace(",", "."))), "zł"

        pct_values = []
        for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%\s*cashback", text, re.IGNORECASE):
            context = text[max(0, m.start()-150):m.end()+150]
            if any(noise in context for noise in NOISE_KEYWORDS):
                continue
            pct_values.append(float(m.group(1).replace(",", ".")))

        if pct_values:
            try:
                return str(mode(pct_values)), "%"
            except StatisticsError:
                return str(pct_values[0]), "%"

    except Exception as e:
        print(f"  Error {url}: {e}")
    return "no cashback", None

def scrape_igraal():
    retailers = get_all_retailers()
    today     = datetime.today().strftime("%Y-%m-%d")
    results   = []
    for r in retailers:
        rate, tipo = get_cashback_rate(r["url"])
        results.append({
            "date"         : today,
            "retailer"     : r["name"],
            "slug"         : r["slug"],
            "igraal_rate"  : rate if rate != "no cashback" else None,
            "cashback_type": tipo if rate != "no cashback" else "no cashback"
        })
        time.sleep(0.8)
    return pd.DataFrame(results)

if __name__ == "__main__":
    df = scrape_igraal()
    df.to_csv("data/igraal_rates_latest.csv", index=False)
    print(f"✅ iGraal: {len(df)} retailers")
