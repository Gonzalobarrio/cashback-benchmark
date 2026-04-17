import re
import time
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os

LETYSHOPS_BASE    = "https://letyshops.com"
LETYSHOPS_LISTING = "https://letyshops.com/pl/shops"

HEADERS = {
    "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Accept"         : "text/html,application/xhtml+xml,application/xml;"
                       "q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection"     : "keep-alive",
}

NO_CASHBACK_PHRASES = [
    "w tej chwili nie ma cashbacku w tym sklepie",
    "there is no cashback in this store at the moment",
    "brak cashbacku",
]


# ══════════════════════════════════════════════════════════════════════════════
# RATE PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_rate(text: str):
    zl = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?zł\s*cashback",
        text, re.IGNORECASE
    )
    if zl:
        return str(float(zl.group(1).replace(",", "."))), "zł"

    up = re.search(
        r"(?:do|up\s+to)\s+(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%",
        text, re.IGNORECASE
    )
    if up:
        return str(float(up.group(1).replace(",", "."))), "up_to_%"

    pct_cb = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%\s*cashback",
        text, re.IGNORECASE
    )
    if pct_cb:
        return str(float(pct_cb.group(1).replace(",", "."))), "%"

    hits = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%", text)
    if hits:
        values = [float(v.replace(",", ".")) for v in hits
                  if 0 < float(v.replace(",", ".")) <= 95]
        if values:
            return str(max(values)), "%"

    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# SESSION WITH COOKIES
# ══════════════════════════════════════════════════════════════════════════════

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)

    cookies_json = os.environ.get("LETYSHOPS_COOKIES", "")
    if not cookies_json:
        print("  ⚠️  No LETYSHOPS_COOKIES secret found")
        return session

    try:
        raw_cookies = json.loads(cookies_json)

        # ── Enviar cookies como header directo ────────────────────
        cookie_header = "; ".join([
            f"{c['name']}={c['value']}"
            for c in raw_cookies
        ])
        session.headers.update({"Cookie": cookie_header})
        print(f"  ✅ {len(raw_cookies)} cookies loaded as header")

        locale_cookie = next(
            (c for c in raw_cookies if c["name"] == "hl"), None
        )
        if locale_cookie:
            print(f"  📍 Locale cookie: {locale_cookie['value']}")

        # ── Test de sesión ────────────────────────────────────────
        print("  🔍 Testing session with Allegro page...")
        test = session.get(
            "https://letyshops.com/pl/shops/allegro-pl",
            timeout=15
        )
        print(f"  📍 Test URL after redirect: {test.url}")
        test_text = BeautifulSoup(test.text, "html.parser").get_text(separator=" ")
        test_rate, _ = _parse_rate(test_text)
        print(f"  📊 Allegro test rate: {test_rate} (expected ~5.1%)")

    except Exception as e:
        print(f"  ⚠️  Session setup error: {e}")

    return session


# ══════════════════════════════════════════════════════════════════════════════
# LISTING PAGE
# ══════════════════════════════════════════════════════════════════════════════

def get_letyshops_listing(session: requests.Session) -> dict:
    print("  📋 Fetching listing page...")
    try:
        r = session.get(LETYSHOPS_LISTING, timeout=15)
        print(f"  📋 Listing final URL: {r.url}")
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ⚠️  Listing fetch error: {e}")
        return {}

    pattern = re.compile(r"^/pl/shops/[^/?#]+$")
    seen, shops = set(), {}

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

def extract_rate_from_url(session: requests.Session, url: str):
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 404:
            return None, None
        if r.status_code != 200:
            return None, None

        # Debug: log final URL to detect redirects
        if r.url != url:
            print(f"    🔀 Redirect: {url} → {r.url}")

        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
        tl   = text.lower()

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
                        re.sub(r"([a-z])([A-Z])", r"\1-\2",
                               retailer_name).lower()).strip("-")
    name_slug  = re.sub(r"[^a-z0-9]+", "-",
                        retailer_name.lower()).strip("-")
    bases = list(dict.fromkeys([igraal_slug, name_slug, camel_slug]))

    variants = (
        [b + "-pl"     for b in bases] +
        [b + "-polska" for b in bases] +
        [b             for b in bases]
    )
    return list(dict.fromkeys(variants))


