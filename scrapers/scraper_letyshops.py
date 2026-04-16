import re
import time
import pandas as pd
from datetime import datetime
import os
from playwright.sync_api import sync_playwright

LETYSHOPS_BASE    = "https://letyshops.com"
LETYSHOPS_LISTING = "https://letyshops.com/pl/shops"
LETYSHOPS_LOGIN   = "https://letyshops.com/pl/login"
LETYSHOPS_HOME    = "https://letyshops.com/pl"

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

            # Debug inputs
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

            email_selectors = [
                'input[name="_username"]',
                'input[type="email"]',
                'input[name="email"]',
                'input[name="login"]',
                'input[name="username"]',
                'input[placeholder*="mail" i]',
                'input[placeholder*="login" i]',
                'input[id*="email" i]',
                'input[id*="login" i]',
                'form input[type="text"]:not([placeholder*="Search" i])',
            ]

            password_selectors = [
                'input[name="_password"]',
                'input[type="password"]',
                'input[name="password"]',
                'input[name="pass"]',
                'input[placeholder*="hasło" i]',
                'input[placeholder*="password" i]',
                'input[id*="password" i]',
                'input[id*="pass" i]',
            ]

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
            print(f"  📍 URL after login: {self._page.url}")

            # ── Forzar locale polaco independientemente del redirect ───────
            print("  🌍 Forcing Polish locale...")
            self._page.goto(LETYSHOPS_HOME, timeout=30000,
                            wait_until="networkidle")
            self._page.wait_for_timeout(3000)
            print(f"  📍 URL after locale fix: {self._page.url}")

            # ── Verificar que estamos logueados ───────────────────────────
            page_text = self._page.inner_text("body").lower()
            if any(fail in page_text for fail in
                   ["nieprawidłowe", "błędne", "invalid", "incorrect",
                    "wrong", "błąd"]):
                print("  ❌ Login failed — wrong credentials")
                return False

            print("  ✅ Login successful — Polish locale active")
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
# HOMEPAGE BOOSTS
# ══════════════════════════════════════════════════════════════════════════════

def get_letyshops_boosts(browser: LetyshopsBrowser) -> dict:
    """
    Scrape homepage for active cashback boosts (3X, 4X, 7X...).
    Returns dict: {slug: boosted_rate_float}
    """
    print("  🔥 Fetching homepage boosts...")
    browser._page.goto(LETYSHOPS_HOME, timeout=30000, wait_until="networkidle")
    browser._page.wait_for_timeout(4000)

    # ── Scroll to load lazy content ───────────────────────────────
    for _ in range(4):
        browser._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        browser._page.wait_for_timeout(1500)
    browser._page.evaluate("window.scrollTo(0, 0)")
    browser._page.wait_for_timeout(1000)

    # ── Debug — cuántos links /pl/shops/ hay en la homepage ───────
    shop_links_count = browser._page.evaluate('''()
