import sqlite3
from sqlite3 import Connection

from config.settings import DATABASE_PATH


def get_connection() -> Connection:
    """Return a SQLite connection to the configured database path.

    The function ensures that the parent directory exists before opening the
    database file. SQLite foreign key support is enabled for the connection.

    Returns:
        A SQLite3 Connection object with row_factory set to sqlite3.Row.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(DATABASE_PATH)
    except sqlite3.Error as e:
        raise RuntimeError(f"Failed to connect to database: {e}") from e

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def close_connection(connection: Connection) -> None:
    """Close the provided SQLite connection."""
    connection.close()
