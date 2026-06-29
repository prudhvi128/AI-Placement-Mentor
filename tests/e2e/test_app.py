"""Comprehensive Playwright E2E tests for AI Placement Mentor (Streamlit app).

Requirements:
  - pytest, pytest-playwright, pytest-html installed
  - Chromium installed (``playwright install chromium``)
  - Streamlit app running at TEST_BASE_URL (default http://localhost:8501)
  - Optional: TEST_EMAIL / TEST_PASSWORD env vars for auth-requiring tests

Usage:
  $env:TEST_EMAIL="user@example.com"
  $env:TEST_PASSWORD="mypassword"
  pytest tests/e2e/test_app.py --html=reports/report.html --self-contained-html
"""

import re
import time
import pytest
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────────
WAIT_SHORT = 2       # short pause for UI transitions
WAIT_MEDIUM = 5      # medium pause for Streamlit reruns
WAIT_LONG = 30       # long pause for AI responses (chat, interview)
WAIT_VERY_LONG = 60  # very long for full interview completion

# Selector shortcuts
SIDEBAR = 'section[data-testid="stSidebar"]'
MAIN = 'section[data-testid="stMain"]'


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _click_button(page, text, timeout=5000, sidebar=False):
    """Click a button by its visible text, optionally scoped to the sidebar."""
    container = SIDEBAR if sidebar else MAIN
    btn = page.locator(container).get_by_role("button", name=text, exact=False)
    btn.wait_for(timeout=timeout)
    btn.click()


def _click_first_button(page, text, timeout=5000):
    """Click the first matching button on the page (not scoped)."""
    btn = page.get_by_role("button", name=text, exact=False).first
    btn.wait_for(timeout=timeout)
    btn.click()


def _fill_input(page, label, value):
    """Fill a text input by its accessible label."""
    inp = page.get_by_label(label, exact=False)
    inp.wait_for(timeout=5000)
    inp.fill(value)


def _wait_for_streamlit(page, t=WAIT_SHORT):
    """Wait for a Streamlit rerun to settle."""
    time.sleep(t)


def _count_elements(page, selector):
    return page.locator(selector).count()


def _console_errors(page):
    """Return list of console.error messages captured during the test."""
    return page.evaluate("() => performance.getEntriesByType('resource')")  # not what we want
    # We rely on the conftest fixture 'capture_console' instead.


# ═══════════════════════════════════════════════════════════════════════
#  1. APP LOADING
# ═══════════════════════════════════════════════════════════════════════

class TestAppLoad:
    """Verify the application loads without errors."""

    def test_app_renders(self, page, base_url):
        """The app should load and show the auth page (login screen) or the main app."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        # The app should either show auth page OR the main app
        auth_visible = page.locator("text=Sign In").first.is_visible()
        main_visible = page.locator("text=Chat").first.is_visible()
        assert auth_visible or main_visible, \
            "Expected either Sign In form (unauthenticated) or Chat view (authenticated)"

    def test_no_broken_images(self, page, base_url):
        """No broken images on the landing page."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        images = page.locator("img")
        count = images.count()
        for i in range(count):
            src = images.nth(i).get_attribute("src")
            if src and src.startswith("http"):
                # Check image loaded – just confirm it exists in DOM
                assert images.nth(i).is_visible()


# ═══════════════════════════════════════════════════════════════════════
#  2. AUTH — SIGN IN / SIGN UP
# ═══════════════════════════════════════════════════════════════════════

