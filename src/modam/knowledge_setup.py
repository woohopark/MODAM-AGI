"""Compose launch support; independent services and protected keys, no Git operations."""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path


def setup(root: Path) -> Path:
    target = root / ".local" / "knowledge.env"
    target.parent.mkdir(mode=0o700, exist_ok=True)
    if not target.exists():
        with open(target, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
            for name in ["MODAM_RAG_SERVICE_KEY", "MODAM_ONTOLOGY_SERVICE_KEY"]:
                handle.write(f"{name}={secrets.token_urlsafe(48)}\n")
    target.chmod(0o600)
    return target


def command(root: Path, args: list[str]) -> None:
    settings = root / ".local" / "chat-runtime.json"
    env = os.environ.copy()
    portable = root / ".local" / "compose.env"
    if portable.exists():
        for line in portable.read_text().splitlines():
            if "=" in line:
                name, value = line.split("=", 1)
                if name in {
                    "MODAM_DATABASE_PASSWORD",
                    "MODAM_CHAT_PORT",
                    "MODAM_NODE_ENV",
                    "MODAM_PUBLIC_ORIGINS",
                }:
                    env[name] = value
    elif settings.exists():
        runtime = json.loads(settings.read_text())
        env["MODAM_DATABASE_PASSWORD"] = runtime["database_password"]
    else:
        raise ValueError("Run scripts/local-chat.py setup first")
    for line in setup(root).read_text().splitlines():
        name, value = line.split("=", 1)
        if name in {"MODAM_RAG_SERVICE_KEY", "MODAM_ONTOLOGY_SERVICE_KEY"}:
            env[name] = value
    for name in [
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ]:
        env.pop(name, None)
    files = [root / "deployment/compose.local.yaml", root / "deployment/compose.knowledge.yaml"]
    if bundle := env.get("MODAM_CA_BUNDLE"):
        # Public trust bundle remains a transient BuildKit secret and read-only runtime mount.
        from json import dumps

        override = root / ".local" / "knowledge-ca.yaml"
        path = dumps(str(Path(bundle).resolve()))
        volume = dumps(str(Path(bundle).resolve()) + ":/run/proxy-ca.pem:ro")
        override.write_text(f"""services:
  migrate: &ca
    build:
      secrets: [proxy_ca]
    environment:
      SSL_CERT_FILE: /run/proxy-ca.pem
    volumes: [{volume}]
  agi: *ca
  worker: *ca
  rag: *ca
  ontology: *ca
  chat:
    build:
      secrets: [proxy_ca]
secrets:
  proxy_ca:
    file: {path}
""")
        files.append(override)
    cli = ["docker", "--host=unix:///var/run/docker.sock", "compose"]
    for file in files:
        cli.extend(["-f", str(file)])
    subprocess.run([*cli, *args], env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "start", "status", "stop"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "setup":
        setup(root)
        print("Protected knowledge keys are ready; values are not displayed.")
    else:
        actions = {
            "start": ["up", "-d", "--build"],
            "status": ["ps"],
            "stop": ["stop", "worker", "rag", "ontology", "agi", "chat"],
        }
        command(root, actions[args.action])


if __name__ == "__main__":
    main()
