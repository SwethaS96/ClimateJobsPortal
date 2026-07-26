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
  parser_name TEXT,
  scrape_frequency TEXT,
  is_enabled INTEGER NOT NULL DEFAULT 1,
  last_scraped TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (organization_id) REFERENCES organizations (id)
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
  FOREIGN KEY (organization_id) REFERENCES organizations (id),
  FOREIGN KEY (website_id) REFERENCES websites (id)
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
  FOREIGN KEY (notification_id) REFERENCES notifications (id)
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
  FOREIGN KEY (website_id) REFERENCES websites (id)
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

CREATE_WEBSITES_ORGANIZATION_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_websites_organization_id ON websites (organization_id);
'''

CREATE_SCRAPE_HISTORY_WEBSITE_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_scrape_history_website_id ON scrape_history (website_id);
'''

CREATE_PDF_NOTIFICATION_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_pdf_notification_id
ON pdf_documents (notification_id);
'''

INDEXES = [
    CREATE_NOTIFICATIONS_STATUS_INDEX,
    CREATE_NOTIFICATIONS_DEADLINE_INDEX,
    CREATE_NOTIFICATIONS_ORGANIZATION_INDEX,
    CREATE_WEBSITES_ORGANIZATION_INDEX,
    CREATE_SCRAPE_HISTORY_WEBSITE_INDEX,
    CREATE_PDF_NOTIFICATION_INDEX,
]


def create_schema(connection: Connection) -> None:
    """Create the SQLite schema and indexes in the provided connection."""
    cursor = connection.cursor()
    for statement in TABLES:
        cursor.execute(statement)
    for statement in INDEXES:
        cursor.execute(statement)
    connection.commit()
