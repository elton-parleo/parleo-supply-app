import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine import URL

import time
import functools
from sqlalchemy.exc import OperationalError
from modules.constants import supabase_db_host, supabase_db_password, database_pool_size_str

# get the database credentials
database_pool_size = int(database_pool_size_str) if database_pool_size_str else 5

# connect to supabase postgres database
DATABASE_URL = URL.create(
    drivername="postgresql",
    username="postgres.epuofomhfngvkkamlfiz",
    host=supabase_db_host,
    database="postgres",
    port="6543",    # transaction mode - should reduce/eliminate max connecting error
    password=supabase_db_password
)

# Create an engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=database_pool_size, pool_recycle=240, max_overflow=2)
# Create a configured "Session" class
session_factory = sessionmaker(expire_on_commit=False, bind=engine)
# Create a scoped session
Session = scoped_session(session_factory) 


def retry_db_operation(retries=3, delay=1, backoff=2):
    """
    Retries a DB operation on OperationalError and disposes the engine
    so SQLAlchemy recreates fresh connections.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            wait = delay

            while attempt < retries:
                try:
                    return func(*args, **kwargs)

                except OperationalError as e:
                    attempt += 1

                    # Dispose the entire pool (CRITICAL for Supabase)
                    try:
                        engine.dispose()
                        print("[DB] Disposing engine due to OperationalError")
                    except Exception:
                        pass  # ignore dispose errors

                    if attempt >= retries:
                        # Exhausted retries — raise the error
                        raise 

                    # Optional logging
                    print(
                        f"[DB RETRY] Attempt {attempt}/{retries} failed: {e}. "
                        f"Retrying in {wait}s..."
                    )

                    time.sleep(wait)
                    wait *= backoff

        return wrapper
    return decorator

