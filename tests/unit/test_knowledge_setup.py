from modam.knowledge_setup import command, setup


def test_key_creation_is_private_and_preserves_existing(tmp_path):
    path = setup(tmp_path)
    before = path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert setup(tmp_path).read_text() == before
    assert len(before.splitlines()) == 2


def test_compose_command_preserves_data_and_supplies_ca(tmp_path, monkeypatch):
    import json

    setup(tmp_path)
    (tmp_path / ".local/chat-runtime.json").write_text(
        json.dumps({"database_password": "fixture-only"})
    )
    monkeypatch.setenv("MODAM_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")
    seen = []
    monkeypatch.setattr(
        "modam.knowledge_setup.subprocess.run", lambda args, **kwargs: seen.append((args, kwargs))
    )
    command(tmp_path, ["up", "-d", "--build"])
    args, kwargs = seen[0]
    assert "compose.knowledge.yaml" in " ".join(args)
    assert "down" not in args and "-v" not in args
    assert kwargs["env"]["MODAM_DATABASE_PASSWORD"] == "fixture-only"
    assert "MODAM_RAG_SERVICE_KEY" in kwargs["env"]
    assert ":ro" in (tmp_path / ".local/knowledge-ca.yaml").read_text()
