import re
import time
import pandas as pd
from datetime import datetime
import os
from playwright.sync_api import sync_playwright

LETYSHOPS_BASE    = "https://letyshops.com"
LETYSHOPS_LISTING = "https://letyshops.com/pl/shops"
LETYSHOPS_LOGIN   = "https://letyshops.com/pl/login"

NO_CASHBACK_PHRASES = [
    "w tej chwili nie ma cashbacku w tym sklepie",
    "there is no cashback in this store at the moment",
    "brak cashbacku",
]

# ══════════════════════════════════════════════════════════════════════════════
# RATE PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_rate(text: str):
    # Fixed zł
    zl = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?zł\s*cashback",
        text, re.IGNORECASE
    )
    if zl:
        return str(float(zl.group(1).replace(",", "."))), "zł"

    # up_to_%
    up = re.search(
        r"(?:do|up\s+to)\s+(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%",
        text, re.IGNORECASE
    )
    if up:
        return str(float(up.group(1).replace(",", "."))), "up_to_%"

    # Plain % + cashback nearby
    pct_cb = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%\s*cashback",
        text, re.IGNORECASE
    )
    if pct_cb:
        return str(float(pct_cb.group(1).replace(",", "."))), "%"

    # Any % fallback
    hits = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:\xa0)?%", text)
    if hits:
        values = [float(v.replace(",", ".")) for v in hits
                  if 0 < float(v.replace(",", ".")) <= 95]
        if values:
            return str(max(values)), "%"

    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER WITH AUTO-LOGIN
# ══════════════════════════════════════════════════════════════════════════════