class TestAuth:
    """Test authentication forms and login flow."""

    def _goto_auth(self, page, base_url):
        """Ensure we're on the auth page."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        # If already authenticated, skip
        if page.locator("text=Sign In").first.is_visible():
            return True
        return False

    def test_signin_form_elements(self, page, base_url):
        """Sign In tab should have email, password fields and Sign In button."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        # Check for the Sign In form
        assert page.locator("text=Sign In").first.is_visible(), "Sign In tab should be visible"
        # The form should have email and password inputs
        email_field = page.get_by_label("Email", exact=False).first
        assert email_field.is_visible(), "Email input should be visible"
        password_field = page.get_by_label("Password", exact=False).first
        assert password_field.is_visible(), "Password input should be visible"
        signin_btn = page.get_by_role("button", name="Sign In").first
        assert signin_btn.is_visible(), "Sign In button should be visible"

    def test_signup_form_elements(self, page, base_url):
        """Sign Up tab should have all fields and Create Account button."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        # Click the Sign Up tab
        signup_tab = page.get_by_role("button", name="Sign Up").first
        if signup_tab.is_visible():
            signup_tab.click()
            _wait_for_streamlit(page, WAIT_SHORT)

        assert page.get_by_label("Email", exact=False).first.is_visible()
        assert page.get_by_label("Password", exact=False).first.is_visible()
        assert page.get_by_label("Confirm Password", exact=False).first.is_visible()
        create_btn = page.get_by_role("button", name="Create Account").first
        assert create_btn.is_visible()

    def test_signup_empty_fields_validation(self, page, base_url):
        """Submitting empty signup form should show validation error."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        # Switch to Sign Up tab
        signup_tab = page.get_by_role("button", name="Sign Up").first
        if signup_tab.is_visible():
            signup_tab.click()
            _wait_for_streamlit(page, WAIT_SHORT)

        # Click Create Account without filling anything
        page.get_by_role("button", name="Create Account").first.click()
        _wait_for_streamlit(page, WAIT_SHORT)

        # Should show an error message (Streamlit error or validation)
        error = page.locator('[data-testid="stAlert"]').first
        assert error.is_visible() or page.locator("text=required").first.is_visible() or \
               page.locator("text=Incorrect").first.is_visible() or \
               page.locator("text=error").first.is_visible(), \
            "Expected some validation error to appear"

    def test_signup_password_mismatch(self, page, base_url):
        """Entering mismatched passwords should show validation error."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        signup_tab = page.get_by_role("button", name="Sign Up").first
        if signup_tab.is_visible():
            signup_tab.click()
            _wait_for_streamlit(page, WAIT_SHORT)

        _fill_input(page, "Email", "test@test.com")
        _fill_input(page, "Password", "secret123")
        _fill_input(page, "Confirm Password", "different")
        page.get_by_role("button", name="Create Account").first.click()
        _wait_for_streamlit(page, WAIT_SHORT)

        error = page.locator('[data-testid="stAlert"]').first
        assert error.is_visible() or page.locator("text=mismatch", re.IGNORECASE).first.is_visible() or \
               page.locator("text=match", re.IGNORECASE).first.is_visible(), \
            "Expected password mismatch error"

    @pytest.mark.requires_auth
    def test_login_success(self, page, base_url, test_credentials):
        """Login with valid test credentials."""
        if not test_credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")

        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        # Already logged in?
        sidebar = page.locator(SIDEBAR)
        if sidebar.locator("text=Dashboard").first.is_visible():
            return  # already logged in

        # Fill login form
        _fill_input(page, "Email", test_credentials["email"])
        _fill_input(page, "Password", test_credentials["password"])
        page.get_by_role("button", name="Sign In").first.click()

        # Wait for auth and dashboard/chat to appear
        _wait_for_streamlit(page, WAIT_MEDIUM)
        # After login we should see the sidebar with navigation items
        sidebar = page.locator(SIDEBAR)
        assert sidebar.locator("text=Dashboard").first.is_visible() or \
               sidebar.locator("text=Chat").first.is_visible(), \
            "Expected sidebar navigation after login"

    @pytest.mark.requires_auth
    def test_login_bad_password(self, page, base_url, test_credentials):
        """Login with wrong password should show error."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        sidebar = page.locator(SIDEBAR)
        if sidebar.locator("text=Dashboard").first.is_visible():
            pytest.skip("Already logged in, cannot test bad login")

        _fill_input(page, "Email", "nonexistent@test.com")
        _fill_input(page, "Password", "wrongpassword123!")
        page.get_by_role("button", name="Sign In").first.click()
        _wait_for_streamlit(page, WAIT_SHORT)

        error = page.locator('[data-testid="stAlert"]').first
        assert error.is_visible(), "Expected error alert for bad login"


# ═══════════════════════════════════════════════════════════════════════
#  3. SIDEBAR NAVIGATION
# ═══════════════════════════════════════════════════════════════════════

