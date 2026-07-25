# Architecture

Describe the overall architecture of ClimateJobsPortal here.
# System Architecture
**Project:** ClimateJobsPortal  
**Version:** 1.0  
**Author:** Swetha Sivakumar  
**Status:** Approved (Frozen)

---

# 1. Overview

ClimateJobsPortal is a modular application that automatically collects recruitment notifications from climate, environmental, and Earth science organizations.

The application periodically visits recruitment webpages, extracts notification details, stores them in a structured SQLite database, and presents them through a searchable web dashboard.

The system is designed to be modular so that each component has a single responsibility and can evolve independently.

---

# 2. System Goals

The application should:

- Monitor multiple organizations.
- Support multiple recruitment pages per organization.
- Detect newly published notifications.
- Avoid duplicate entries.
- Download and manage official PDF documents.
- Store all recruitment data in a normalized database.
- Provide a searchable dashboard.
- Allow future integration of AI features.

---

# 3. High-Level Architecture

```
                    +---------------------+
                    |     User Dashboard  |
                    +----------+----------+
                               |
                               |
                               ▼
                    +---------------------+
                    |      FastAPI API    |
                    +----------+----------+
                               |
               +---------------+---------------+
               |                               |
               ▼                               ▼
     +-------------------+          +-------------------+
     |   Database Layer  |          |    AI Services    |
     |  (SQLite + CRUD)  |          |   (Future Scope)  |
     +---------+---------+          +-------------------+
               ^
               |
               |
      +--------+--------+
      |                 |
      ▼                 ▼
+------------+   +---------------+
|   Scraper  |   |    Parsers    |
+------------+   +---------------+
        ^
        |
        |
+-----------------------+
| Organization Websites |
+-----------------------+
```

---

# 4. Folder Structure

```
ClimateJobsPortal/

├── backend/
├── frontend/
├── scraper/
├── parser/
├── database/
├── models/
├── config/
├── utils/
├── docs/
├── tests/
├── logs/
├── data/
├── requirements.txt
└── README.md
```

---

# 5. Component Responsibilities

## Backend

Responsible for:

- REST API
- Business logic
- Communication between frontend and database

Technology:

- FastAPI

---

## Frontend

Responsible for:

- Display notifications
- Search
- Filters
- Opening PDFs
- Opening official webpages

Version 1 focuses on a simple dashboard.

---

## Scraper

Responsible for:

- Visiting websites
- Downloading HTML
- Passing HTML to parsers

The scraper does **not** understand website structure.

It only retrieves webpage content.

---

## Parser

Responsible for extracting information from webpage HTML.

Each organization has its own parser.

Example

```
parser/

imd.py

niot.py

iitm.py

nccr.py
```

Each parser converts raw HTML into a common notification format.

---

## Database

Responsible for:

- Data persistence
- Duplicate detection
- Queries
- Updates

No other module communicates directly with SQLite.

---

## Models

Defines Python data models shared across the application.

Example

- Organization
- Website
- Notification
- PDFDocument

---

## Config

Stores application configuration.

Examples

- Website URLs
- Parser mapping
- Retry limits
- Download paths

---

## Logs

Stores:

- Scraper logs
- Errors
- Download history

Useful for debugging.

---

## Tests

Contains unit and integration tests.

---

# 6. Data Flow

The application follows a simple pipeline.

```
Website

↓

Scraper

↓

Parser

↓

Notification Object

↓

Database Repository

↓

SQLite Database

↓

FastAPI

↓

Dashboard
```

Each component performs only one task.

---

# 7. Scraping Workflow

```
Start

↓

Load website configuration

↓

Visit website

↓

Download HTML

↓

Select parser

↓

Extract notifications

↓

Generate notification hash

↓

Duplicate check

↓

Insert or Update database

↓

Download PDFs

↓

Complete
```

---

# 8. Duplicate Detection Workflow

```
Notification

↓

Generate Hash

↓

Hash Exists?

     │

 ┌───┴────┐

 │        │

Yes       No

 │        │

Update   Insert
```

This prevents duplicate notifications.

---

# 9. Dashboard Workflow

```
User opens application

↓

Frontend requests notifications

↓

Backend queries database

↓

Database returns results

↓

Display table

↓

User opens PDF or Website
```

---

# 10. Error Handling

Every component handles only its own errors.

Examples

Scraper

- Website unavailable
- Timeout
- SSL errors

Parser

- HTML structure changed
- Missing fields

Database

- Duplicate entries
- Connection errors

Backend

- Invalid requests
- Internal server errors

Errors are logged for troubleshooting.

---

# 11. Future AI Integration

Version 1 does not include AI.

Future AI capabilities may include:

- Notification summarization
- Automatic category prediction
- Skill extraction
- Semantic search
- Resume matching
- Personalized recommendations

These will be implemented as independent services without modifying the core database.

---

# 12. Design Principles

The architecture follows the following principles:

### Separation of Concerns

Each module has one responsibility.

---

### Modularity

Components can be developed independently.

---

### Scalability

New organizations require only a new parser.

No database changes.

---

### Extensibility

Future features should require minimal changes to existing code.

---

### Maintainability

Small modules are easier to debug and test.

---

# 13. Development Roadmap

## Phase 1

- Database
- Generic scraper
- HTML parser
- SQLite storage

---

## Phase 2

- FastAPI backend
- Dashboard
- Search
- Filters

---

## Phase 3

- Scheduled scraping
- Email notifications
- PDF management improvements

---

## Phase 4

- AI summaries
- Semantic search
- Resume matching
- Analytics
- Multi-user support

---

# 14. Technology Stack

| Component | Technology |
|------------|------------|
| Language | Python 3.14 |
| Database | SQLite |
| Backend | FastAPI |
| ORM | SQLAlchemy |
| Scraping | Requests + BeautifulSoup |
| Dynamic Websites | Playwright |
| Frontend | HTML, CSS, JavaScript (Version 1) |
| API | REST |
| Version Control | Git |
| IDE | Visual Studio Code |

---

# 15. Architecture Summary

ClimateJobsPortal follows a layered architecture:

```
Presentation Layer
        │
        ▼
Business Logic Layer
        │
        ▼
Data Access Layer
        │
        ▼
SQLite Database
```

Each layer communicates only with the layer immediately below it, ensuring a clean, maintainable, and extensible architecture suitable for long-term development.