# Database

Document the database schema, storage, and access patterns for ClimateJobsPortal.
# Database Design
**Project:** ClimateJobsPortal  
**Version:** 1.0  
**Author:** Swetha Sivakumar  
**Status:** Approved (Frozen)

---

# 1. Overview

The ClimateJobsPortal database is designed to collect, store, and manage recruitment notifications from multiple climate and environmental research organizations.

The design follows normalization principles to:

- Avoid duplicate data
- Support multiple monitored websites per organization
- Support multiple PDFs per notification
- Maintain scraping history
- Allow future expansion without schema changes

SQLite is used as the primary database for Version 1.

---

# 2. Database Architecture

```
Organizations
      │
      │ 1
      ▼
Websites
      │
      │ 1
      ▼
Notifications
      │
      ├────────► PDF Documents
      │
      └────────► Scrape History
```

---

# 3. Tables

## 3.1 Organizations

Stores information about institutions.

| Column | Type | Description |
|---------|------|-------------|
| id | INTEGER | Primary Key |
| name | TEXT | Full organization name |
| short_name | TEXT | Abbreviation |
| homepage_url | TEXT | Official website |
| country | TEXT | Country |
| state | TEXT | State/Region |
| is_active | BOOLEAN | Whether organization is monitored |
| created_at | DATETIME | Record creation timestamp |
| updated_at | DATETIME | Last modification timestamp |

### Example

| id | name | short_name |
|----|------|------------|
|1|India Meteorological Department|IMD|

---

## 3.2 Websites

Stores monitored pages belonging to organizations.

Examples:

- Careers
- Recruitment
- Vacancies
- Notices

| Column | Type | Description |
|---------|------|-------------|
| id | INTEGER | Primary Key |
| organization_id | INTEGER | FK → organizations.id |
| page_name | TEXT | Name of monitored page |
| url | TEXT | Page URL |
| parser_name | TEXT | Parser assigned |
| scrape_frequency | TEXT | Daily / Weekly |
| is_enabled | BOOLEAN | Enable monitoring |
| last_scraped | DATETIME | Last successful scrape |
| created_at | DATETIME | Created timestamp |
| updated_at | DATETIME | Updated timestamp |

Relationship

```
One Organization
        │
        ├── Careers
        ├── Recruitment
        ├── Notices
        └── Vacancies
```

---

## 3.3 Notifications

Core table storing recruitment information.

| Column | Type | Description |
|---------|------|-------------|
| id | INTEGER | Primary Key |
| website_id | INTEGER | FK → websites.id |
| title | TEXT | Notification title |
| notification_number | TEXT | Advertisement number |
| category | TEXT | Faculty / Project / Internship / JRF |
| notification_date | DATE | Publication date |
| application_deadline | DATE | Last date to apply |
| status | TEXT | ACTIVE / EXPIRED / ARCHIVED |
| page_url | TEXT | Official webpage |
| hash | TEXT | Unique notification hash |
| first_seen | DATETIME | First scrape timestamp |
| last_seen | DATETIME | Most recent verification |
| created_at | DATETIME | Record creation |
| updated_at | DATETIME | Last update |

---

## 3.4 PDF Documents

Stores PDF files associated with notifications.

One notification may contain multiple PDFs.

Examples

- Advertisement
- Corrigendum
- Annexure

| Column | Type | Description |
|---------|------|-------------|
| id | INTEGER | Primary Key |
| notification_id | INTEGER | FK → notifications.id |
| document_type | TEXT | Advertisement / Corrigendum |
| pdf_url | TEXT | Official PDF URL |
| local_file | TEXT | Downloaded file location |
| checksum | TEXT | Detect file changes |
| downloaded | BOOLEAN | Download status |
| downloaded_at | DATETIME | Download timestamp |
| file_size | INTEGER | File size in bytes |

Relationship

```
Notification

│

├── Advertisement.pdf

├── Corrigendum.pdf

└── Annexure.pdf
```

---

## 3.5 Scrape History

Stores execution history of every scraper run.

Useful for debugging failures.

| Column | Type | Description |
|---------|------|-------------|
| id | INTEGER | Primary Key |
| website_id | INTEGER | FK → websites.id |
| started_at | DATETIME | Scrape start |
| finished_at | DATETIME | Scrape end |
| status | TEXT | SUCCESS / FAILED |
| notifications_found | INTEGER | Number discovered |
| notifications_added | INTEGER | Newly inserted |
| notifications_updated | INTEGER | Existing updated |
| error_message | TEXT | Error details |

---

## 3.6 Application Settings

Stores configurable application values.

| Column | Type | Description |
|---------|------|-------------|
| key | TEXT | Primary Key |
| value | TEXT | Configuration value |

Examples

| key | value |
|-----|-------|
| archive_after_days | 90 |
| download_pdfs | true |
| default_filter_days | 7 |

---

# 4. Relationships

```
Organizations
      │
      ▼
Websites
      │
      ▼
Notifications
      │
      ├────────► PDF Documents
      │
      └────────► Scrape History
```

---

# 5. Notification Lifecycle

```
Website

↓

Notification Published

↓

Scraper Detects

↓

ACTIVE

↓

Deadline Passed

↓

EXPIRED

↓

Retention Period Ends

↓

ARCHIVED
```

Notifications are never immediately deleted.

---

# 6. Duplicate Detection

Each notification receives a unique hash generated from stable fields such as:

- Title
- Notification Number
- Website
- Publication Date

The `hash` column has a UNIQUE constraint to prevent duplicate entries.

---

# 7. Future Expansion

This schema supports future features without major redesign:

- AI summaries
- Email notifications
- Telegram alerts
- User accounts
- Search by category
- Analytics dashboard
- Multiple countries
- Additional document types

---

# 8. Design Principles

- Normalized database structure
- Single responsibility for each table
- Referential integrity through foreign keys
- Immutable historical records
- Extensible without schema redesign
- Optimized for recruitment notification tracking

---

# 9. Version History

| Version | Date | Changes |
|----------|------|---------|
| 1.0 | July 2026 | Initial database design approved |