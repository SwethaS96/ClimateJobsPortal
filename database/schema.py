import sqlite3
from sqlite3 import Connection

CREATE_ORGANIZATIONS_TABLE = '''
CREATE TABLE IF NOT EXISTS organizations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  short_name TEXT,
  homepage_url TEXT,
  country TEXT,
  state TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
'''

CREATE_WEBSITES_TABLE = '''
CREATE TABLE IF NOT EXISTS websites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INTEGER NOT NULL,
  page_name TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  parser_name TEXT NOT NULL DEFAULT 'generic_html',
  parser_metadata TEXT,
  user_agent TEXT,
  timeout_seconds INTEGER NOT NULL DEFAULT 30,
  scrape_interval_minutes INTEGER NOT NULL DEFAULT 60,
  is_enabled INTEGER NOT NULL DEFAULT 1,
  last_scraped TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);
'''

CREATE_NOTIFICATIONS_TABLE = '''
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INTEGER NOT NULL,
  website_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  notification_number TEXT,
  category TEXT,
  notification_date TEXT,
  application_deadline TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  page_url TEXT,
  hash TEXT NOT NULL UNIQUE,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  email_sent INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
  FOREIGN KEY (website_id) REFERENCES websites (id) ON DELETE CASCADE
);
'''

CREATE_PDF_DOCUMENTS_TABLE = '''
CREATE TABLE IF NOT EXISTS pdf_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notification_id INTEGER NOT NULL,
  document_type TEXT,
  pdf_url TEXT,
  local_file TEXT,
  checksum TEXT,
  downloaded INTEGER NOT NULL DEFAULT 0,
  downloaded_at TEXT,
  file_size INTEGER,
  http_status INTEGER,
  extracted_text TEXT,
  extraction_status TEXT,
  FOREIGN KEY (notification_id) REFERENCES notifications (id) ON DELETE CASCADE
);
'''

CREATE_NOTIFICATION_REVIEW_QUEUE_TABLE = '''
CREATE TABLE IF NOT EXISTS notification_review_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INTEGER NOT NULL,
  website_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  reason TEXT,
  classification TEXT NOT NULL,
  raw_html TEXT,
  metadata TEXT,
  hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  review_status TEXT NOT NULL DEFAULT 'PENDING',
  FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
  FOREIGN KEY (website_id) REFERENCES websites (id) ON DELETE CASCADE
);
'''

CREATE_SCRAPE_HISTORY_TABLE = '''
CREATE TABLE IF NOT EXISTS scrape_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  website_id INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_seconds INTEGER,
  status TEXT NOT NULL,
  notifications_found INTEGER DEFAULT 0,
  notifications_added INTEGER DEFAULT 0,
  notifications_updated INTEGER DEFAULT 0,
  error_message TEXT,
  status_code INTEGER,
  FOREIGN KEY (website_id) REFERENCES websites (id) ON DELETE CASCADE
);
'''

CREATE_APPLICATION_SETTINGS_TABLE = '''
CREATE TABLE IF NOT EXISTS application_settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
'''

TABLES = [
    CREATE_ORGANIZATIONS_TABLE,
    CREATE_WEBSITES_TABLE,
    CREATE_NOTIFICATIONS_TABLE,
    CREATE_PDF_DOCUMENTS_TABLE,
    CREATE_NOTIFICATION_REVIEW_QUEUE_TABLE,
    CREATE_SCRAPE_HISTORY_TABLE,
    CREATE_APPLICATION_SETTINGS_TABLE,
]

CREATE_NOTIFICATIONS_STATUS_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications (status);
'''

CREATE_NOTIFICATIONS_DEADLINE_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_notifications_application_deadline ON notifications (application_deadline);
'''

CREATE_NOTIFICATIONS_ORGANIZATION_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_notifications_organization_id ON notifications (organization_id);
'''

CREATE_NOTIFICATIONS_WEBSITE_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_notifications_website_id ON notifications (website_id);
'''

CREATE_WEBSITES_ORGANIZATION_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_websites_organization_id ON websites (organization_id);
'''

CREATE_WEBSITES_ENABLED_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_websites_enabled ON websites (is_enabled);
'''

CREATE_SCRAPE_HISTORY_WEBSITE_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_scrape_history_website_id ON scrape_history (website_id);
'''

CREATE_PDF_NOTIFICATION_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_pdf_notification_id
ON pdf_documents (notification_id);
'''

CREATE_REVIEW_QUEUE_STATUS_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON notification_review_queue (review_status);
'''

INDEXES = [
    CREATE_NOTIFICATIONS_STATUS_INDEX,
    CREATE_NOTIFICATIONS_DEADLINE_INDEX,
    CREATE_NOTIFICATIONS_ORGANIZATION_INDEX,
    CREATE_NOTIFICATIONS_WEBSITE_INDEX,
    CREATE_WEBSITES_ORGANIZATION_INDEX,
    CREATE_WEBSITES_ENABLED_INDEX,
    CREATE_SCRAPE_HISTORY_WEBSITE_INDEX,
    CREATE_PDF_NOTIFICATION_INDEX,
    CREATE_REVIEW_QUEUE_STATUS_INDEX,
]

# Columns added to existing tables after their initial release. Existing
# databases created before these were added need them backfilled via
# ALTER TABLE, since `CREATE TABLE IF NOT EXISTS` only helps fresh databases.
ADDED_COLUMNS_BY_TABLE = {
    "notifications": {"email_sent": "INTEGER NOT NULL DEFAULT 0"},
    "pdf_documents": {
        "http_status": "INTEGER",
        "extracted_text": "TEXT",
        "extraction_status": "TEXT",
    },
    "scrape_history": {"status_code": "INTEGER"},
}


def create_schema(connection: Connection) -> None:
    """Create the SQLite schema and indexes in the provided connection."""
    cursor = connection.cursor()
    for statement in TABLES:
        cursor.execute(statement)

    for table_name, added_columns in ADDED_COLUMNS_BY_TABLE.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_type in added_columns.items():
            if column_name not in existing_columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    for statement in INDEXES:
        cursor.execute(statement)
    connection.commit()
