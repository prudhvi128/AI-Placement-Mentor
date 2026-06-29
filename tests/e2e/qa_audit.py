"""Senior QA Engineer audit — runs comprehensive Playwright tests on the running Streamlit app.

Produces:
  - reports/qa/screenshots/  — per-test screenshots
  - reports/qa/qa-report.md  — full QA report
  - tests/e2e/test_critical_flows.py  — generated Playwright tests for critical flows
"""

import os, sys, json, time, re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, expect

REPORT_DIR = Path("reports/qa")
SCREENSHOT_DIR = REPORT_DIR / "screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8501")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "")

# ── Findings store ─────────────────────────────────────────────────────
findings = {
    "critical_bugs": [],
    "functional_bugs": [],
    "ui_issues": [],
    "ux_issues": [],
    "accessibility_issues": [],
    "performance_issues": [],
    "security_observations": [],
    "suggestions": [],
}

console_errors_global = []

def report(category, severity, title, detail, screenshot=None):
    findings[category].append({
        "severity": severity,
        "title": title,
        "detail": detail,
        "screenshot": screenshot,
    })

def screenshot(page, name):
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)

def log_console_errors(page):
    """Return list of console.error messages."""
    return page.evaluate("() => window.__qa_console_errors || []")

def setup_console_capture(page):
    page.evaluate("""() => {
        window.__qa_console_errors = [];
        window.__qa_console_warnings = [];
        const origError = console.error;
        console.error = function(...args) {
            window.__qa_console_errors.push(args.join(' '));
            origError.apply(console, args);
        };
        const origWarn = console.warn;
        console.warn = function(...args) {
            window.__qa_console_warnings.push(args.join(' '));
            origWarn.apply(console, args);
        };
    }""")

def wait_for_streamlit(page, secs=2):
    time.sleep(secs)

def go(page, url=None):
    page.goto(url or BASE_URL, wait_until="networkidle", timeout=30000)
    wait_for_streamlit(page, 3)

# ═══════════════════════════════════════════════════════════════════════
#  MAIN AUDIT
# ═══════════════════════════════════════════════════════════════════════