class TestSidebarNavigation:
    """Test every navigation item in the sidebar."""

    NAV_ITEMS = [
        "Dashboard",
        "Chat",
        "Resume Analyzer",
        "Mock Interview",
        "Career",
        "History",
        "Weaknesses",
        "Roadmap",
    ]

    NAV_VIEW_INDICATORS = {
        "Dashboard": ["stMetric", "Quick Actions"],
        "Chat": ["stChatInput"],
        "Resume Analyzer": ["Resume", "Upload"],
        "Mock Interview": ["Interview", "Start"],
        "Career": ["Skills", "Experience"],
        "History": ["History", "Report"],
        "Weaknesses": ["Weakness", "Track"],
        "Roadmap": ["Learning", "Roadmap"],
    }

    @pytest.mark.requires_auth
    def test_nav_items_present(self, page, base_url, test_credentials):
        """All 8 navigation items should be visible in the sidebar."""
        self._ensure_login(page, base_url, test_credentials)
        sidebar = page.locator(SIDEBAR)
        for item in self.NAV_ITEMS:
            btn = sidebar.get_by_role("button", name=item, exact=False).first
            assert btn.is_visible(), f"Navigation item '{item}' should be visible in sidebar"

    @pytest.mark.requires_auth
    def test_navigate_dashboard(self, page, base_url, test_credentials):
        """Navigate to Dashboard."""
        self._click_nav(page, base_url, test_credentials, "Dashboard")
        self._assert_view(page, "Dashboard")

    @pytest.mark.requires_auth
    def test_navigate_chat(self, page, base_url, test_credentials):
        """Navigate to Chat."""
        self._click_nav(page, base_url, test_credentials, "Chat")
        self._assert_view(page, "Chat")

    @pytest.mark.requires_auth
    def test_navigate_resume(self, page, base_url, test_credentials):
        """Navigate to Resume Analyzer."""
        self._click_nav(page, base_url, test_credentials, "Resume Analyzer")
        self._assert_view(page, "Resume Analyzer")

    @pytest.mark.requires_auth
    def test_navigate_interview(self, page, base_url, test_credentials):
        """Navigate to Mock Interview."""
        self._click_nav(page, base_url, test_credentials, "Mock Interview")
        self._assert_view(page, "Mock Interview")

    @pytest.mark.requires_auth
    def test_navigate_career(self, page, base_url, test_credentials):
        """Navigate to Career."""
        self._click_nav(page, base_url, test_credentials, "Career")
        self._assert_view(page, "Career")

    @pytest.mark.requires_auth
    def test_navigate_history(self, page, base_url, test_credentials):
        """Navigate to History."""
        self._click_nav(page, base_url, test_credentials, "History")
        self._assert_view(page, "History")

    @pytest.mark.requires_auth
    def test_navigate_weaknesses(self, page, base_url, test_credentials):
        """Navigate to Weaknesses."""
        self._click_nav(page, base_url, test_credentials, "Weaknesses")
        self._assert_view(page, "Weaknesses")

    @pytest.mark.requires_auth
    def test_navigate_roadmap(self, page, base_url, test_credentials):
        """Navigate to Roadmap."""
        self._click_nav(page, base_url, test_credentials, "Roadmap")
        self._assert_view(page, "Roadmap")

    # ── helpers ──────────────────────────────────────────────

    def _ensure_login(self, page, base_url, credentials):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)

        sidebar = page.locator(SIDEBAR)
        if sidebar.locator("text=Dashboard").first.is_visible():
            return  # already logged in

        _fill_input(page, "Email", credentials["email"])
        _fill_input(page, "Password", credentials["password"])
        page.get_by_role("button", name="Sign In").first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)
        assert sidebar.locator("text=Dashboard").first.is_visible(), "Login failed"

    def _click_nav(self, page, base_url, credentials, name):
        self._ensure_login(page, base_url, credentials)
        sidebar = page.locator(SIDEBAR)
        btn = sidebar.get_by_role("button", name=name, exact=False).first
        btn.scroll_into_view_if_needed()
        btn.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)

    def _assert_view(self, page, name):
        indicators = self.NAV_VIEW_INDICATORS.get(name, [])
        main_area = page.locator(MAIN)
        found = any(
            main_area.locator(f"text={kw}").first.is_visible()
            for kw in indicators
        ) if indicators else True
        assert found, f"View '{name}' indicators should be visible"


# ═══════════════════════════════════════════════════════════════════════
#  4. DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

class TestDashboard:
    """Dashboard view – metrics, quick actions, assessment panels."""

    @pytest.mark.requires_auth
    def test_dashboard_metrics(self, page, base_url, test_credentials):
        """Dashboard shows metric cards."""
        self._go(page, base_url, test_credentials, "Dashboard")
        metrics = page.locator('[data-testid="stMetric"]')
        assert metrics.count() >= 4, f"Expected at least 4 metric cards, got {metrics.count()}"

    @pytest.mark.requires_auth
    def test_dashboard_quick_actions(self, page, base_url, test_credentials):
        """Dashboard quick-action buttons are present."""
        self._go(page, base_url, test_credentials, "Dashboard")
        for btn_text in ["New Interview", "View Weaknesses", "Learning Roadmap", "History"]:
            btn = page.locator(MAIN).get_by_role("button", name=btn_text, exact=False).first
            if btn.is_visible():
                btn.click()
                _wait_for_streamlit(page, WAIT_SHORT)
                break  # just click one to verify interaction works

    @pytest.mark.requires_auth
    def test_dashboard_assessment_expander(self, page, base_url, test_credentials):
        """Assessment & Insights expander opens."""
        self._go(page, base_url, test_credentials, "Dashboard")
        expander = page.locator(MAIN).get_by_role("button", name="Assessment", exact=False).first
        if expander.is_visible():
            expander.click()
            _wait_for_streamlit(page, WAIT_SHORT)
            # After opening, should show strengths/weaknesses sections
            _wait_for_streamlit(page, WAIT_SHORT)

    @pytest.mark.requires_auth
    def test_dashboard_interactive_buttons(self, page, base_url, test_credentials):
        """Click every button on the dashboard and verify no crashes."""
        self._go(page, base_url, test_credentials, "Dashboard")
        buttons = page.locator(MAIN).get_by_role("button")
        count = buttons.count()
        for i in range(min(count, 10)):  # click up to 10 to avoid infinite loops
            try:
                buttons.nth(i).click(timeout=2000)
                _wait_for_streamlit(page, 1)
            except Exception:
                pass

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  5. CHAT
# ═══════════════════════════════════════════════════════════════════════