# ══════════════════════════════════════════════════════════════════════════════
# STORE RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

def find_letyshops_store(
    session: requests.Session,
    retailer_name: str,
    igraal_slug: str,
    listing: dict
):
    variants          = generate_slug_variants(retailer_name, igraal_slug)
    found_no_cashback = False

    # ── Pass 1: listing ───────────────────────────────────────────
    for slug in variants:
        if slug not in listing:
            continue
        info = listing[slug]
        if info["letyshops_rate"]:
            return (info["letyshops_rate"],
                    info["letyshops_rate_type"],
                    info["letyshops_url"],
                    "listing")

        rate, rtype = extract_rate_from_url(session, info["letyshops_url"])
        if rate and rate != "no cashback":
            return rate, rtype, info["letyshops_url"], "listing_page"
        if rate == "no cashback":
            found_no_cashback = True

    # ── Pass 2: direct /pl/shops/ ─────────────────────────────────
    url_bases = [
        LETYSHOPS_BASE + "/pl/shops/",
        LETYSHOPS_BASE + "/pl-en/shops/",
    ]
    for slug in variants:
        for base in url_bases:
            url  = base + slug
            rate, rtype = extract_rate_from_url(session, url)
            if rate and rate != "no cashback":
                return rate, rtype, url, "direct"
            if rate == "no cashback":
                found_no_cashback = True
            time.sleep(0.2)

    if found_no_cashback:
        return "no cashback", None, None, "direct"
    return "not_found", None, None, "direct"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_letyshops(df_igraal: pd.DataFrame) -> pd.DataFrame:
    session = build_session()
    listing = get_letyshops_listing(session)

    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    total   = len(df_igraal)

    for i, (_, row) in enumerate(df_igraal.iterrows(), 1):
        retailer = row["retailer"]
        slug     = row["slug"]
        print(f"  [{i:>3}/{total}] {retailer} ({slug})", end=" → ")

        rate, rtype, url, method = find_letyshops_store(
            session, retailer, slug, listing
        )

        if rate in ("no cashback", "not_found"):
            print(f"{'🚫' if rate == 'no cashback' else '❓'} {rate}  [{method}]")
        else:
            print(f"✅ {rate}%  [{method}]")

        results.append({
            "date"               : today,
            "retailer"           : retailer,
            "igraal_slug"        : slug,
            "letyshops_rate"     : (rate if rate not in
                                    ("no cashback", "not_found") else None),
            "letyshops_rate_type": (rtype if rate not in
                                    ("no cashback", "not_found") else rate),
            "letyshops_boosted"  : False,
            "letyshops_url"      : url,
        })
        time.sleep(0.3)

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    df_ig  = pd.read_csv("data/igraal_rates_latest.csv")
    df_out = scrape_letyshops(df_ig)

    today       = datetime.today().strftime("%Y%m%d")
    dated_file  = f"data/letyshops_rates_{today}.csv"
    latest_file = "data/letyshops_rates_latest.csv"

    df_out.to_csv(dated_file,  index=False)
    df_out.to_csv(latest_file, index=False)

    found = df_out["letyshops_rate_type"].isin(["%", "up_to_%", "zł"]).sum()
    nc    = (df_out["letyshops_rate_type"] == "no cashback").sum()
    nf    = (df_out["letyshops_rate_type"] == "not_found").sum()

    print(f"\n✅ Saved → {dated_file}")
    print(f"✅ Saved → {latest_file}")
    print(f"   ✅ Rates found : {found}")
    print(f"   🚫 No cashback : {nc}")
    print(f"   ❓ Not found   : {nf}")
