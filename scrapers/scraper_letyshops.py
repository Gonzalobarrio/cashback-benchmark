import re
import time
import json
import os
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright

LETYSHOPS_BASE    = "https://letyshops.com"
LETYSHOPS_LISTING = "https://letyshops.com/pl/shops"

NO_CASHBACK_PHRASES = [
    "there is no cashback in this store",
    "w tej chwili nie ma cashbacku",
    "brak cashbacku",
    "nie ma cashbacku",
]

# ══════════════════════════════════════════════════════════════════════════════
# RATE PARSER v2
# ══════════════════════════════════════════════════════════════════════════════

def _parse_rate(text: str):
    # ── Prioridad 1: "X% cashback" directo ───────────────────────
    pct_direct = re.search(
        r"(\d+(?:[.,]\d+)?)\s*%\s*\n?\s*cashback",
        text, re.IGNORECASE
    )
    if pct_direct:
        val = float(pct_direct.group(1).replace(",", "."))
        if 0 < val <= 95:
            return str(val), "%"

    # ── Prioridad 2: zł cashback ──────────────────────────────────
    zl = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?zł\s*cashback",
        text, re.IGNORECASE
    )
    if zl:
        return str(float(zl.group(1).replace(",", "."))), "zł"

    # ── Prioridad 3: "up to X%" ───────────────────────────────────
    up = re.search(
        r"(?:do|up\s+to)\s+(\d+(?:[.,]\d+)?)\s*%",
        text, re.IGNORECASE
    )
    if up:
        val = float(up.group(1).replace(",", "."))
        if 0 < val <= 95:
            return str(val), "up_to_%"

    # ── Prioridad 4: % con cashback en ventana cercana ────────────
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", text):
        val = float(m.group(1).replace(",", "."))
        if not (0 < val <= 95):
            continue
        start = max(0, m.start() - 60)
        end   = min(len(text), m.end() + 60)
        if "cashback" in text[start:end].lower():
            return str(val), "%"

    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# SLUG VARIANTS
# ══════════════════════════════════════════════════════════════════════════════

def generate_slug_variants(retailer_name: str, igraal_slug: str) -> list:
    name_lower  = retailer_name.lower()
    name_slug   = re.sub(r"[^a-z0-9]+", "-", name_lower).strip("-")
    camel_slug  = re.sub(r"[^a-z0-9]+", "-",
                         re.sub(r"([a-z])([A-Z])", r"\1-\2",
                                retailer_name).lower()).strip("-")
    words_slug  = "-".join(name_lower.split())

    bases = list(dict.fromkeys([
        igraal_slug, name_slug, camel_slug, words_slug
    ]))

    variants = []
    for b in bases:
        variants.append(b + "-pl")
        variants.append(b + "-polska")
        variants.append(b)

    return list(dict.fromkeys(variants))


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER WITH COOKIES
# ══════════════════════════════════════════════════════════════════════════════

class LetyshopsBrowser:
    def __init__(self):
        self._pw      = None
        self._browser = None
        self._context = None
        self._page    = None

    def start(self):
        cookies_json = os.environ.get("LETYSHOPS_COOKIES", "")
        raw_cookies  = []

        if not cookies_json:
            print("  ⚠️  No LETYSHOPS_COOKIES secret found")
        else:
            try:
                raw_cookies = json.loads(cookies_json)
                print(f"  ✅ {len(raw_cookies)} cookies loaded")
            except Exception as e:
                print(f"  ⚠️  Cookie parse error: {e}")

        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage"]
        )
        self._context = self._browser.new_context(
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )

        if raw_cookies:
            self._context.add_cookies(raw_cookies)

        self._page = self._context.new_page()

        # ── Test de sesión ────────────────────────────────────────
        self._test_session()
        return self

    def _test_session(self):
        try:
            self._page.goto(
                "https://letyshops.com/pl/shops/allegro-pl",
                timeout=20000, wait_until="domcontentloaded"
            )
            self._page.wait_for_timeout(3000)
            text = self._page.inner_text("body")
            rate, _ = _parse_rate(text)
            print(f"  🔍 Session test — Allegro: {rate}% "
                  f"(URL: {self._page.url})")
        except Exception as e:
            print(f"  ⚠️  Session test error: {e}")

    def get_text(self, url: str, wait_ms: int = 3000) -> str | None:
        try:
            self._page.goto(url, timeout=20000,
                            wait_until="domcontentloaded")
            self._page.wait_for_timeout(wait_ms)
            return self._page.inner_text("body")
        except Exception as e:
            print(f"    ⚠ Error on {url}: {e}")
            return None

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()