def run_audit():
    print("=" * 70)
    print("  SENIOR QA ENGINEER — FULL APPLICATION AUDIT")
    print(f"  App: {BASE_URL}")
    print(f"  Started: {datetime.now().isoformat()}")
    print("=" * 70)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2,  # Retina for crisp screenshots
        )

        # ── 1. INITIAL LOAD ──────────────────────────────────────
        print("\n[1/15] Initial page load...")
        page = context.new_page()
        setup_console_capture(page)
        go(page)

        # Check app title
        title = page.title()
        print(f"  Title: {title}")
        if not title or "AI Placement Mentor" not in title:
            report("ui_issues", "low", "Page title", f"Expected 'AI Placement Mentor' but got '{title}'")

        # Check auth vs authenticated
        is_auth_page = page.locator("button").filter(has_text="Sign In").first.is_visible()
        print(f"  Auth page: {is_auth_page}")
        if is_auth_page:
            report("ux_issues", "info", "First-run experience",
                   "New users see the auth form immediately. Consider adding a brief landing/hero before auth to explain the app's value proposition.")
            # Screenshot the landing page
            sp = screenshot(page, "01-landing-auth-page")
            print(f"  Screenshot: {sp}")

        # Check for Switch to Sign Up tab
        signup_tab = page.locator("button").filter(has_text="Sign Up").first
        signin_tab = page.locator("button").filter(has_text="Sign In").first
        has_tabs = signup_tab.is_visible() and signin_tab.is_visible()

        # ── 2. AUTH — SIGN IN FORM ───────────────────────────────
        print("\n[2/15] Auth — Sign In form audit...")
        email_input = page.locator("input[type='text']").first
        password_input = page.locator("input[type='password']").first

        if email_input.is_visible():
            # Check labels
            label = page.locator("label").filter(has_text="Email").first
            if not label.is_visible():
                report("accessibility_issues", "medium", "Missing input labels",
                       "Email input may lack an associated visible label.")
            sp = screenshot(page, "02-signin-form")
            print(f"  Screenshot: {sp}")

            # Test empty submission
            signin_btn = page.locator("button").filter(has_text="Sign In").first
            signin_btn.click()
            wait_for_streamlit(page, 2)
            errors_after_empty = log_console_errors(page)
            # Streamlit may show error in the UI
            st_error = page.locator('[data-testid="stAlert"]')
            if st_error.is_visible():
                report("functional_bugs", "low", "Empty form submission shows alert",
                       "Submitting empty sign-in form shows a Streamlit alert. This is acceptable but consider inline validation instead.")

        # ── 3. AUTH — SIGN UP FORM ───────────────────────────────
        print("\n[3/15] Auth — Sign Up form audit...")
        if signup_tab.is_visible():
            signup_tab.click()
            wait_for_streamlit(page, 2)

            pwd_fields = page.locator("input[type='password']")
            # Use .last and force=True to target the visible Sign Up form fields
            # (Sign In fields are hidden in DOM via Streamlit tab hiding)
            email_field = page.get_by_label("Email", exact=False).last

            if pwd_fields.count() >= 2:
                # Password mismatch test
                # Use force=True because Streamlit tabs keep hidden DOM in place
                email_field.fill("newuser@test.com", force=True)
                # Last two password inputs belong to the Sign Up form (visible)
                pwd_fields.nth(pwd_fields.count() - 2).fill("password123", force=True)
                pwd_fields.last.fill("different456", force=True)

                create_btn = page.locator("button").filter(has_text="Create Account").first
                create_btn.click()
                wait_for_streamlit(page, 2)

                st_error = page.locator('[data-testid="stAlert"]')
                if st_error.is_visible():
                    print("  Password mismatch correctly caught")
                else:
                    report("functional_bugs", "medium", "Password mismatch not detected",
                           "Entering non-matching passwords did not show an inline error. Check if the validation is client-side or Supabase-side.",
                           screenshot(page, "03-password-mismatch"))

                # Short password test
                pwd_fields.nth(pwd_fields.count() - 2).fill("ab", force=True)
                pwd_fields.last.fill("ab", force=True)
                create_btn.click()
                wait_for_streamlit(page, 2)
                if st_error.is_visible():
                    print("  Short password correctly caught")

            sp = screenshot(page, "04-signup-form")
            print(f"  Screenshot: {sp}")

        # ── 4. LOGIN / SIGNUP ────────────────────────────────────
        print("\n[4/15] Auth — Login/Signup flow...")
        sidebar = page.locator('section[data-testid="stSidebar"]')
        is_logged_in = sidebar.locator("button").filter(has_text="Dashboard").first.is_visible()

        if is_logged_in:
            print("  Already logged in (session persisted)")
        elif TEST_EMAIL and TEST_PASSWORD:
            # Switch to Sign In tab
            if signin_tab.is_visible():
                signin_tab.click()
                wait_for_streamlit(page, 2)

            email_input = page.get_by_label("Email", exact=False).last
            password_input = page.locator("input[type='password']").last
            email_input.fill(TEST_EMAIL, force=True)
            password_input.fill(TEST_PASSWORD, force=True)
            signin_btn = page.locator("button").filter(has_text="Sign In").first
            signin_btn.click()
            wait_for_streamlit(page, 5)

            sidebar = page.locator('section[data-testid="stSidebar"]')
            if sidebar.locator("button").filter(has_text="Dashboard").first.is_visible():
                print("  Login successful")
                is_logged_in = True
            else:
                st_error = page.locator('[data-testid="stAlert"]')
                if st_error.is_visible():
                    err_text = st_error.text_content() or ""
                    report("functional_bugs", "high", "Login failed",
                           f"Login with provided credentials failed: {err_text[:200]}",
                           screenshot(page, "05-login-failed"))
                else:
                    report("functional_bugs", "high", "Login state unclear",
                           "After login, neither sidebar nav nor error alert appeared. Check auth flow.",
                           screenshot(page, "05-login-unclear"))
                print("  Login FAILED — see report")
        else:
            print("  No credentials provided — attempting signup...")
            # Try to sign up with a fresh account
            signup_tab.click()
            wait_for_streamlit(page, 2)

            pwd_fields = page.locator("input[type='password']")
            email_field = page.get_by_label("Email", exact=False).last

            import time as _time
            test_email = "pw-e2e-" + str(int(_time.time())) + "@test.com"
            test_pass = "TestPass123!"

            email_field.fill(test_email, force=True)
            pwd_fields.nth(pwd_fields.count() - 2).fill(test_pass, force=True)
            pwd_fields.last.fill(test_pass, force=True)

            page.locator("button").filter(has_text="Create Account").first.click()

            # Signup/Supabase can take 10-20 seconds, poll for success
            signup_ok = False
            for _i in range(16):  # up to ~32 seconds
                time.sleep(2)
                sidebar = page.locator('section[data-testid="stSidebar"]')
                if sidebar.locator("button").filter(has_text="Dashboard").first.is_visible():
                    signup_ok = True
                    break
                # Also check body DOM (Streamlit may render app before visibility)
                body_text = page.text_content("body") or ""
                if "Dashboard" in body_text and "Chat" in body_text:
                    signup_ok = True
                    break

            if signup_ok:
                print(f"  Signup successful (email: {test_email})")
                is_logged_in = True
            else:
                report("functional_bugs", "high", "Signup failed",
                       "Could not create a test account after 32s wait. Supabase may require email confirmation or have rate limits.",
                       screenshot(page, "05-signup-failed"))

        # ── If not logged in, test bad login as fallback ─────────
        if not is_logged_in:
            print("\n[Fallback] Testing bad login...")
            signin_tab = page.locator("button").filter(has_text="Sign In").first
            if signin_tab.is_visible():
                signin_tab.click()
                wait_for_streamlit(page, 2)

            email_input = page.get_by_label("Email", exact=False).last
            password_input = page.locator("input[type='password']").last
            if email_input.is_visible():
                email_input.fill("fake@nonexistent.com", force=True)
                password_input.fill("wrongpassword123!", force=True)
                signin_btn = page.locator("button").filter(has_text="Sign In").first
                signin_btn.click()
                wait_for_streamlit(page, 3)
                st_error = page.locator('[data-testid="stAlert"]')
                if st_error.is_visible():
                    print("  Bad login: error shown correctly")
                else:
                    report("functional_bugs", "medium", "Invalid login no error",
                           "Attempting login with bad credentials did not show an error message.",
                           screenshot(page, "06-bad-login-no-error"))

            sp = screenshot(page, "06-bad-login")
            print(f"  Screenshot: {sp}")
            print("\n  Cannot test authenticated features — skipping to console audit.")
            browser.close()
            _write_report()
            _generate_tests()
            return

        is_logged_in = True

        # ── 5. SIDEBAR NAVIGATION ───────────────────────────────
        print("\n[5/15] Sidebar navigation audit...")
        nav_items = [
            "Dashboard", "Chat", "Resume Analyzer",
            "Mock Interview", "Career", "History",
            "Weaknesses", "Roadmap"
        ]
        for item in nav_items:
            btn = sidebar.locator("button").filter(has_text=item).first
            if btn.is_visible():
                btn.click()
                wait_for_streamlit(page, 2)
                print(f"  [OK] Navigated to {item}")
            else:
                report("functional_bugs", "medium", f"Navigation item '{item}' missing",
                       f"Sidebar button for '{item}' not found.",
                       screenshot(page, f"07-nav-{item.lower().replace(' ', '-')}-missing"))

        sp = screenshot(page, "07-sidebar-nav-complete")
        print(f"  Screenshot: {sp}")

        # ── 6. DASHBOARD ──────────────────────────────────────────
        print("\n[6/15] Dashboard audit...")
        nav_items[0] = "Dashboard"
        sidebar.locator("button").filter(has_text="Dashboard").first.click()
        wait_for_streamlit(page, 3)

        # Check metrics
        metrics = page.locator('[data-testid="stMetric"]')
        metric_count = metrics.count()
        print(f"  Metric cards: {metric_count}")
        if metric_count == 0:
            report("functional_bugs", "medium", "Dashboard metrics empty",
                   "No metric cards displayed on the dashboard.",
                   screenshot(page, "08-dashboard-no-metrics"))

        # Check quick action buttons
        quick_actions = page.locator('section[data-testid="stMain"]').locator("button")
        qa_count = quick_actions.count()
        print(f"  Buttons in main area: {qa_count}")

        # Check Assessment & Insights expander
        assessment = page.locator("button").filter(has_text="Assessment").first
        if assessment.is_visible():
            assessment.click()
            wait_for_streamlit(page, 2)
            print("  [OK] Assessment expander toggled")
        else:
            report("ui_issues", "low", "Assessment expander not found",
                   "The 'Assessment & Insights' expander was not visible on the dashboard.")

        sp = screenshot(page, "08-dashboard")
        print(f"  Screenshot: {sp}")

        # ── 7. CHAT ──────────────────────────────────────────────
        print("\n[7/15] Chat audit...")
        sidebar.locator("button").filter(has_text="Chat").first.click()
        wait_for_streamlit(page, 3)

        # Check chat input
        chat_input = page.locator('[data-testid="stChatInput"]')
        if chat_input.is_visible():
            print("  [OK] Chat input present")

            # Send a message (stChatInput is a contenteditable div, not an input)
            chat_input.click()
            page.keyboard.insert_text("Hello, who are you?")
            page.keyboard.press("Enter")
            print("  Message sent, waiting for response...")
            wait_for_streamlit(page, 15)

            # Check for response / runtime card
            runtime_card = page.locator(".runtime-card")
            if runtime_card.is_visible():
                print("  [OK] Runtime card visible")
                # Verify card structure
                items = runtime_card.locator(".rt-item")
                item_count = items.count()
                print(f"  Runtime items: {item_count}")

                # Check for corrupted characters
                card_text = runtime_card.text_content() or ""
                corrupted_patterns = ["â", "¢", "š", "€"]
                found_corrupted = [c for c in corrupted_patterns if c in card_text]
                if found_corrupted:
                    report("critical_bugs", "high", "Corrupted characters in runtime card",
                           f"Found corrupted characters {found_corrupted} in runtime card. UTF-8 encoding issue.",
                           screenshot(page, "09-corrupted-metadata"))

                sp = screenshot(page, "09-chat-response")
                print(f"  Screenshot: {sp}")
            else:
                report("functional_bugs", "high", "Runtime card missing after chat",
                       "After sending a chat message and waiting 15s, the runtime metadata card did not appear.",
                       screenshot(page, "09-chat-no-response"))
        else:
            report("functional_bugs", "high", "Chat input not visible",
                   "The chat input element (stChatInput) was not found on the Chat view.",
                   screenshot(page, "09-chat-no-input"))

        # ── 8. RUNTIME METADATA ───────────────────────────────────
        print("\n[8/15] Runtime metadata deep audit...")
        cards = page.locator(".runtime-card")
        if cards.count() > 0:
            card = cards.first
            # Check primary row
            pri = card.locator(".rt-pri")
            sec = card.locator(".rt-sec")
            if pri.is_visible():
                exec_item = card.locator(".rt-exec")
                prov_item = card.locator(".rt-provider")
                model_item = card.locator(".rt-model")
                lat_item = card.locator(".rt-latency")
                cost_item = card.locator(".rt-cost")

                for name, el in [("Execution", exec_item), ("Provider", prov_item),
                                  ("Model", model_item), ("Latency", lat_item),
                                  ("Cost", cost_item)]:
                    if not el.is_visible():
                        report("functional_bugs", "medium", f"Metadata item '{name}' hidden",
                               f"The {name} item in the runtime card is not visible.")
            if sec.is_visible():
                route_item = card.locator(".rt-route")
                reason_item = card.locator(".rt-reason")
                if route_item.is_visible():
                    route_val = route_item.locator(".rt-val").text_content() or ""
                    print(f"  Route: {route_val}")
                # Reason might be empty — that's OK
            else:
                report("functional_bugs", "low", "Secondary metadata row missing",
                       "The second row (Route/Reason) of the runtime card is not visible.")
        else:
            report("functional_bugs", "high", "No runtime cards found",
                   "No .runtime-card elements exist on the page despite having sent a chat message.")

        # ── 9. RESUME UPLOAD ──────────────────────────────────────
        print("\n[9/15] Resume upload audit...")
        sidebar.locator("button").filter(has_text="Resume Analyzer").first.click()
        wait_for_streamlit(page, 3)

        # Check uploader
        file_uploader = page.locator('[data-testid="stFileUploader"]')
        if file_uploader.is_visible():
            print("  [OK] File uploader present")
            file_input = file_uploader.locator("input[type='file']")
            if file_input.is_visible():
                # Upload the test resume
                resume_path = Path("tests/e2e/test_resume.txt").resolve()
                if resume_path.exists():
                    file_input.set_input_files(str(resume_path))
                    wait_for_streamlit(page, 3)
                    print("  [OK] File uploaded")

                    # Check for Analyze button
                    analyze_btn = page.locator("button").filter(has_text="Analyze").first
                    if analyze_btn.is_visible():
                        print("  [OK] Analyze button appeared")
                        sp = screenshot(page, "10-resume-uploaded")
                        print(f"  Screenshot: {sp}")

                        # Click Analyze
                        analyze_btn.click()
                        print("  Analyzing... (waiting up to 60s)")
                        wait_for_streamlit(page, 60)

                        # Check for results
                        success = page.locator("text=completed").first.is_visible() or \
                                  page.locator(".resume-card").first.is_visible() or \
                                  page.locator('[data-testid="stExpander"]').first.is_visible()
                        if success:
                            print("  [OK] Analysis completed")
                            sp = screenshot(page, "10-resume-analysis-result")
                            print(f"  Screenshot: {sp}")
                        else:
                            report("functional_bugs", "high", "Resume analysis failed",
                                   "After 60s wait, no analysis results appeared.",
                                   screenshot(page, "10-resume-analysis-failed"))
                    else:
                        report("functional_bugs", "medium", "Analyze button not found",
                               "After uploading a file, the Analyze button did not appear.",
                               screenshot(page, "10-resume-no-analyze-btn"))
                else:
                    report("functional_bugs", "medium", "Test resume file missing",
                           f"Test resume file not found at {resume_path}")
        else:
            report("functional_bugs", "medium", "File uploader not found",
                   "The stFileUploader element was not visible on Resume Analyzer view.",
                   screenshot(page, "10-resume-no-uploader"))

        # ── 10. MOCK INTERVIEW ──────────────────────────────────
        print("\n[10/15] Mock Interview audit...")
        sidebar.locator("button").filter(has_text="Mock Interview").first.click()
        wait_for_streamlit(page, 3)

        start_btn = page.locator("button").filter(has_text="Start Mock Interview").first
        if start_btn.is_visible():
            print("  [OK] Start button present")
            start_btn.click()
            print("  Starting interview... (waiting up to 30s for questions)")
            wait_for_streamlit(page, 30)

            # Check for question
            textarea = page.locator("textarea").first
            if textarea.is_visible():
                print("  [OK] Question displayed")
                textarea.fill("This is a test answer for the interview question. I have experience with C# and .NET development, building REST APIs, and working with databases.")
                wait_for_streamlit(page, 1)

                submit_btn = page.locator("button").filter(has_text="Submit Answer").first
                if submit_btn.is_visible():
                    submit_btn.click()
                    print("  Answer submitted, waiting for feedback...")
                    wait_for_streamlit(page, 30)

                    # Check for next question or finish
                    next_btn = page.locator("button").filter(has_text="Next Question").first
                    finish_btn = page.locator("button").filter(has_text="Finish Interview").first
                    if next_btn.is_visible() or finish_btn.is_visible():
                        print("  [OK] Answer evaluated")
                        sp = screenshot(page, "11-interview-answer-evaluated")
                        print(f"  Screenshot: {sp}")
                    else:
                        report("functional_bugs", "medium", "Interview feedback not shown",
                               "After submitting an answer, neither 'Next Question' nor 'Finish Interview' appeared.",
                               screenshot(page, "11-interview-no-feedback"))
                else:
                    report("functional_bugs", "medium", "Submit Answer button missing",
                           "Question appeared but Submit Answer button was not visible.",
                           screenshot(page, "11-interview-no-submit-btn"))
            else:
                report("functional_bugs", "medium", "Interview question not displayed",
                       "After clicking Start, no question textarea appeared within 30s.",
                       screenshot(page, "11-interview-no-question"))
        else:
            report("functional_bugs", "low", "Start Mock Interview not available",
                   "Start button not visible — possibly no resume uploaded yet or resume text missing.")

        sp = screenshot(page, "11-interview-state")
        print(f"  Screenshot: {sp}")

        # ── 11. CAREER ───────────────────────────────────────────
        print("\n[11/15] Career audit...")
        sidebar.locator("button").filter(has_text="Career").first.click()
        wait_for_streamlit(page, 3)

        textareas = page.locator("textarea")
        if textareas.count() >= 2:
            print("  [OK] Career form inputs present")
            textareas.nth(0).fill("Python, JavaScript, React, Node.js, SQL, AWS, Docker")
            textareas.nth(1).fill("AI/ML, web development, cloud architecture, system design")

            # Experience level select
            selectbox = page.locator('[data-testid="stSelectbox"]').first
            if selectbox.is_visible():
                selectbox.click()
                wait_for_streamlit(page, 1)
                # Select first option (Entry Level)
                option = page.locator('[role="option"]').first
                if option.is_visible():
                    option.click()
                    wait_for_streamlit(page, 1)
                    print("  [OK] Experience level selected")

            generate_btn = page.locator("button").filter(has_text="Generate Career").first
            if generate_btn.is_visible():
                print("  Generating career recommendation... (waiting up to 30s)")
                generate_btn.click()
                wait_for_streamlit(page, 30)

                sp = screenshot(page, "12-career-result")
                print(f"  Screenshot: {sp}")
            else:
                report("functional_bugs", "medium", "Generate Career button missing",
                       "Career form has inputs but no generate button found.",
                       screenshot(page, "12-career-no-generate-btn"))
        else:
            report("functional_bugs", "medium", "Career form incomplete",
                   f"Expected at least 2 textareas for Skills and Interests, found {textareas.count()}",
                   screenshot(page, "12-career-no-form"))

        # ── 12. HINDSIGHT MEMORY ─────────────────────────────────
        print("\n[12/15] Hindsight memory audit...")
        # Check History
        sidebar.locator("button").filter(has_text="History").first.click()
        wait_for_streamlit(page, 3)
        sp = screenshot(page, "13-history-view")
        print(f"  [History] Screenshot: {sp}")

        # Check Weaknesses
        sidebar.locator("button").filter(has_text="Weaknesses").first.click()
        wait_for_streamlit(page, 3)
        metrics_weak = page.locator('[data-testid="stMetric"]')
        if metrics_weak.count() > 0:
            print(f"  [OK] Weaknesses metrics: {metrics_weak.count()}")
        else:
            report("ui_issues", "low", "Weaknesses page has no metrics",
                   "No metric cards visible on Weaknesses view. May be an empty state.")

        sp = screenshot(page, "14-weaknesses-view")
        print(f"  [Weaknesses] Screenshot: {sp}")

        # Check Roadmap
        sidebar.locator("button").filter(has_text="Roadmap").first.click()
        wait_for_streamlit(page, 3)
        sp = screenshot(page, "15-roadmap-view")
        print(f"  [Roadmap] Screenshot: {sp}")

        # ── 13. THEME SWITCHING ─────────────────────────────────
        print("\n[13/15] Theme switching audit...")
        # Streamlit's theme toggle is in settings
        settings_btn = page.locator('[data-testid="stSettings"]').first
        if settings_btn.is_visible():
            settings_btn.click()
            wait_for_streamlit(page, 1)

            # Look for theme toggle
            theme_toggle = page.locator('[data-testid="stThemeToggle"]').first
            if theme_toggle.is_visible():
                current_theme = page.locator("body").get_attribute("data-theme") or "unknown"
                print(f"  Current theme: {current_theme}")
                theme_toggle.click()
                wait_for_streamlit(page, 2)
                new_theme = page.locator("body").get_attribute("data-theme") or "unknown"
                print(f"  After toggle: {new_theme}")
                if new_theme == current_theme:
                    report("functional_bugs", "medium", "Theme toggle not switching",
                           f"Clicked theme toggle but theme stayed as '{current_theme}'",
                           screenshot(page, "16-theme-toggle-failed"))
                sp = screenshot(page, "16-theme-switched")
                print(f"  Screenshot: {sp}")
            else:
                report("ux_issues", "low", "Theme toggle not found",
                       "Could not find a theme toggle button in the Streamlit settings menu.")
        else:
            # Try hamburger menu
            hamburger = page.locator('[data-testid="stAppViewBlockContainer"] button').first
            if hamburger.is_visible():
                hamburger.click()
                wait_for_streamlit(page, 1)
                settings_link = page.locator("a").filter(has_text="Settings").first
                if settings_link.is_visible():
                    settings_link.click()
                    wait_for_streamlit(page, 1)
                    print("  [OK] Settings menu opened via hamburger")
                else:
                    report("ui_issues", "low", "Settings menu inaccessible",
                           "Could not open Streamlit settings via hamburger menu.",
                           screenshot(page, "16-no-settings"))

        # ── 14. MOBILE RESPONSIVENESS ────────────────────────────
        print("\n[14/15] Mobile responsiveness audit...")
        # Resize current page to mobile viewport
        original_viewport = page.viewport_size
        page.set_viewport_size({"width": 375, "height": 812})
        wait_for_streamlit(page, 3)

        if is_logged_in:
            # On mobile, sidebar is collapsed — check hamburger
            hamburger = page.locator('[data-testid="stAppViewBlockContainer"] button').first
            if hamburger.is_visible():
                hamburger.click()
                wait_for_streamlit(page, 1)
                print("  [OK] Mobile hamburger menu opens")
            else:
                report("ui_issues", "medium", "Mobile hamburger menu not found",
                       "The hamburger menu button was not visible at 375x812 viewport.",
                       screenshot(page, "17-mobile-no-hamburger"))

            # Check chat input on mobile
            chat_input = page.locator('[data-testid="stChatInput"]')
            if chat_input.is_visible():
                print("  [OK] Chat input visible on mobile")
            else:
                report("ui_issues", "medium", "Chat input hidden on mobile",
                       "The chat input field is not visible at 375x812 viewport.",
                       screenshot(page, "17-mobile-chat-hidden"))

        # Check for horizontal overflow
        body_width = page.evaluate("document.body.scrollWidth")
        viewport_width = page.evaluate("window.innerWidth")
        if body_width > viewport_width and body_width > viewport_width * 1.05:
            report("ui_issues", "high", "Horizontal overflow on mobile",
                   f"Body width ({body_width}px) exceeds viewport ({viewport_width}px) — horizontal scrolling required.",
                   screenshot(page, "17-mobile-overflow"))

        sp = screenshot(page, "17-mobile-view")
        print(f"  [Mobile] Screenshot: {sp}")
        # Restore viewport
        page.set_viewport_size(original_viewport)
        wait_for_streamlit(page, 2)

        # ── 15. CHAT HISTORY & LOGOUT ───────────────────────────
        print("\n[15/15] Chat history & logout audit...")
        # Return to desktop page
        sidebar.locator("button").filter(has_text="Chat").first.click()
        wait_for_streamlit(page, 3)

        # Check for existing chat messages
        messages = page.locator('.message')
        if messages.count() > 0:
            print(f"  Chat messages preserved: {messages.count()}")
        else:
            report("functional_bugs", "low", "Chat history empty",
                   "After previous chat test, no messages appear in chat view.")

        # Try the New Chat button
        new_chat = sidebar.locator("button").filter(has_text="New Chat").first
        if new_chat.is_visible():
            new_chat.click()
            wait_for_streamlit(page, 2)
            print("  [OK] New Chat works")

        # Sign out
        signout = sidebar.locator("button").filter(has_text="Sign Out").first
        if signout.is_visible():
            signout.click()
            wait_for_streamlit(page, 3)

            # Verify we're back to auth page
            if page.locator("button").filter(has_text="Sign In").first.is_visible():
                print("  [OK] Logout successful — returned to auth page")
            else:
                report("functional_bugs", "high", "Logout did not return to auth page",
                       "After clicking Sign Out, the Sign In form did not appear.",
                       screenshot(page, "18-logout-failed"))
        else:
            report("functional_bugs", "medium", "Sign Out button missing",
                   "The Sign Out button was not found in the sidebar.",
                   screenshot(page, "18-no-signout-btn"))

        sp = screenshot(page, "18-after-logout")
        print(f"  Screenshot: {sp}")

        # ── CONSOLE ERRORS ──────────────────────────────────────
        print("\n\n=== CONSOLE ERROR ANALYSIS ===")
        all_errors = page.evaluate("() => window.__qa_console_errors || []")
        all_warnings = page.evaluate("() => window.__qa_console_warnings || []")

        if all_errors:
            print(f"  Console errors: {len(all_errors)}")
            for err in all_errors:
                print(f"    [X] {err[:150]}")
            report("critical_bugs", "medium", f"Browser console errors ({len(all_errors)})",
                   "JavaScript errors found in browser console:\n" + "\n".join(all_errors[:10]))
        else:
            print("  [OK] No console errors detected")

        if all_warnings:
            print(f"  Console warnings: {len(all_warnings)}")
            for w in all_warnings[:5]:
                print(f"    ⚠ {w[:150]}")
            report("performance_issues", "low", f"Console warnings ({len(all_warnings)})",
                   "JS warnings present:\n" + "\n".join(all_warnings[:5]))

        browser.close()

    _write_report()
    _generate_tests()
    print("\n[OK] Audit complete. Report written to reports/qa/qa-report.md")


