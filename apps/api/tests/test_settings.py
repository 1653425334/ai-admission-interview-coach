from __future__ import annotations

from app.core import config


def test_get_settings_uses_the_same_anchored_env_file_from_any_cwd(monkeypatch) -> None:
    captured_env_files: list[object] = []

    class CapturingSettings:
        def __init__(self, *, _env_file: object) -> None:
            captured_env_files.append(_env_file)

    monkeypatch.setattr(config, "Settings", CapturingSettings)
    monkeypatch.chdir(config.ENV_FILE.parent / "apps" / "api" / "tests")
    config.get_settings.cache_clear()

    config.get_settings()

    assert captured_env_files == [config.ENV_FILE]
    assert config.ENV_FILE == config.ENV_FILE.parent / ".env"
    config.get_settings.cache_clear()
