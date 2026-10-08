from modam.local_setup import setup


def test_setup_creates_private_config_and_preserves_existing_secrets(tmp_path):
    setup(tmp_path, "gsk_synthetic_test_credential")
    settings = (tmp_path / ".local/compose.env").read_text()
    assert "MODAM_DATABASE_PASSWORD=" in settings
    assert "MODAM_CA_BUNDLE" not in settings
    assert (tmp_path / ".local/groq.env").stat().st_mode & 0o777 == 0o600
    setup(tmp_path, "gsk_other_synthetic_credential")
    assert (tmp_path / ".local/compose.env").read_text() == settings
    assert (
        tmp_path / ".local/groq.env"
    ).read_text() == "GROQ_API_KEY=gsk_synthetic_test_credential\n"
