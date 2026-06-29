"""Try to sign up for a test account and return the credentials."""
import sys, time, json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
    time.sleep(4)

    signup_tab = page.locator("button").filter(has_text="Sign Up").first
    if not signup_tab.is_visible():
        # Already logged in?
        sidebar = page.locator('section[data-testid="stSidebar"]')
        if sidebar.locator("button").filter(has_text="Dashboard").first.is_visible():
            print("ALREADY_LOGGED_IN")
            browser.close()
            sys.exit(0)
        print("NO_SIGNUP_TAB")
        browser.close()
        sys.exit(1)

    signup_tab.click()
    time.sleep(2)

    email_field = page.get_by_label("Email", exact=False).last
    pwd_fields = page.locator("input[type='password']")

    test_email = "playwright-e2e-" + str(int(time.time())) + "@test.com"
    test_pass = "TestPass123!"

    email_field.fill(test_email, force=True)
    pwd_fields.nth(pwd_fields.count() - 2).fill(test_pass, force=True)
    pwd_fields.last.fill(test_pass, force=True)

    page.locator("button").filter(has_text="Create Account").first.click()
    time.sleep(5)

    sidebar = page.locator('section[data-testid="stSidebar"]')
    if sidebar.locator("button").filter(has_text="Dashboard").first.is_visible():
        print(f"SUCCESS:{test_email}:{test_pass}")
    else:
        alert = page.locator('[data-testid="stAlert"]')
        if alert.is_visible():
            print(f"FAILED:{alert.text_content()[:200]}")
        else:
            print("FAILED:Unknown state")
    page.screenshot(path="reports/qa/screenshots/00-signup-attempt.png")
    browser.close()
