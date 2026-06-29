<#
.SYNOPSIS
  Run Playwright E2E tests for the AI Placement Mentor Streamlit app.

.DESCRIPTION
  Runs the full test suite and generates an HTML report.
  Requires the Streamlit app to be running at $TEST_BASE_URL (default http://localhost:8501).

.PARAMETER AuthOnly
  Run only auth-requiring tests (requires TEST_EMAIL / TEST_PASSWORD).

.PARAMETER Suite
  Run a specific test class: App, Auth, Nav, Dashboard, Chat, Resume, Interview,
  Career, Metadata, Memory, Sidebar, Buttons, Logout, UX.

.PARAMETER Headed
  Run browser in headed mode (visible).

.PARAMETER SlowMo
  Slow down Playwright by N milliseconds between actions.

.EXAMPLE
  .\run_e2e_tests.ps1
  .\run_e2e_tests.ps1 -Headed -SlowMo 100
  .\run_e2e_tests.ps1 -Suite Auth -Headed
  $env:TEST_EMAIL="user@example.com"; $env:TEST_PASSWORD="pass"; .\run_e2e_tests.ps1
#>

param(
    [switch]$AuthOnly,
    [string]$Suite = "",
    [switch]$Headed,
    [int]$SlowMo = 0
)

$REPORT_DIR = "reports"
$null = New-Item -ItemType Directory -Force -Path $REPORT_DIR

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportFile = Join-Path $REPORT_DIR "e2e-report_$timestamp.html"

# Build pytest args
$pytestArgs = @(
    "tests/e2e/test_app.py",
    "--html=`"$reportFile`"",
    "--self-contained-html",
    "--capture=sys",
    "-v"
)

# Marker filters
if ($AuthOnly) {
    $pytestArgs += "-m", "requires_auth"
}

if ($Suite) {
    $classMap = @{
        "App"       = "TestAppLoad"
        "Auth"      = "TestAuth"
        "Nav"       = "TestSidebarNavigation"
        "Dashboard" = "TestDashboard"
        "Chat"      = "TestChat"
        "Resume"    = "TestResume"
        "Interview" = "TestInterview"
        "Career"    = "TestCareer"
        "Metadata"  = "TestRuntimeMetadata"
        "Memory"    = "TestMemory"
        "Sidebar"   = "TestSidebarInteractions"
        "Buttons"   = "TestAllButtons"
        "Logout"    = "TestLogout"
        "UX"        = "TestUISuggestions"
    }
    $className = $classMap[$Suite]
    if ($className) {
        $pytestArgs[-1] = "tests/e2e/test_app.py::$className"
    }
}

# Browser options
$browserOpts = @()
if ($Headed) {
    $browserOpts += "--headed"
}
if ($SlowMo -gt 0) {
    $browserOpts += "--slowmo", $SlowMo
}
$pytestArgs += $browserOpts

Write-Host "=" x 60
Write-Host "  AI Placement Mentor — Playwright E2E Tests"
Write-Host "  Report: $reportFile"
Write-Host "=" x 60
Write-Host ""
Write-Host "> python -m pytest $($pytestArgs -join ' ')"
Write-Host ""

python -m pytest @pytestArgs

$exitCode = $LASTEXITCODE
Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "✓ All tests passed!" -ForegroundColor Green
} else {
    Write-Host "✗ Tests completed with failures (exit code: $exitCode)" -ForegroundColor Red
}
Write-Host "  Report: file:///$(Resolve-Path $reportFile)" -ForegroundColor Cyan
exit $exitCode
