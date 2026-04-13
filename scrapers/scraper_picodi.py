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