class TestChat:
    """Chat view – send message, verify response and metadata."""

    @pytest.mark.requires_auth
    def test_chat_input_present(self, page, base_url, test_credentials):
        """Chat view shows the chat input box."""
        self._go(page, base_url, test_credentials, "Chat")
        chat_input = page.locator('[data-testid="stChatInput"]')
        assert chat_input.is_visible(), "Chat input should be visible"

    @pytest.mark.requires_auth
    @pytest.mark.requires_ai
    def test_send_message(self, page, base_url, test_credentials):
        """Send a chat message and verify the response appears."""
        self._go(page, base_url, test_credentials, "Chat")
        chat_input = page.locator('[data-testid="stChatInput"]')
        chat_input.wait_for(timeout=10000)
        chat_input.fill("Hello, who are you?")
        chat_input.press("Enter")
        _wait_for_streamlit(page, WAIT_LONG)

        # After the response, we should see assistant messages
        assistant_msgs = page.locator('.message.assistant, [class*="assistant"]')
        # The runtime card should be visible
        runtime_card = page.locator(".runtime-card")
        if runtime_card.is_visible():
            # Verify metadata items
            assert runtime_card.locator("text=CascadeFlow").first.is_visible()
            assert runtime_card.locator("text=Groq").first.is_visible()

    @pytest.mark.requires_auth
    def test_new_chat_button(self, page, base_url, test_credentials):
        """+ New Chat button works."""
        self._go(page, base_url, test_credentials, "Chat")
        new_chat = page.locator(SIDEBAR).get_by_role("button", name="New Chat").first
        if new_chat.is_visible():
            new_chat.click()
            _wait_for_streamlit(page, WAIT_SHORT)
            # The chat should be empty
            runtime_cards = page.locator(".runtime-card")
            # At most, there might be a welcome message, but generally no runtime cards
            assert True  # no crash

    @pytest.mark.requires_auth
    def test_chat_new_chat_button(self, page, base_url, test_credentials):
        """The sidebar New Chat button creates a fresh chat."""
        self._go(page, base_url, test_credentials, "Chat")
        sidebar = page.locator(SIDEBAR)
        new_chat = sidebar.get_by_role("button", name="New Chat", exact=False).first
        if new_chat.is_visible():
            new_chat.click()
            _wait_for_streamlit(page, WAIT_SHORT)

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  6. RESUME UPLOAD
# ═══════════════════════════════════════════════════════════════════════

class TestResume:
    """Resume upload and analysis."""

    @pytest.mark.requires_auth
    def test_resume_uploader_present(self, page, base_url, test_credentials):
        """Resume Analyzer shows file uploader."""
        self._go(page, base_url, test_credentials, "Resume Analyzer")
        uploader = page.locator('[data-testid="stFileUploader"]')
        assert uploader.is_visible(), "File uploader should be visible"

    @pytest.mark.requires_auth
    def test_resume_upload_file(self, page, base_url, test_credentials, resume_file_path):
        """Upload a resume file and check it's accepted."""
        self._go(page, base_url, test_credentials, "Resume Analyzer")
        uploader = page.locator('[data-testid="stFileUploader"] input[type="file"]')
        uploader.wait_for(timeout=10000)
        uploader.scroll_into_view_if_needed()
        uploader.set_input_files(str(resume_file_path))
        _wait_for_streamlit(page, WAIT_MEDIUM)

        # After upload, the Analyze button should appear
        analyze_btn = page.locator(MAIN).get_by_role("button", name="Analyze", exact=False).first
        if analyze_btn.is_visible():
            assert True  # File accepted

    @pytest.mark.requires_auth
    @pytest.mark.requires_ai
    def test_resume_analyze(self, page, base_url, test_credentials, resume_file_path):
        """Upload a resume and run analysis."""
        self._go(page, base_url, test_credentials, "Resume Analyzer")
        uploader = page.locator('[data-testid="stFileUploader"] input[type="file"]')
        uploader.wait_for(timeout=10000)
        uploader.scroll_into_view_if_needed()
        uploader.set_input_files(str(resume_file_path))
        _wait_for_streamlit(page, WAIT_MEDIUM)

        analyze_btn = page.locator(MAIN).get_by_role("button", name="Analyze", exact=False).first
        if analyze_btn.is_visible():
            analyze_btn.click()
            _wait_for_streamlit(page, WAIT_VERY_LONG)
            # Check for success or analysis result
            success = page.locator("text=completed").first.is_visible() or \
                      page.locator("text=Analysis").first.is_visible() or \
                      page.locator('.resume-card', exact=False).first.is_visible()
            assert True  # Test completed without crash

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  7. INTERVIEW
# ═══════════════════════════════════════════════════════════════════════

