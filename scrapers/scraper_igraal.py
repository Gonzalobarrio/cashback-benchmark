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
BASE_URL       = "https://igraal.pl"
LISTING_URL    = "https://igraal.pl/wszystkie-sklepy"
NOISE_KEYWORDS = ["OFERTA DNIA", "oferta dnia"]


# ══════════════════════════════════════════════════════════════════════════════
# LISTING
# ══════════════════════════════════════════════════════════════════════════════

def get_all_retailers():
    r    = requests.get(LISTING_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, retailers = set(), []
    for link in soup.find_all(
        "a", href=re.compile(r"/wszystkie-sklepy/[^/?#]+")
    ):
        href     = link.get("href", "")
        slug     = href.split("/wszystkie-sklepy/")[-1].strip("/")
        full_url = href if href.startswith("http") else BASE_URL + href
        if slug and slug not in seen:
            seen.add(slug)
            retailers.append({
                "name": link.get_text(strip=True) or slug,
                "slug": slug,
                "url" : full_url
            })
    return retailers


# ══════════════════════════════════════════════════════════════════════════════
# RATE PARSER v5
# ══════════════════════════════════════════════════════════════════════════════

def get_cashback_rate(url):
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return "no cashback", None

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=" ")

        # ── Prioridad 0: "do X% cashbacku" en header ──────────
        # Más fiable — es el rate principal en el bloque superior
        header_text = text[:1500]
        header_match = re.search(
            r"do\s+(\d+(?:[.,]\d+)?)\s*%\s*cashback\w*",
            header_text, re.IGNORECASE
        )
        if header_match:
            val = float(header_match.group(1).replace(",", "."))
            if 0 < val <= 100:
                return str(val), "%"

        # ── Prioridad 1: X% cashback* en texto completo ────────
        pct_values = []
        for m in re.finditer(
            r"(\d+(?:[.,]\d+)?)\s*%\s*cashback\w*",
            text, re.IGNORECASE
        ):
            context = text[max(0, m.start()-150):m.end()+150]
            if any(noise in context for noise in NOISE_KEYWORDS):
                continue
            val = float(m.group(1).replace(",", "."))
            if 0 < val <= 100:
                pct_values.append(val)

        if pct_values:
            try:
                return str(mode(pct_values)), "%"
            except StatisticsError:
                return str(pct_values[0]), "%"

        # ── Prioridad 2: X zł cashback* ────────────────────────
        for m in re.finditer(
            r"(\d+(?:[.,]\d+)?)\s*(?:PLN|zł|zl)\s*cashback\w*",
            text, re.IGNORECASE
        ):
            val = float(m.group(1).replace(",", "."))
            if val > 0:
                return str(val), "zł"

        # ── Prioridad 3: cashback* X zł ────────────────────────
        for m in re.finditer(
            r"cashback\w*\s+(?:do\s+)?(\d+(?:[.,]\d+)?)\s*(?:PLN|zł|zl)",
            text, re.IGNORECASE
        ):
            context = text[max(0, m.start()-50):m.end()+50].lower()
            if any(w in context for w in
                   ["bonus", "nagroda", "polecenie", "zaproś"]):
                continue
            val = float(m.group(1).replace(",", "."))
            if val > 0:
                return str(val), "zł"

        # ── Prioridad 4: +X cashbacku en título ───────────────
        title_text = text[:800]
        for m in re.finditer(
            r"\+\s*(\d+(?:[.,]\d+)?)\s*cashback\w*",
            title_text, re.IGNORECASE
        ):
            val = float(m.group(1).replace(",", "."))
            if val > 80:
                return str(val), "zł"
            elif 0 < val <= 100:
                return str(val), "%"

    except Exception as e:
        print(f"  Error {url}: {e}")
    return "no cashback", None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_igraal() -> pd.DataFrame:
    retailers = get_all_retailers()
    today     = datetime.today().strftime("%Y-%m-%d")
    results   = []
    total     = len(retailers)

    print(f"  🔍 Found {total} retailers on iGraal.pl")

    for i, r in enumerate(retailers, 1):
        print(f"  [{i:>3}/{total}] {r['name']} ({r['slug']})", end=" → ")
        rate, tipo = get_cashback_rate(r["url"])

        if rate == "no cashback":
            print("🚫 no cashback")
        else:
            print(f"✅ {rate} ({tipo})")

        results.append({
            "date"         : today,
            "retailer"     : r["name"],
            "slug"         : r["slug"],
            "igraal_rate"  : rate if rate != "no cashback" else None,
            "cashback_type": tipo if rate != "no cashback" else "no cashback",
        })
        time.sleep(0.8)

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    df = scrape_igraal()
    df.to_csv("data/igraal_rates_latest.csv", index=False)

    pct = (df["cashback_type"] == "%").sum()
    zl  = (df["cashback_type"] == "zł").sum()
    nc  = (df["cashback_type"] == "no cashback").sum()

    print(f"\n✅ iGraal: {len(df)} retailers")
    print(f"   ✅ % rates     : {pct}")
    print(f"   💰 zł rates   : {zl}")
    print(f"   🚫 No cashback : {nc}")