class LetyshopsBrowser:
    def __init__(self):
        self._pw        = None
        self._browser   = None
        self._page      = None
        self._logged_in = False

    def start(self):
        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        context       = self._browser.new_context(
            locale="pl-PL",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        self._page = context.new_page()
        return self

    def login(self, email: str, password: str) -> bool:
        if not email or not password:
            print("  ⚠️  No credentials found — scraping without login")
            return False

        try:
            print("  🔐 Logging in to Letyshops...")
            self._page.goto(LETYSHOPS_LOGIN, timeout=30000,
                            wait_until="networkidle")
            self._page.wait_for_timeout(3000)

            # ── Debug: ver qué inputs existen en la página ────────────────
            inputs = self._page.evaluate('''() => {
                return Array.from(document.querySelectorAll("input")).map(i => ({
                    type: i.type,
                    name: i.name,
                    placeholder: i.placeholder,
                    id: i.id,
                    className: i.className.substring(0, 50)
                }));
            }''')
            print(f"  📋 Inputs found on login page: {inputs}")

            # ── Selectores email ───────────────────────────────────────────
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[name="login"]',
                'input[name="username"]',
                'input[placeholder*="mail" i]',
                'input[placeholder*="login" i]',
                'input[id*="email" i]',
                'input[id*="login" i]',
                'form input:first-of-type',
            ]

            # ── Selectores password ────────────────────────────────────────
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[name="pass"]',
                'input[placeholder*="hasło" i]',
                'input[placeholder*="password" i]',
                'input[id*="password" i]',
                'input[id*="pass" i]',
            ]

            # ── Encontrar y rellenar email ─────────────────────────────────
            email_filled = False
            for sel in email_selectors:
                try:
                    el = self._page.locator(sel).first
                    if el.count() > 0:
                        el.wait_for(timeout=3000, state="visible")
                        el.fill(email)
                        print(f"  ✅ Email filled with selector: {sel}")
                        email_filled = True
                        break
                except Exception:
                    continue

            if not email_filled:
                print("  ❌ Could not find email input")
                return False

            time.sleep(0.5)

            # ── Encontrar y rellenar password ──────────────────────────────
            pass_filled = False
            for sel in password_selectors:
                try:
                    el = self._page.locator(sel).first
                    if el.count() > 0:
                        el.wait_for(timeout=3000, state="visible")
                        el.fill(password)
                        print(f"  ✅ Password filled with selector: {sel}")
                        pass_filled = True
                        break
                except Exception:
                    continue

            if not pass_filled:
                print("  ❌ Could not find password input")
                return False

            time.sleep(0.5)

            # ── Submit ─────────────────────────────────────────────────────
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Zaloguj")',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'form button',
            ]

            submitted = False
            for sel in submit_selectors:
                try:
                    el = self._page.locator(sel).first
                    if el.count() > 0:
                        el.click()
                        print(f"  ✅ Submitted with selector: {sel}")
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                self._page.keyboard.press("Enter")
                print("  ⚠️  Submit via Enter key")

            self._page.wait_for_timeout(4000)

            # ── Verificar login ────────────────────────────────────────────
            current_url = self._page.url
            page_text   = self._page.inner_text("body").lower()
            print(f"  📍 URL after login: {current_url}")

            if any(fail in page_text for fail in
                   ["nieprawidłowe", "błędne", "invalid", "incorrect",
                    "wrong", "error", "błąd"]):
                print("  ❌ Login failed — wrong credentials")
                return False

            if any(ok in current_url for ok in
                   ["shops", "dashboard", "profile", "account", "pl/"]):
                print("  ✅ Login successful")
                self._logged_in = True
                return True

            # ── Verificar elemento de usuario logueado ────────────────────
            logged_in_indicators = [
                '[class*="user" i]',
                '[class*="account" i]',
                '[class*="profile" i]',
                'a[href*="logout"]',
                'a[href*="wyloguj"]',
            ]
            for indicator in logged_in_indicators:
                try:
                    if self._page.locator(indicator).count() > 0:
                        print("  ✅ Login successful (element detected)")
                        self._logged_in = True
                        return True
                except Exception:
                    continue

            print("  ⚠️  Login status unclear — continuing anyway")
            self._logged_in = True
            return True

        except Exception as e:
            print(f"  ❌ Login error: {e}")
            return False

    def get_text(self, url: str, wait_ms: int = 2000) -> str | None:
        try:
            self._page.goto(url, timeout=20000, wait_until="networkidle")
            self._page.wait_for_timeout(wait_ms)
            return self._page.inner_text("body")
        except Exception as e:
            print(f"    ⚠ Playwright error on {url}: {e}")
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
    browser._page.goto(LETYSHOPS_LISTING, timeout=30000,
                       wait_until="networkidle")
    browser._page.wait_for_timeout(3000)

    # ── Scroll para cargar todos los shops (lazy loading) ─────────
    print("  📋 Scrolling to load all shops...")
    prev_count = 0
    for scroll_attempt in range(15):
        browser._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        browser._page.wait_for_timeout(1500)

        current_count = browser._page.evaluate('''() => {
            return document.querySelectorAll('a[href*="/pl/shops/"]').length;
        }''')
        print(f"  📋 Scroll {scroll_attempt + 1}: {current_count} links found")

        if current_count == prev_count and scroll_attempt > 3:
            break
        prev_count = current_count

    # ── Scroll back to top ────────────────────────────────────────
    browser._page.evaluate("window.scrollTo(0, 0)")
    browser._page.wait_for_timeout(1000)

    content = browser._page.content()
    soup    = BeautifulSoup(content, "html.parser")

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
                    info["letyshops_url"])

        rate, rtype = extract_rate_from_url(browser, info["letyshops_url"])
        if rate and rate != "no cashback":
            return rate, rtype, info["letyshops_url"]
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
                return rate, rtype, url
            if rate == "no cashback":
                found_no_cashback = True
            time.sleep(0.3)

    if found_no_cashback:
        return "no cashback", None, None
    return "not_found", None, None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_letyshops(df_igraal: pd.DataFrame) -> pd.DataFrame:
    # ── Credentials from GitHub Secrets ──────────────────────────
    email    = os.environ.get("LETYSHOPS_EMAIL", "")
    password = os.environ.get("LETYSHOPS_PASSWORD", "")

    browser = LetyshopsBrowser().start()
    browser.login(email, password)
    listing = get_letyshops_listing(browser)

    today   = datetime.today().strftime("%Y-%m-%d")
    results = []
    total   = len(df_igraal)

    try:
        for i, (_, row) in enumerate(df_igraal.iterrows(), 1):
            retailer = row["retailer"]
            slug     = row["slug"]
            print(f"  [{i:>3}/{total}] {retailer} ({slug})", end=" → ")

            rate, rtype, url = find_letyshops_store(
                browser, retailer, slug, listing
            )
            print(rate or "—")

            results.append({
                "date"               : today,
                "retailer"           : retailer,
                "igraal_slug"        : slug,
                "letyshops_rate"     : (rate if rate not in
                                        ("no cashback", "not_found") else None),
                "letyshops_rate_type": (rtype if rate not in
                                        ("no cashback", "not_found") else rate),
                "letyshops_url"      : url,
            })
            time.sleep(0.4)

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
    print(f"   Rates found : {found}")
    print(f"   No cashback : {nc}")
    print(f"   Not found   : {nf}")
