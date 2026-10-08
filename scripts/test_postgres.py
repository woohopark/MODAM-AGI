"""Run integration tests in a newly created database; never reset an existing database."""

import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url

from modam.config import Settings
from modam.db import make_engine

url = make_url(Settings().database_url)
if url.get_backend_name() != "postgresql":
    raise SystemExit("Start scripts/start_postgres.py first or configure a PostgreSQL database")
name = "modam_test_" + uuid4().hex
engine = make_engine(url.render_as_string(hide_password=False))
with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
    connection.execute(text(f'CREATE DATABASE "{name}"'))
try:
    test_env = dict(os.environ)
    test_env["MODAM_TEST_DATABASE_URL"] = url.set(database=name).render_as_string(
        hide_password=False
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_postgres.py", "-q"], env=test_env, check=False
    )
finally:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    engine.dispose()
raise SystemExit(result.returncode)
