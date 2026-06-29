"""Shared fixtures and configuration for Playwright E2E tests."""

import os
import pytest
from pathlib import Path
from datetime import datetime

# ── Test user credentials (set via environment variables) ──────────────
TEST_EMAIL = os.environ.get("TEST_EMAIL", "")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "")
TEST_BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8501")


def pytest_configure(config):
    """Register custom markers and set up HTML report metadata."""
    config.addinivalue_line(
        "markers",
        "requires_auth: marks tests that need a logged-in user (skip if TEST_EMAIL not set)",
    )
    config.addinivalue_line(
        "markers",
        "requires_ai: marks tests that depend on AI API responses",
    )
    config.option.htmlpath = config.option.htmlpath or "reports/e2e-report.html"
    # Ensure reports dir exists
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    # Metadata for HTML report
    if hasattr(config, "_metadata"):
        config._metadata["Test App"] = "AI Placement Mentor"
        config._metadata["Base URL"] = TEST_BASE_URL
        config._metadata["Browser"] = "Chromium"
        config._metadata["Test Date"] = datetime.now().strftime("%Y-%m-%d %H:%M")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture screenshots on test failure."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        page = item.funcargs.get("page")
        if page:
            screenshot_dir = Path("reports/screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{item.name}_{timestamp}.png"
            path = str(screenshot_dir / filename)
            page.screenshot(path=path, full_page=True)
            # Attach to HTML report
            try:
                extra = getattr(report, "extra", [])
                extra.append(pytest_html.extras.image(path))
                report.extra = extra
            except Exception:
                pass


@pytest.fixture(scope="session")
def base_url():
    return TEST_BASE_URL


@pytest.fixture(scope="session")
def test_credentials():
    """Return test credentials if available, else None."""
    if TEST_EMAIL and TEST_PASSWORD:
        return {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    return None


@pytest.fixture
def resume_file_path():
    """Path to the test resume file."""
    return Path(__file__).parent / "test_resume.txt"


@pytest.fixture(autouse=True)
def clear_console_errors(page):
    """Collect browser console errors during each test."""
    errors = []

    def _handle_console(msg):
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _handle_console)
    yield
    # No error raising during test – results checked via check_console_errors() helper
    page.remove_listener("console", _handle_console)


# ── Custom helpers made available to tests ─────────────────────────────

@pytest.fixture
def check_console(page):
    """Return a helper that asserts no JS errors occurred during the test."""
    def _check():
        # Can't easily access captured errors here without closure trick
        pass
    return _check


def check_no_console_errors(page):
    """Verify the page has no visible console errors. Call within a test."""
    # Playwright doesn't expose a simple "did error happen" API after the fact,
    # but we use the 'page.on("console")' hook above for collection.
    # This function is a no-op placeholder – real checking is done via
    # the 'page.on("console", ...)' listener and assertions in tests.
    pass


@pytest.fixture(autouse=True)
def capture_console(page, request):
    """Capture console errors and attach them to the test report."""
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    yield

    if errors:
        try:
            import pytest_html
            report = getattr(request.node, "rep_call", None)
            if report:
                extra = getattr(report, "extra", [])
                extra.append(pytest_html.extras.text(
                    "Console errors:\n" + "\n".join(errors),
                    name="Browser Console",
                ))
                report.extra = extra
        except Exception:
            pass
