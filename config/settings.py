import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = Path("data/database/climate_jobs.db")

# Email digest configuration. Never hard-code credentials/addresses here —
# all of this comes from the environment (a local .env file is gitignored;
# see .env.example for the expected variable names).
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = [address.strip() for address in os.environ.get("EMAIL_TO", "").split(",") if address.strip()]

# Safety cap on how many notifications one digest email will include.
# Notifications beyond this limit are left with email_sent=False and picked
# up by the next run — never silently discarded.
EMAIL_MAX_NOTIFICATIONS = int(os.environ.get("EMAIL_MAX_NOTIFICATIONS", "200"))
