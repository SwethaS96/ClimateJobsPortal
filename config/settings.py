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

def _parse_email_max_notifications(raw: str | None) -> int | None:
    """Optional cap on how many notifications one digest email includes.

    Unset, blank, or one of the explicit "unlimited" spellings -> None,
    meaning the digest includes every pending (email_sent=0) notification,
    no matter how many there are. A positive integer still works if a cap
    is ever wanted again later. Notifications beyond an active cap are
    left with email_sent=0 and picked up by the next run — never silently
    discarded either way.
    """
    value = (raw or "").strip().lower()
    if value in ("", "unlimited", "none", "0", "-1"):
        return None
    return int(value)


EMAIL_MAX_NOTIFICATIONS = _parse_email_max_notifications(os.environ.get("EMAIL_MAX_NOTIFICATIONS"))
