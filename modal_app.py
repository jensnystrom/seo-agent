"""
Modal App — Villalife SEO Agent
Kör orchestrator dagligen kl 06:00 svensk tid.
Deploy: modal deploy modal_app.py
"""

import modal
import os
import sys

app = modal.App("villalife-seo-agent")

# Bygg image med alla dependencies + lokal kod
image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install(
        "google-auth",
        "google-auth-httplib2",
        "google-api-python-client",
        "gspread",
        "openai",
        "requests",
        "python-dotenv",
        "resend",
    )
    .add_local_dir("tools", remote_path="/app/tools")
    .add_local_dir("credentials", remote_path="/app/credentials")
)

secrets = modal.Secret.from_name("villalife-secrets")


@app.function(
    image=image,
    secrets=[secrets],
    schedule=modal.Cron("0 5 * * *"),  # 06:00 svensk tid (UTC+1)
    timeout=1800,
)
def run_daily():
    """Daglig körning — hämtar GSC, auditerar, skriver artiklar."""
    os.chdir("/app")
    sys.path.insert(0, "/app/tools")

    # Sätt env vars som förväntas av tools
    os.environ.setdefault("GSC_SERVICE_ACCOUNT_FILE", "/app/credentials/gsc_service_account.json")

    from orchestrator import main as orchestrator_main
    sys.argv = ["orchestrator.py"]
    orchestrator_main()


@app.function(
    image=image,
    secrets=[secrets],
    schedule=modal.Cron("0 8 * * 1"),  # Måndag 09:00
    timeout=300,
)
def send_weekly_report():
    """Skickar weekly report varje måndag."""
    os.chdir("/app")
    sys.path.insert(0, "/app/tools")
    os.environ.setdefault("GSC_SERVICE_ACCOUNT_FILE", "/app/credentials/gsc_service_account.json")

    from orchestrator import send_weekly_report as send_report
    send_report()


@app.local_entrypoint()
def test_run():
    """Test: modal run modal_app.py"""
    run_daily.remote()
