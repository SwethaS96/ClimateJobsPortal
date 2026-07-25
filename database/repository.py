from .connection import get_connection


def create_organization(name: str):
    conn = get_connection("data/database/climate_jobs.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO organizations (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()
