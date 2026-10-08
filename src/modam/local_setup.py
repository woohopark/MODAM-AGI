"""Portable local setup and Docker commands; Python standard library only."""

import argparse
import os
import re
import secrets
import subprocess
from getpass import getpass
from pathlib import Path


def _private_create(path: Path, content: str) -> None:
    # O_EXCL preserves existing credentials and refuses symlink replacements.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
        file.write(content)


def setup(root: Path, key: str) -> None:
    if not re.fullmatch(r"gsk_[A-Za-z0-9_-]+", key):
        raise ValueError("Enter a valid Groq API key")
    private = root / ".local"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_create(private / "groq.env", f"GROQ_API_KEY={key}\n")
    _private_create(
        private / "compose.env",
        f"MODAM_DATABASE_PASSWORD={secrets.token_urlsafe(32)}\n"
        "MODAM_CHAT_PORT=3300\n"
        "MODAM_NODE_ENV=development\n"
        "MODAM_PUBLIC_ORIGINS=http://localhost:3300,http://127.0.0.1:3300\n",
    )


def main(root: Path) -> None:
    parser = argparse.ArgumentParser(description="Run MODAM chat on this PC with Docker")
    parser.add_argument("action", choices=["setup", "start", "account", "status", "stop"])
    parser.add_argument("--username", default="modam-admin")
    args = parser.parse_args()
    if args.action == "setup":
        if (root / ".local/groq.env").exists() and (root / ".local/compose.env").exists():
            print("Local configuration already exists; credentials preserved.")
            return
        key = os.environ.get("GROQ_API_KEY") or getpass("Groq API key (hidden): ")
        setup(root, key.strip())
        print("Local configuration created. Next: python scripts/local-chat.py start")
        return
    if not (root / ".local/compose.env").exists() or not (root / ".local/groq.env").exists():
        raise SystemExit("Run python scripts/local-chat.py setup first")
    if not (root.parent / "modam-chat/package.json").exists():
        raise SystemExit("Clone MODAM-CHAT into the sibling directory modam-chat")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(root / ".local/compose.env"),
        "-f",
        str(root / "deployment/compose.local.yaml"),
    ]
    actions = {
        "start": ["up", "--build", "-d", "--wait", "--wait-timeout", "180"],
        "account": ["exec", "agi", "modam-create-user", args.username, "--admin"],
        "status": ["ps"],
        "stop": ["stop"],
    }
    try:
        subprocess.run(command + actions[args.action], cwd=root, check=True)
    except FileNotFoundError:
        raise SystemExit("Install and start Docker Desktop (Docker Engine on Linux)") from None
    except subprocess.CalledProcessError:
        raise SystemExit("Docker command failed; see the Docker output above") from None
    if args.action == "start":
        print(
            "Open http://localhost:3300 ; create an account with: "
            "python scripts/local-chat.py account"
        )
