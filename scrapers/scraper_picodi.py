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

DISCOUNT_WORDS = [
    "zniżki", "zniżka", "rabat", "taniej",
    "promocj", "kupon", "kod"
]

# ── Manual slug overrides ─────────────────────────────────────────────────────
MANUAL_SLUGS = {
    # Tanda 1
    "kfc"              : "kfc",
    "kinguin"          : "kinguin",
    "kiwi"             : "kiwi",
    "komputronik"      : "komputronik",
    "konesso"          : "konesso-pl",
    "krakvet"          : "krakvet-pl",
    "lacoste"          : "lacoste",
    "lampy"            : "lampy-pl",
    "legimi"           : "legimi",
    "lego"             : "lego",
    "leoexpress"       : "leo-express",
    "levis"            : "levis",
    "lg"               : "lg",
    "lionelo"          : "lionelo",
    "cdkeys"           : "loaded",
    "lookfantastic"    : "lookfantastic",
    "lot"              : "lot",
    "mamyito"          : "mamyito",
    "mango-outlet"     : "mango-outlet",
    "marilyn"          : "marilyn",
    "maxelektro"       : "max-elektro",
    "maxizoo"          : "maxi-zoo",
    "meblemwm"         : "meblemwm",
    "wearmedicine"     : "medicine",
    "merkurymarket"    : "merkury-market",
    "michaelkors"      : "michael-kors",
    "modivo.pl"        : "modivo",
    "morele"           : "morele-net",
    "mountainwarehouse": "mountain-warehouse",
    "myprotein"        : "myprotein",
    "naoko"            : "naoko",
    "neness"           : "neness-pl",
    "neonail"          : "neonail",
    "nbsklep"          : "new-balance",
    "ninja"            : "ninja",
    "nordvpn"          : "nordvpn",
    "norton"           : "norton",
    "notino"           : "notino",
    "novakid"          : "novakid",
    "oleole"           : "oleole",
    "canalplus"        : "nc",
    # Tanda 2
    "olimp-store"      : "olimp-store",
    "ombre"            : "ombre-pl",
    "panmaterac"       : "pan-materac",
    "parfumdreams"     : "parfumdreams",
    "perfumeria.pl"    : "perfumeria",
    "perfumy"          : "perfumy-pl",
    "philips"          : "philips",
    "philips-hue"      : "philips-hue",
    "play"             : "play",
    "prm"              : "prm",
    "przyjacielekawy"  : "przyjaciele-kawy",
    "puma"             : "puma",
    "pyszne"           : "pyszne-pl",
    "radissonhotels"   : "radisson-hotels",
    "regatta"          : "regatta",
    "remix"            : "remix",
    "renee"            : "renee",
    "reporteryoung"    : "reporter-young",
    "ryobi"            : "ryobi",
    "samsung"          : "samsung",
    "senpo.pl"         : "senpo",
    "sferis"           : "sferis",
    "shark"            : "shark",
    "sinsay"           : "sinsay",
    "skechers"         : "skechers",
    "skyshowtime"      : "sky-showtime",
    "sportstylestory"  : "sportstylestory",
    "stradivarius"     : "stradivarius",
    "stylevana"        : "stylevana",
    "surfshark"        : "surfshark",
    "swiatsupli"       : "swiat-supli",
    "tagomago"         : "tagomago",
    "teufel"           : "teufel",
    "topsecret"        : "topsecret",
    "trip-com"         : "trip-com",
    "ubisoft"          : "ubisoft",
    "ucando"           : "ucando-pl",
    "udemy"            : "udemy",
    "under-armour"     : "under-armour",
    "vangraaf"         : "van-graaf",
    "vans"             : "vans",
    "vidaxl"           : "vida-xl",
    "visionexpress"    : "vision-express",
    "volcano"          : "volcano",
    # Tanda 3
    "recman"           : "recman-com",
    "sun-and-snow"     : "sunandsnow",
    "mi"               : "xiaomi",
    "streetstyle24"    : "street-style",
    "victorias-secret" : "victoria-s-secret",
    "wrangler"         : "wrangler",
    "yanosik"          : "yanosik",
    "yves-rocher"      : "yves-rocher",
    "znak"             : "znak",
    "zooplus"          : "zooplus",
    "4kidspoint"       : "4kidspoint",
    "7way"             : "7way",
}


# ══════════════════════════════════════════════════════════════════════════════
# LISTING
# ══════════════════════════════════════════════════════════════════════════════