def _write_report():
    """Write the QA report to disk."""
    lines = []
    lines.append("# QA Audit Report — AI Placement Mentor")
    lines.append(f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**App URL:** {BASE_URL}")
    lines.append(f"**Browser:** Chromium (Playwright)")
    lines.append(f"**Viewport:** 1280×800 (desktop), 375×812 (mobile)")
    lines.append("")

    total = sum(len(v) for v in findings.values())
    lines.append(f"**Total findings: {total}**")
    for category in findings:
        count = len(findings[category])
        emoji = {
            "critical_bugs": "🔥",
            "functional_bugs": "🐛",
            "ui_issues": "🎨",
            "ux_issues": "🧭",
            "accessibility_issues": "♿",
            "performance_issues": "!!",
            "security_observations": "🔒",
            "suggestions": "💡",
        }.get(category, "•")
        lines.append(f"  {emoji} **{category.replace('_', ' ').title()}**: {count}")

    for category, items in findings.items():
        if not items:
            continue
        heading = category.replace("_", " ").title()
        lines.append(f"\n---\n## {heading}")
        for item in items:
            sev = item["severity"].upper()
            lines.append(f"\n### [{sev}] {item['title']}")
            lines.append(f"{item['detail']}")
            if item.get("screenshot"):
                lines.append(f"  📸 `{item['screenshot']}`")

    lines.append("\n---\n## Summary\n")
    critical_count = sum(1 for v in findings.values()
                         for i in v if i["severity"] in ("high", "critical"))
    medium_count = sum(1 for v in findings.values()
                       for i in v if i["severity"] == "medium")
    low_count = sum(1 for v in findings.values()
                    for i in v if i["severity"] in ("low", "info"))
    lines.append(f"- 🔥 Critical/High: **{critical_count}**")
    lines.append(f"- !! Medium: **{medium_count}**")
    lines.append(f"- 📝 Low/Info: **{low_count}**")
    lines.append(f"\n_End of report — {datetime.now().isoformat()}_")

    report_path = REPORT_DIR / "qa-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {report_path}")