# ══════════════════════════════════════════════════════════════════════════════
# LISTING PAGE
# ══════════════════════════════════════════════════════════════════════════════

def get_letyshops_listing(browser: LetyshopsBrowser) -> dict:
    from bs4 import BeautifulSoup

    print("  📋 Fetching listing page...")
    try:
        browser._page.goto(LETYSHOPS_LISTING, timeout=30000,
                           wait_until="domcontentloaded")
        browser._page.wait_for_timeout(3000)
    except Exception as e:
        print(f"  ⚠️  Listing timeout: {e}")

    print(f"  📋 Listing URL: {browser._page.url}")

    # Scroll para cargar todos los shops
    prev_count = 0
    for attempt in range(15):
        browser._page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )
        browser._page.wait_for_timeout(1500)
        current_count = browser._page.evaluate(
            "() => document.querySelectorAll('a[href*=\"/shops/\"]').length"
        )
        print(f"  📋 Scroll {attempt+1}: {current_count} links")
        if current_count == prev_count and attempt > 3:
            break
        prev_count = current_count

    browser._page.evaluate("window.scrollTo(0, 0)")
    browser._page.wait_for_timeout(1000)

    content = browser._page.content()
    soup    = BeautifulSoup(content, "html.parser")

    # Acepta /pl/shops/ y /pl-en/shops/
    pattern = re.compile(r"^/pl(?:-en)?/shops/[^/?#]+$")
    seen, shops = set(), {}

    for link in soup.find_all("a", href=pattern):
        href = link.get("href", "")
        slug = re.split(r"/shops/", href)[-1].strip("/")
        if slug in seen:
            continue
        seen.add(slug)
        rate, rtype = _parse_rate(link.get_text(separator=" ", strip=True))
        shops[slug] = {
            "letyshops_rate"     : rate,
            "letyshops_rate_type": rtype,
            "letyshops_url"      : LETYSHOPS_BASE + href,
        }

    print(f"  📋 Listing complete: {len(shops)} shops found")
    return shops


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL PAGE
# ══════════════════════════════════════════════════════════════════════════════

def extract_rate_from_url(browser: LetyshopsBrowser, url: str):
    text = browser.get_text(url)
    if not text:
        return None, None

    tl = text.lower()
    if any(phrase in tl for phrase in NO_CASHBACK_PHRASES):
        return "no cashback", None

    return _parse_rate(text)


# ══════════════════════════════════════════════════════════════════════════════
# STORE RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

def find_letyshops_store(
    browser: LetyshopsBrowser,
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
        rate, rtype = extract_rate_from_url(browser, info["letyshops_url"])
        if rate and rate != "no cashback":
            return rate, rtype, info["letyshops_url"], "listing_page"
        if rate == "no cashback":
            found_no_cashback = True

    # ── Pass 2: direct URL probing ────────────────────────────────
    url_bases = [
        LETYSHOPS_BASE + "/pl/shops/",
        LETYSHOPS_BASE + "/pl-en/shops/",
    ]
    for slug in variants:
        for base in url_bases:
            url  = base + slug
            rate, rtype = extract_rate_from_url(browser, url)
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
    browser = LetyshopsBrowser().start()
    listing = get_letyshops_listing(browser)

    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    total   = len(df_igraal)

    try:
        for i, (_, row) in enumerate(df_igraal.iterrows(), 1):
            retailer = row["retailer"]
            slug     = row["slug"]
            print(f"  [{i:>3}/{total}] {retailer} ({slug})", end=" → ")

            rate, rtype, url, method = find_letyshops_store(
                browser, retailer, slug, listing
            )

            if rate in ("no cashback", "not_found"):
                print(f"{'🚫' if rate == 'no cashback' else '❓'} "
                      f"{rate}  [{method}]")
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

    finally:
        browser.stop()

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
