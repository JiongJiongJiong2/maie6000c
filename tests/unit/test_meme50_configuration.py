import stat

import pytest
from dotenv import dotenv_values

from scripts.configure_meme50 import merge_private_env


def test_private_merge_preserves_other_members_settings_and_deduplicates(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# preserve\nDATABASE_URL='existing'\nMEME50_BRAVE_API_KEY='old'\n"
        "MEME50_BRAVE_API_KEY='duplicate'\nOTHER_SETTING=true\n"
    )
    assert merge_private_env(path, {"MEME50_BRAVE_API_KEY": "controlled-test'value\\suffix"})
    assert dotenv_values(path)["MEME50_BRAVE_API_KEY"] == "controlled-test'value\\suffix"
    assert "DATABASE_URL='existing'\n" in path.read_text()
    assert "OTHER_SETTING=true\n" in path.read_text()
    assert path.read_text().count("MEME50_BRAVE_API_KEY=") == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_blank_credentials_do_not_create_fake_configuration(tmp_path):
    path = tmp_path / ".env"
    assert not merge_private_env(path, {"MEME50_GEMINI_API_KEY": ""})
    assert not path.exists()


def test_symlinks_and_newline_injection_refused_without_mutation(tmp_path):
    target = tmp_path / "other"
    target.write_text("untouched")
    link = tmp_path / ".env"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        merge_private_env(link, {"MEME50_GEMINI_API_KEY": "controlled-test"})
    assert target.read_text() == "untouched"
    with pytest.raises(ValueError):
        merge_private_env(tmp_path / "regular", {"MEME50_GEMINI_API_KEY": "x\nOTHER=y"})
    assert not (tmp_path / "regular").exists()


def test_concurrent_member_edit_is_not_overwritten(tmp_path, monkeypatch):
    from scripts import configure_meme50

    path = tmp_path / ".env"
    path.write_text("OTHER=original\n")
    parse = configure_meme50.dotenv_values

    def changed(temporary):
        values = parse(temporary)
        path.write_text("OTHER=member-update\n")
        return values

    monkeypatch.setattr(configure_meme50, "dotenv_values", changed)
    with pytest.raises(ValueError, match="concurrently"):
        merge_private_env(path, {"MEME50_BRAVE_API_KEY": "controlled-test-key"})
    assert path.read_text() == "OTHER=member-update\n"
    assert not list(tmp_path.glob(".meme50-env-*"))


def test_school_configuration_and_model_validation(tmp_path):
    path = tmp_path / ".env"
    assert merge_private_env(
        path,
        {
            "MEME50_VISION_PROVIDER": "hkust",
            "MEME50_HKUST_API_KEY": "controlled-school-key",
            "MEME50_HKUST_MODEL": "gemini-2.5-flash-lite",
        },
    )
    assert dotenv_values(path)["MEME50_HKUST_API_KEY"] == "controlled-school-key"
    original = path.read_bytes()
    for invalid in [{"MEME50_VISION_PROVIDER": "unknown"}, {"MEME50_HKUST_MODEL": "../../model"}]:
        with pytest.raises(ValueError):
            merge_private_env(path, invalid)
        assert path.read_bytes() == original


def test_school_only_cli_does_not_request_google_or_secondary_key(tmp_path, monkeypatch, capsys):
    from scripts import configure_meme50 as config
    from services.search_agent.meme_types import MemeSettings

    monkeypatch.setitem(MemeSettings.model_config, "env_file", ".env")

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["configure_meme50", "--provider", "hkust", "--vision-only"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    prompts = []

    def secret(prompt):
        prompts.append(prompt)
        return "controlled-school-key"

    monkeypatch.setattr(config.getpass, "getpass", secret)
    with pytest.raises(SystemExit) as exit_info:
        config.main()
    assert exit_info.value.code == 0
    assert prompts == ["MEME50_HKUST_API_KEY: "]
    output = capsys.readouterr().out
    assert '"vision_provider": "hkust"' in output
    assert '"authorization_verified": false' in output
    assert "controlled-school-key" not in output


def test_search_only_cli_preserves_school_key_and_model(tmp_path, monkeypatch):
    from scripts import configure_meme50 as config
    from services.search_agent.meme_types import MemeSettings

    monkeypatch.setitem(MemeSettings.model_config, "env_file", ".env")

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".env"
    config.merge_private_env(
        path,
        {
            "MEME50_VISION_PROVIDER": "hkust",
            "MEME50_HKUST_API_KEY": "controlled-school-key",
            "MEME50_HKUST_MODEL": "gemini-2.5-flash-lite",
        },
    )
    monkeypatch.setattr("sys.argv", ["configure_meme50", "--search-only"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: ""
        if prompt.startswith("MEME50_DEEPSEEK_MODEL")
        else pytest.fail("must not ask school provider/model"),
    )
    prompts = []

    def secret(prompt):
        prompts.append(prompt)
        return "controlled-search-key"

    monkeypatch.setattr(config.getpass, "getpass", secret)
    with pytest.raises(SystemExit) as exit_info:
        config.main()
    assert exit_info.value.code == 0
    assert prompts == ["DEEPSEEK_API_KEY: "]
    assert dotenv_values(path)["MEME50_HKUST_API_KEY"] == "controlled-school-key"
    assert dotenv_values(path)["MEME50_HKUST_MODEL"] == "gemini-2.5-flash-lite"


def test_explicit_test_credentials_override_all_dotenv_aliases(tmp_path):
    from services.search_agent.meme_types import MemeSettings

    path = tmp_path / ".env"
    fields = {
        "hkust_api_key": "MEME50_HKUST_API_KEY",
        "gemini_api_key": "MEME50_GEMINI_API_KEY",
        "google_vision_api_key": "MEME50_GOOGLE_VISION_API_KEY",
        "brave_api_key": "MEME50_BRAVE_API_KEY",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
    }
    path.write_text("".join(f"{alias}=controlled-file-value\n" for alias in fields.values()))
    settings = MemeSettings(
        _env_file=path, **{name: "controlled-constructor-value" for name in fields}
    )
    assert all(
        (
            getattr(settings, name).get_secret_value()
            if name == "deepseek_api_key"
            else getattr(settings, name)
        )
        == "controlled-constructor-value"
        for name in fields
    )