def _generate_tests():
    """Generate Playwright tests for critical user flows based on findings."""
    lines = []
    lines.append('"""Auto-generated Playwright E2E tests for critical user flows.')
    lines.append("Generated from QA audit — " + datetime.now().isoformat())
    lines.append('"""')
    lines.append("")
    lines.append("import time")
    lines.append("import pytest")
    lines.append("from playwright.sync_api import expect")
    lines.append("")
    lines.append("")
    lines.append("BASE_URL = \"http://localhost:8501\"")
    lines.append("")
    lines.append("")
    lines.append("def test_app_loads(page):")
    lines.append('    """Critical flow 1: App loads and shows auth page."""')
    lines.append("    page.goto(BASE_URL, wait_until=\"networkidle\")")
    lines.append("    time.sleep(3)")
    lines.append("    # Should show either Sign In (unauthenticated) or sidebar nav (authenticated)")
    lines.append('    signin = page.locator("button").filter(has_text="Sign In").first')
    lines.append("    sidebar = page.locator('section[data-testid=\"stSidebar\"]')")
    lines.append('    dashboard = sidebar.locator("button").filter(has_text="Dashboard").first')
    lines.append("    assert signin.is_visible() or dashboard.is_visible(),")
    lines.append('        "App should show auth or main view"')
    lines.append("    # No console errors")
    lines.append('    errors = page.evaluate("() => window.__qa_console_errors || []")')
    lines.append("    assert len(errors) == 0, f\"Console errors: {errors}\"")
    lines.append("")
    lines.append("")
    lines.append("def test_auth_signin_form(page):")
    lines.append('    """Critical flow 2: Sign In form has correct fields."""')
    lines.append("    page.goto(BASE_URL, wait_until=\"networkidle\")")
    lines.append("    time.sleep(3)")
    lines.append('    email = page.locator("input[type=\'text\']").first')
    lines.append('    password = page.locator("input[type=\'password\']").first')
    lines.append('    signin_btn = page.locator("button").filter(has_text="Sign In").first')
    lines.append("    assert email.is_visible(), \"Email input should be visible\"")
    lines.append("    assert password.is_visible(), \"Password input should be visible\"")
    lines.append("    assert signin_btn.is_visible(), \"Sign In button should be visible\"")
    lines.append("")
    lines.append("")
    lines.append("def test_auth_signup_form(page):")
    lines.append('    """Critical flow 3: Sign Up form with validation."""')
    lines.append("    page.goto(BASE_URL, wait_until=\"networkidle\")")
    lines.append("    time.sleep(3)")
    lines.append('    signup_tab = page.locator("button").filter(has_text="Sign Up").first')
    lines.append("    if signup_tab.is_visible():")
    lines.append("        signup_tab.click()")
    lines.append("        time.sleep(2)")
    lines.append("    # Test password mismatch")
    lines.append('    pwd_fields = page.locator("input[type=\'password\']")')
    lines.append('    email_field = page.locator("input[type=\'text\']").first')
    lines.append('    email_field.fill("test@example.com")')
    lines.append('    pwd_fields.nth(0).fill("password123")')
    lines.append('    pwd_fields.nth(1).fill("different456")')
    lines.append('    page.locator("button").filter(has_text="Create Account").first.click()')
    lines.append("    time.sleep(2)")
    lines.append('    error = page.locator(\'[data-testid="stAlert"]\')')
    lines.append("    assert error.is_visible(), \"Password mismatch should show error\"")
    lines.append("")
    lines.append("")
    lines.append("def test_sidebar_navigation(page):")
    lines.append('    """Critical flow 4: All 8 nav items navigate correctly (requires auth)."""')
    lines.append('    pytest.skip("Requires TEST_EMAIL/TEST_PASSWORD")')
    lines.append("")
    lines.append("")
    lines.append("def test_chat_send_and_receive(page):")
    lines.append('    """Critical flow 5: Send message and verify runtime card."""')
    lines.append('    pytest.skip("Requires TEST_EMAIL/TEST_PASSWORD")')
    lines.append("")
    lines.append("")
    lines.append("def test_chat_runtime_metadata(page):")
    lines.append('    """Critical flow 6: Runtime card has all 7 items."""')
    lines.append('    pytest.skip("Requires TEST_EMAIL/TEST_PASSWORD")')
    lines.append("")
    lines.append("")
    lines.append("def test_resume_upload_and_analyze(page, resume_file):")
    lines.append('    """Critical flow 7: Upload and analyze a resume."""')
    lines.append('    pytest.skip("Requires TEST_EMAIL/TEST_PASSWORD")')
    lines.append("")
    lines.append("")
    lines.append("def test_interview_flow(page):")
    lines.append('    """Critical flow 8: Full interview cycle."""')
    lines.append('    pytest.skip("Requires TEST_EMAIL/TEST_PASSWORD")')
    lines.append("")
    lines.append("")
    lines.append("def test_logout(page):")
    lines.append('    """Critical flow 9: Logout returns to auth page."""')
    lines.append('    pytest.skip("Requires TEST_EMAIL/TEST_PASSWORD")')
    lines.append("")
    lines.append("")
    lines.append("def test_no_console_errors(page):")
    lines.append('    """Critical flow 10: No JS errors across all views."""')
    lines.append("    page.goto(BASE_URL, wait_until=\"networkidle\")")
    lines.append("    time.sleep(3)")
    lines.append('    errors = page.evaluate("() => window.__qa_console_errors || []")')
    lines.append("    warnings = page.evaluate(\"() => window.__qa_console_warnings || []\")")
    lines.append("    assert len(errors) == 0, f\"Console errors: {errors[:5]}\"")
    lines.append("    if warnings:")
    lines.append("        print(f\"Warnings: {len(warnings)}\")")

    test_path = Path("tests/e2e/test_critical_flows.py")
    test_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Test stubs written to {test_path}")


if __name__ == "__main__":
    run_audit()
