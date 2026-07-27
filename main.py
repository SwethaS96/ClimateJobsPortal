from fastapi import FastAPI

from database.connection import get_connection, close_connection
from database.schema import create_schema
from routers.application_settings import router as application_settings_router
from routers.organizations import router as organizations_router
from routers.notifications import router as notifications_router
from routers.pdf_documents import router as pdf_documents_router
from routers.scrape_history import router as scrape_history_router
from routers.websites import router as websites_router


app = FastAPI()

app.include_router(organizations_router)

app.include_router(websites_router)

app.include_router(notifications_router)

app.include_router(pdf_documents_router)

app.include_router(scrape_history_router)

app.include_router(application_settings_router)

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "message": "ClimateJobsPortal is running"
    }


@app.get("/test-db")
async def test_database():
    """Test SQLite database connection."""

    connection = get_connection()

    version = connection.execute(
        "SELECT sqlite_version();"
    ).fetchone()[0]

    close_connection(connection)

    return {
        "status": "success",
        "database": "Connected",
        "sqlite_version": version
    }


@app.get("/initialize-db")
async def initialize_database():
    """Create all database tables and indexes."""

    connection = get_connection()

    create_schema(connection)

    close_connection(connection)

    return {
        "status": "success",
        "message": "Database schema initialized successfully"
    }