def get_picodi_listing():
    r    = requests.get(PICODI_LISTING, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, shops = set(), {}
    for link in soup.find_all("a", href=re.compile(r"^/pl/[^/?#]{2,}$")):
        href = link.get("href", "")
        slug = href.replace("/pl/", "").strip("/")
        name = link.get_text(strip=True)
        if slug in ("sklepy", "kategorie-sklepow", "kontakt") or not slug:
            continue
        if slug not in seen:
            seen.add(slug)
            shops[slug] = {"name": name, "picodi_url": PICODI_BASE + href}
    return shops


# ══════════════════════════════════════════════════════════════════════════════
# RATE PARSER v3
# ══════════════════════════════════════════════════════════════════════════════

def get_picodi_rate(url):
    # Asegurar que la URL termina en /offers
    if not url.rstrip("/").endswith("/offers"):
        url = url.rstrip("/") + "/offers"

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None

        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")

        # ── Prioridad 1: % cashback ────────────────────────────
        pct_values = []
        for m in re.finditer(
            r"cashback\s+(?:up\s+to\s+|do\s+)?(\d+(?:[.,]\d+)?)\s*%",
            text, re.IGNORECASE
        ):
            context = text[max(0, m.start()-100):m.end()+100].lower()
            if any(w in context for w in DISCOUNT_WORDS):
                continue
            val = float(m.group(1).replace(",", "."))
            if val <= 80:
                pct_values.append(val)

        if pct_values:
            try:
                best = mode(pct_values)
            except StatisticsError:
                best = max(pct_values)
            has_do = bool(re.search(
                r"cashback\s+(?:up\s+to|do)\s+\d",
                text, re.IGNORECASE
            ))
            return str(best), ("up_to_%" if has_do else "%")

        # ── Prioridad 2: zł cashback (filtrado) ───────────────
        zl_filtered = []
        for m in re.finditer(
            r"cashback\s+(?:do\s+)?(\d+(?:[.,]\d+)?)\s*(?:PLN|zł|zl)",
            text, re.IGNORECASE
        ):
            context = text[max(0, m.start()-50):m.end()+50].lower()
            if any(w in context for w in ["bonus", "share", "refer", "invite"]):
                continue
            zl_filtered.append(float(m.group(1).replace(",", ".")))

        if zl_filtered:
            return str(zl_filtered[0]), "zł"

        # ── Prioridad 3: USD cashback ──────────────────────────
        dollar_hits = []
        for m in re.finditer(
            r"cashback\s+(?:up\s+to\s+|do\s+)?(\d+(?:[.,]\d+)?)\s*(?:USD|\$)",
            text, re.IGNORECASE
        ):
            context = text[max(0, m.start()-50):m.end()+50].lower()
            if any(w in context for w in ["bonus", "share", "refer", "invite"]):
                continue
            dollar_hits.append(float(m.group(1).replace(",", ".")))

        if dollar_hits:
            return str(dollar_hits[0]), "usd"

        return "no cashback", None

    except Exception as e:
        print(f"  Error {url}: {e}")
    return "no cashback", None


# ══════════════════════════════════════════════════════════════════════════════
# STORE RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

def find_picodi_store(retailer_name, igraal_slug, listing):
    # ── Check manual slug override first ──────────────────────
    if igraal_slug in MANUAL_SLUGS:
        picodi_slug = MANUAL_SLUGS[igraal_slug]
        url  = f"{PICODI_BASE}/pl/{picodi_slug}/offers"
        rate, rtype = get_picodi_rate(url)
        if rate and rate not in ("no cashback", None):
            return rate, rtype, url

    name_slug  = re.sub(r"[^a-z0-9]+", "-", retailer_name.lower()).strip("-")
    camel      = re.sub(r"([a-z])([A-Z])", r"\1-\2", retailer_name)
    camel_slug = re.sub(r"[^a-z0-9]+", "-", camel.lower()).strip("-")

    variants = list(dict.fromkeys([
        igraal_slug,
        igraal_slug + "-pl",
        igraal_slug + "-com",
        name_slug,
        name_slug + "-pl",
        camel_slug,
        camel_slug + "-pl",
    ]))

    # Pass 1: listing
    for v in variants:
        if v in listing:
            url  = listing[v]["picodi_url"].rstrip("/") + "/offers"
            rate, rtype = get_picodi_rate(url)
            if rate and rate not in ("no cashback", None):
                return rate, rtype, url

    # Pass 2: name matching
    name_clean = re.sub(r"[^a-z0-9]", "", retailer_name.lower())
    for slug, data in listing.items():
        shop_clean = re.sub(r"[^a-z0-9]", "", data["name"].lower())
        if name_clean == shop_clean:
            url  = data["picodi_url"].rstrip("/") + "/offers"
            rate, rtype = get_picodi_rate(url)
            if rate and rate not in ("no cashback", None):
                return rate, rtype, url

    # Pass 3: direct URL probing with /offers
    for v in variants:
        url  = f"{PICODI_BASE}/pl/{v}/offers"
        rate, rtype = get_picodi_rate(url)
        if rate and rate not in ("no cashback", None):
            return rate, rtype, url
        time.sleep(0.3)

    return "not_found", None, None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_picodi(df_igraal: pd.DataFrame) -> pd.DataFrame:
    listing = get_picodi_listing()
    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    total   = len(df_igraal)

    for i, (_, row) in enumerate(df_igraal.iterrows(), 1):
        retailer = row["retailer"]
        slug     = row["slug"]
        print(f"  [{i:>3}/{total}] {retailer} ({slug})", end=" → ")

        rate, rtype, url = find_picodi_store(retailer, slug, listing)

        if rate in ("no cashback", "not_found"):
            print(f"{'🚫' if rate == 'no cashback' else '❓'} {rate}")
        else:
            print(f"✅ {rate} ({rtype})")

        results.append({
            "date"            : today,
            "retailer"        : retailer,
            "igraal_slug"     : slug,
            "picodi_rate"     : (rate if rate not in
                                 ("no cashback", "not_found") else None),
            "picodi_rate_type": (rtype if rate not in
                                 ("no cashback", "not_found") else rate),
            "picodi_url"      : url,
        })
        time.sleep(0.4)

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    df_ig = pd.read_csv("data/igraal_rates_latest.csv")
    df    = scrape_picodi(df_ig)
    df.to_csv("data/picodi_rates_latest.csv", index=False)

    found = df["picodi_rate_type"].isin(["%", "up_to_%"]).sum()
    zl    = (df["picodi_rate_type"] == "zł").sum()
    usd   = (df["picodi_rate_type"] == "usd").sum()
    nc    = (df["picodi_rate_type"] == "no cashback").sum()
    nf    = (df["picodi_rate_type"] == "not_found").sum()

    print(f"\n✅ Picodi: {len(df)} retailers")
    print(f"   ✅ Rates % found : {found}")
    print(f"   💰 zł rates     : {zl}")
    print(f"   💵 USD rates    : {usd}")
    print(f"   🚫 No cashback  : {nc}")
    print(f"   ❓ Not found    : {nf}")
