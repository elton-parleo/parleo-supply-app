from contextlib import contextmanager

from modules.database import Session


@contextmanager
def get_db_session():
    """
    Yields a SQLAlchemy DB session and ensures it is closed after use.
    Used by MCP tools instead of FastAPI's Depends() mechanism.
    """
    db = Session()
    try:
        yield db
    finally:
        db.close()
