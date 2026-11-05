import pytest


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """Point config + database at a throwaway folder so tests never touch real data."""
    import likho.config as config
    import likho.db as db
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "likho.db")
    return tmp_path
