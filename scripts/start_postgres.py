"""Start a local development DB without putting credentials in command arguments."""

import os
import secrets
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
local = root / ".local"
local.mkdir(mode=0o700, exist_ok=True)
path = local / "runtime.env"
if not path.exists():
    password = secrets.token_urlsafe(32)
    content = (
        f"MODAM_POSTGRES_PASSWORD={password}\n"
        "MODAM_POSTGRES_PORT=55432\n"
        f"MODAM_DATABASE_URL=postgresql+psycopg://modam:{password}@127.0.0.1:55432/modam\n"
    )
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
# Compose loads generated values from an ignored, mode-0600 file. Never print config.
subprocess.run(
    ["docker", "compose", "--env-file", str(path), "up", "-d", "--wait", "postgres"],
    cwd=root,
    check=True,
)
print("PostgreSQL started on loopback; Settings loads .local/runtime.env.")