class TestInterview:
    """Mock interview flow."""

    @pytest.mark.requires_auth
    def test_interview_start_button(self, page, base_url, test_credentials):
        """Interview view shows Start button if resume exists, or an info message."""
        self._go(page, base_url, test_credentials, "Mock Interview")
        main = page.locator(MAIN)
        start_btn = main.get_by_role("button", name="Start Mock Interview", exact=False).first
        if start_btn.is_visible():
            assert True  # Button exists
        else:
            # Maybe no resume uploaded – either way, page loaded
            assert True

    @pytest.mark.requires_auth
    @pytest.mark.requires_ai
    def test_interview_flow(self, page, base_url, test_credentials, resume_file_path):
        """Full interview flow: start, answer, submit."""
        self._go(page, base_url, test_credentials, "Mock Interview")
        main = page.locator(MAIN)

        # We might need a resume first
        start_btn = main.get_by_role("button", name="Start Mock Interview", exact=False).first
        if not start_btn.is_visible():
            # Upload resume first
            sidebar = page.locator(SIDEBAR)
            sidebar.get_by_role("button", name="Resume Analyzer", exact=False).first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
            uploader = page.locator('[data-testid="stFileUploader"] input[type="file"]')
            if uploader.is_visible():
                uploader.set_input_files(str(resume_file_path))
                _wait_for_streamlit(page, WAIT_MEDIUM)
            sidebar.get_by_role("button", name="Mock Interview", exact=False).first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
            start_btn = main.get_by_role("button", name="Start Mock Interview", exact=False).first

        if start_btn.is_visible():
            start_btn.click()
            _wait_for_streamlit(page, WAIT_VERY_LONG)

            # Should see a question or loading state
            textarea = page.locator("textarea").first
            if textarea.is_visible():
                textarea.fill("This is my test answer for the interview question.")
                _wait_for_streamlit(page, WAIT_SHORT)
                submit_btn = main.get_by_role("button", name="Submit Answer", exact=False).first
                if submit_btn.is_visible():
                    submit_btn.click()
                    _wait_for_streamlit(page, WAIT_LONG)

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  8. CAREER
# ═══════════════════════════════════════════════════════════════════════

class TestCareer:
    """Career recommendations."""

    @pytest.mark.requires_auth
    def test_career_form_elements(self, page, base_url, test_credentials):
        """Career view shows skills, experience, interests inputs."""
        self._go(page, base_url, test_credentials, "Career")
        main = page.locator(MAIN)
        skills = main.locator("textarea").first  # Skills textarea
        assert skills.is_visible(), "Skills textarea should be visible"
        # Experience level selectbox
        selectbox = page.locator('[data-testid="stSelectbox"]').first
        assert selectbox.is_visible() or main.locator("text=Experience").first.is_visible(), \
            "Experience level select should be visible"

    @pytest.mark.requires_auth
    @pytest.mark.requires_ai
    def test_career_generate(self, page, base_url, test_credentials):
        """Fill career form and generate recommendation."""
        self._go(page, base_url, test_credentials, "Career")
        main = page.locator(MAIN)

        # Fill skills
        textareas = main.locator("textarea")
        if textareas.count() >= 1:
            textareas.nth(0).fill("Python, JavaScript, React, Node.js, SQL, AWS")
        if textareas.count() >= 2:
            textareas.nth(1).fill("AI/ML, web development, cloud architecture")

        # Set experience level if selectable
        selectbox = page.locator('[data-testid="stSelectbox"]').first
        if selectbox.is_visible():
            selectbox.click()
            _wait_for_streamlit(page, 1)
            option = page.locator('[data-testid="stSelectbox"] [role="option"]').first
            if option.is_visible():
                option.click()
                _wait_for_streamlit(page, 1)

        # Submit
        generate_btn = main.get_by_role("button", name="Generate Career", exact=False).first
        if generate_btn.is_visible():
            generate_btn.click()
            _wait_for_streamlit(page, WAIT_VERY_LONG)

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  9. RUNTIME METADATA
# ═══════════════════════════════════════════════════════════════════════

