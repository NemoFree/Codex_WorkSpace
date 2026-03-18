import os
from contextlib import contextmanager

import psycopg


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://app:app@localhost:5432/knowledge"
)


@contextmanager
def get_conn():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        yield conn