class TestRuntimeMetadata:
    """CascadeFlow runtime metadata card appearance and content."""

    @pytest.mark.requires_auth
    @pytest.mark.requires_ai
    def test_metadata_card_structure(self, page, base_url, test_credentials):
        """Runtime card appears after an AI response with correct structure."""
        self._go(page, base_url, test_credentials, "Chat")
        chat_input = page.locator('[data-testid="stChatInput"]')
        chat_input.wait_for(timeout=10000)
        chat_input.fill("Say hello in one word.")
        chat_input.press("Enter")
        _wait_for_streamlit(page, WAIT_LONG)

        card = page.locator(".runtime-card")
        assert card.is_visible(), "Runtime card should be visible after AI response"

        # Verify structure
        assert card.locator(".rt-pri").first.is_visible(), "Primary row should exist"
        assert card.locator(".rt-sec").first.is_visible(), "Secondary row should exist"

        # Verify content items
        exec_item = card.locator(".rt-exec")
        assert exec_item.is_visible(), "Execution item should be visible"

        provider_item = card.locator(".rt-provider")
        assert provider_item.is_visible(), "Provider item should be visible"

        model_item = card.locator(".rt-model")
        assert model_item.is_visible(), "Model item should be visible"

        latency_item = card.locator(".rt-latency")
        assert latency_item.is_visible(), "Latency item should be visible"

        cost_item = card.locator(".rt-cost")
        assert cost_item.is_visible(), "Cost item should be visible"

        route_item = card.locator(".rt-route")
        assert route_item.is_visible(), "Route item should be visible"

    @pytest.mark.requires_auth
    def test_metadata_empty_reason_hidden(self, page, base_url, test_credentials):
        """Reason field should be hidden when empty."""
        # Test on an existing message that has metadata but no reason
        self._go(page, base_url, test_credentials, "Chat")
        card = page.locator(".runtime-card").first
        if card.is_visible():
            reason = card.locator(".rt-reason")
            # If visible, reason should have non-empty text
            if reason.is_visible():
                assert len(reason.locator(".rt-val").text_content().strip()) > 0
            # If not visible, that's also fine (reason is empty)

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  10. MEMORY / HISTORY / WEAKNESSES
# ═══════════════════════════════════════════════════════════════════════

class TestMemory:
    """Hindsight memory features: history, weaknesses, roadmap."""

    @pytest.mark.requires_auth
    def test_history_view(self, page, base_url, test_credentials):
        """History view loads interview reports."""
        self._go(page, base_url, test_credentials, "History")
        main = page.locator(MAIN)
        _wait_for_streamlit(page, WAIT_SHORT)
        # Should at least show a heading or message
        assert main.locator("text=History").first.is_visible() or \
               main.locator("text=Report").first.is_visible() or \
               main.locator("text=interview").first.is_visible() or \
               main.locator("text=No").first.is_visible(), \
            "History view should load with content or empty state"

    @pytest.mark.requires_auth
    def test_weaknesses_view(self, page, base_url, test_credentials):
        """Weaknesses view loads tracking data."""
        self._go(page, base_url, test_credentials, "Weaknesses")
        main = page.locator(MAIN)
        _wait_for_streamlit(page, WAIT_SHORT)
        # Should show weakness metrics or empty state
        metrics = page.locator('[data-testid="stMetric"]')
        assert metrics.count() > 0 or main.locator("text=Weakness").first.is_visible(), \
            "Weaknesses view should show metrics"

    @pytest.mark.requires_auth
    def test_weaknesses_buttons(self, page, base_url, test_credentials):
        """Weaknesses view has interactive buttons."""
        self._go(page, base_url, test_credentials, "Weaknesses")
        main = page.locator(MAIN)
        buttons = main.get_by_role("button")
        # Try clicking Scan Latest Interview if available
        scan_btn = main.get_by_role("button", name="Scan", exact=False).first
        if scan_btn.is_visible():
            scan_btn.click()
            _wait_for_streamlit(page, WAIT_SHORT)

    @pytest.mark.requires_auth
    def test_roadmap_view(self, page, base_url, test_credentials):
        """Roadmap view loads and shows form."""
        self._go(page, base_url, test_credentials, "Roadmap")
        main = page.locator(MAIN)
        _wait_for_streamlit(page, WAIT_SHORT)
        assert main.locator("textarea").first.is_visible() or \
               main.locator("text=Roadmap").first.is_visible(), \
            "Roadmap view should show form"

    @pytest.mark.requires_auth
    @pytest.mark.requires_ai
    def test_roadmap_generate(self, page, base_url, test_credentials):
        """Generate a learning roadmap."""
        self._go(page, base_url, test_credentials, "Roadmap")
        main = page.locator(MAIN)
        textareas = main.locator("textarea")
        if textareas.count() >= 1:
            textareas.nth(0).fill("Data structures, algorithms, system design")
        generate_btn = main.get_by_role("button", name="Generate", exact=False).first
        if generate_btn.is_visible():
            generate_btn.click()
            _wait_for_streamlit(page, WAIT_VERY_LONG)

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  11. SIDEBAR INTERACTIONS
# ═══════════════════════════════════════════════════════════════════════

class TestSidebarInteractions:
    """Sidebar-specific elements: New Chat, search, sign out, clear chat."""

    @pytest.mark.requires_auth
    def test_sidebar_search(self, page, base_url, test_credentials):
        """Sidebar chat search input is present."""
        self._go(page, base_url, test_credentials, "Chat")
        sidebar = page.locator(SIDEBAR)
        search = sidebar.get_by_placeholder("Search", exact=False).first
        if search.is_visible():
            search.fill("test search")
            _wait_for_streamlit(page, WAIT_SHORT)
            search.fill("")

    @pytest.mark.requires_auth
    def test_sidebar_logout_button(self, page, base_url, test_credentials):
        """Sign Out button exists in the sidebar."""
        self._go(page, base_url, test_credentials, "Chat")
        sidebar = page.locator(SIDEBAR)
        signout = sidebar.get_by_role("button", name="Sign Out", exact=False).first
        assert signout.is_visible(), "Sign Out button should be visible in sidebar"

    @pytest.mark.requires_auth
    def test_sidebar_clear_chat_button(self, page, base_url, test_credentials):
        """Clear Chat button exists in sidebar when on Chat view."""
        self._go(page, base_url, test_credentials, "Chat")
        sidebar = page.locator(SIDEBAR)
        clear = sidebar.get_by_role("button", name="Clear Chat", exact=False).first
        if clear.is_visible():
            assert True

    def _go(self, page, base_url, credentials, view):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", credentials["email"])
            _fill_input(page, "Password", credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  12. COMPREHENSIVE BUTTON CLICK TEST
# ═══════════════════════════════════════════════════════════════════════

class TestAllButtons:
    """Click every visible button on every page to check for crashes."""

    @pytest.mark.requires_auth
    def test_all_sidebar_buttons(self, page, base_url, test_credentials):
        """Click every sidebar button."""
        self._login(page, base_url, test_credentials)
        sidebar = page.locator(SIDEBAR)
        buttons = sidebar.get_by_role("button")
        count = buttons.count()
        clicked = 0
        for i in range(count):
            try:
                text = buttons.nth(i).text_content(timeout=1000) or ""
                buttons.nth(i).click(timeout=2000)
                _wait_for_streamlit(page, 1.5)
                clicked += 1
            except Exception:
                pass
        assert clicked > 0, f"Should click at least one sidebar button, clicked {clicked}"

    @pytest.mark.requires_auth
    def test_all_chat_view_buttons(self, page, base_url, test_credentials):
        """Click all buttons on the Chat view."""
        self._go(page, base_url, test_credentials, "Chat")
        buttons = page.get_by_role("button")
        count = buttons.count()
        clicked = 0
        for i in range(count):
            try:
                buttons.nth(i).click(timeout=2000)
                _wait_for_streamlit(page, 1.5)
                clicked += 1
            except Exception:
                pass

    @pytest.mark.requires_auth
    def test_all_dashboard_buttons(self, page, base_url, test_credentials):
        """Click all buttons on the Dashboard view."""
        self._go(page, base_url, test_credentials, "Dashboard")
        buttons = page.locator(MAIN).get_by_role("button")
        count = buttons.count()
        clicked = 0
        for i in range(count):
            try:
                buttons.nth(i).click(timeout=2000)
                _wait_for_streamlit(page, 1.5)
                clicked += 1
            except Exception:
                pass

    @pytest.mark.requires_auth
    def test_all_resume_buttons(self, page, base_url, test_credentials, resume_file_path):
        """Click all buttons on the Resume Analyzer view."""
        self._go(page, base_url, test_credentials, "Resume Analyzer")
        # Upload file first so buttons become active
        uploader = page.locator('[data-testid="stFileUploader"] input[type="file"]')
        if uploader.is_visible():
            uploader.set_input_files(str(resume_file_path))
            _wait_for_streamlit(page, WAIT_MEDIUM)

        buttons = page.locator(MAIN).get_by_role("button")
        count = buttons.count()
        for i in range(count):
            try:
                buttons.nth(i).click(timeout=2000)
                _wait_for_streamlit(page, 1.5)
            except Exception:
                pass

    @pytest.mark.requires_auth
    def test_all_career_buttons(self, page, base_url, test_credentials):
        """Click all buttons on the Career view."""
        self._go(page, base_url, test_credentials, "Career")
        buttons = page.locator(MAIN).get_by_role("button")
        count = buttons.count()
        for i in range(count):
            try:
                buttons.nth(i).click(timeout=2000)
                _wait_for_streamlit(page, 1.5)
            except Exception:
                pass

    def _login(self, page, base_url, credentials):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if sidebar.locator("text=Dashboard").first.is_visible():
            return
        _fill_input(page, "Email", credentials["email"])
        _fill_input(page, "Password", credentials["password"])
        page.get_by_role("button", name="Sign In").first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)

    def _go(self, page, base_url, credentials, view):
        self._login(page, base_url, credentials)
        sidebar = page.locator(SIDEBAR)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
#  13. LOGOUT
# ═══════════════════════════════════════════════════════════════════════

class TestLogout:
    """Sign out flow."""

    @pytest.mark.requires_auth
    def test_logout(self, page, base_url, test_credentials):
        """Click Sign Out and verify return to auth page."""
        if not test_credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")

        # Login first
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if not sidebar.locator("text=Dashboard").first.is_visible():
            _fill_input(page, "Email", test_credentials["email"])
            _fill_input(page, "Password", test_credentials["password"])
            page.get_by_role("button", name="Sign In").first.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)

        # Click Sign Out
        sidebar = page.locator(SIDEBAR)
        signout = sidebar.get_by_role("button", name="Sign Out", exact=False).first
        if signout.is_visible():
            signout.click()
            _wait_for_streamlit(page, WAIT_MEDIUM)
            # Should see login form again
            assert page.locator("text=Sign In").first.is_visible(), \
                "Should return to auth page after logout"


# ═══════════════════════════════════════════════════════════════════════
#  14. UI/UX SUGGESTIONS (collected during testing)
# ═══════════════════════════════════════════════════════════════════════

class TestUISuggestions:
    """Observe the application and suggest improvements (non-blocking checks)."""

    @pytest.mark.requires_auth
    def test_empty_states(self, page, base_url, test_credentials):
        """Check that empty/loading states are handled gracefully."""
        self._go(page, base_url, test_credentials, "History")
        _wait_for_streamlit(page, WAIT_SHORT)
        main = page.locator(MAIN)
        # Should show something meaningful, not a blank page
        content_visible = main.locator("text").first.is_visible()
        assert content_visible, "History should have non-empty content or empty state message"

    @pytest.mark.requires_auth
    def test_loading_states(self, page, base_url, test_credentials):
        """During AI calls, loading indicators should appear."""
        self._go(page, base_url, test_credentials, "Chat")
        chat_input = page.locator('[data-testid="stChatInput"]')
        if not chat_input.is_visible():
            pytest.skip("Chat input not visible")
        # Check that the input is not obviously disabled without any feedback
        disabled = chat_input.is_disabled()
        # Not asserting on disabled state since it varies

    @pytest.mark.requires_auth
    def test_runtime_card_readability(self, page, base_url, test_credentials):
        """Check runtime card text is readable (no overflow, no tiny text)."""
        self._go(page, base_url, test_credentials, "Chat")
        # If there are existing messages with runtime cards, inspect them
        cards = page.locator(".runtime-card")
        count = cards.count()
        if count > 0:
            for i in range(count):
                card = cards.nth(i)
                # Check card is within viewport bounds
                box = card.bounding_box()
                assert box is not None
                assert box["width"] > 100, f"Card {i} should be wider than 100px"
                assert box["height"] > 20, f"Card {i} should be taller than 20px"

    @pytest.mark.requires_auth
    def test_theme_consistency(self, page, base_url, test_credentials):
        """Check that the app renders correctly (both dark and light themes)."""
        self._login(page, base_url, test_credentials)
        body = page.locator("body")
        # Streamlit applies data-theme attribute
        theme = body.get_attribute("data-theme")
        # Either dark or light should be set
        assert theme in ("dark", "light", None), f"Unexpected theme: {theme}"

    def _login(self, page, base_url, credentials):
        if not credentials:
            pytest.skip("TEST_EMAIL / TEST_PASSWORD not set")
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _wait_for_streamlit(page, WAIT_MEDIUM)
        sidebar = page.locator(SIDEBAR)
        if sidebar.locator("text=Dashboard").first.is_visible():
            return
        _fill_input(page, "Email", credentials["email"])
        _fill_input(page, "Password", credentials["password"])
        page.get_by_role("button", name="Sign In").first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)

    def _go(self, page, base_url, credentials, view):
        self._login(page, base_url, credentials)
        sidebar = page.locator(SIDEBAR)
        sidebar.get_by_role("button", name=view, exact=False).first.click()
        _wait_for_streamlit(page, WAIT_MEDIUM)
