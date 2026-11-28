import os
import stat
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values

from scripts import configure_meme50
from scripts.configure_meme50 import merge_private_env


def test_private_merge_preserves_other_members_settings_and_deduplicates(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# 保留\nDATABASE_URL='existing'\nMEME50_BRAVE_API_KEY='old'\n"
        "MEME50_BRAVE_API_KEY='duplicate'\nOTHER_SETTING=true\n",
        encoding="utf-8",
    )
    assert merge_private_env(path, {"MEME50_BRAVE_API_KEY": "controlled-test'value\\suffix"})
    assert dotenv_values(path)["MEME50_BRAVE_API_KEY"] == "controlled-test'value\\suffix"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# 保留\nDATABASE_URL='existing'\n")
    assert "OTHER_SETTING=true\n" in content
    assert content.count("MEME50_BRAVE_API_KEY=") == 1
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file ACLs")
def test_windows_merge_has_a_protected_current_user_acl(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PRESERVE=1\n")
    assert merge_private_env(path, {"DEEPSEEK_API_KEY": "controlled-test"})

    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = """
        $ErrorActionPreference = 'Stop'
        $acl = [System.IO.File]::GetAccessControl($env:MEMERETRIEVE_ACL_TEST_FILE, 'Access')
        $acl.GetSecurityDescriptorSddlForm('Access')
        [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    """
    output = subprocess.check_output(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "MEMERETRIEVE_ACL_TEST_FILE": str(path)},
        text=True,
        timeout=15,
    )
    descriptor, sid = output.splitlines()
    flags, entries = descriptor.removeprefix("D:").split("(", 1)
    assert "P" in flags
    assert entries == f"A;;FA;;;{sid})"
    assert dotenv_values(path) == {"PRESERVE": "1", "DEEPSEEK_API_KEY": "controlled-test"}


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file ACLs")
def test_windows_acl_failure_preserves_existing_config(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("PRESERVE=1\n")
    original = path.read_bytes()

    def fail_before_writing(temporary):
        assert temporary.read_bytes() == b""
        raise OSError("configuration ACL could not be secured")

    monkeypatch.setattr(configure_meme50, "_protect_windows_file", fail_before_writing)
    with pytest.raises(OSError, match="ACL"):
        merge_private_env(path, {"DEEPSEEK_API_KEY": "controlled-test"})
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".meme50-env-*"))


def test_blank_credentials_do_not_create_fake_configuration(tmp_path):
    path = tmp_path / ".env"
    assert not merge_private_env(path, {"MEME50_GEMINI_API_KEY": ""})
    assert not path.exists()


def test_symlinks_refused_without_mutation(tmp_path):
    target = tmp_path / "other"
    target.write_text("untouched")
    link = tmp_path / ".env"
    try:
        link.symlink_to(target)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires Developer Mode or the symlink privilege")
        raise
    with pytest.raises(ValueError):
        merge_private_env(link, {"MEME50_GEMINI_API_KEY": "controlled-test"})
    assert target.read_text() == "untouched"


def test_newline_injection_refused_without_mutation(tmp_path):
    with pytest.raises(ValueError):
        merge_private_env(tmp_path / "regular", {"MEME50_GEMINI_API_KEY": "x\nOTHER=y"})
    assert not (tmp_path / "regular").exists()


def test_concurrent_member_edit_is_not_overwritten(tmp_path, monkeypatch):
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


@pytest.mark.parametrize("arguments", [[], ["--deepseek-only"]])
def test_default_cli_uses_one_deepseek_key_for_vision_and_web(
    tmp_path, monkeypatch, capsys, arguments
):
    config = configure_meme50
    monkeypatch.setitem(config.MemeSettings.model_config, "env_file", ".env")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "MEME50_PROVIDER_POLICY=hkust-deepseek-v1\nMEME50_VISION_PROVIDER=hkust\n"
    )
    monkeypatch.setattr("sys.argv", ["configure_meme50", *arguments])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "local-test-deepseek"

    monkeypatch.setattr(config.getpass, "getpass", answer)
    with pytest.raises(SystemExit) as exit_code:
        config.main()
    assert exit_code.value.code == 0
    assert prompts == ["DEEPSEEK_API_KEY: "]
    assert config.presence()["visual_key_present"] and config.presence()["deepseek_key_present"]
    assert config.presence()["provider_policy"] == "deepseek-only-v1"
    assert dotenv_values(tmp_path / ".env")["MEME50_VISION_PROVIDER"] == "deepseek"
    assert "local-test-deepseek" not in capsys.readouterr().out


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


@pytest.mark.parametrize(("entered_key", "expected_exit"), [("controlled-hkgai-key", 0), ("", 2)])
def test_hkgai_cli_prompts_only_for_its_own_key(
    tmp_path, monkeypatch, capsys, entered_key, expected_exit
):
    config = configure_meme50
    monkeypatch.setitem(config.MemeSettings.model_config, "env_file", ".env")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".env"
    path.write_text(
        "MEME50_HKUST_API_KEY=controlled-school-key\nDEEPSEEK_API_KEY=controlled-search\n"
    )

    monkeypatch.setattr("sys.argv", ["configure_meme50", "--provider", "hkgai", "--vision-only"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: ""
        if prompt == "MEME50_HKGAI_MODEL [t2_hkgai-v3_fp8_1m_e10]: "
        else pytest.fail("must only ask for the HKGAI model"),
    )
    prompts = []

    def secret(prompt):
        prompts.append(prompt)
        return entered_key

    monkeypatch.setattr(config.getpass, "getpass", secret)
    with pytest.raises(SystemExit) as exit_info:
        config.main()
    assert exit_info.value.code == expected_exit
    assert prompts == ["MEME50_HKGAI_API_KEY: "]
    values = dotenv_values(path)
    assert values["MEME50_VISION_PROVIDER"] == "hkgai"
    assert values["MEME50_PROVIDER_POLICY"] == "hkgai-deepseek-v1"
    assert values["MEME50_HKGAI_MODEL"] == "t2_hkgai-v3_fp8_1m_e10"
    assert values.get("MEME50_HKGAI_API_KEY", "") == entered_key
    assert values["MEME50_HKUST_API_KEY"] == "controlled-school-key"
    assert values["DEEPSEEK_API_KEY"] == "controlled-search"
    output = capsys.readouterr().out
    assert '"vision_provider": "hkgai"' in output
    assert '"authorization_verified": false' in output
    assert "controlled-" not in output


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
            "MEME50_VISION_PROVIDER": "hkgai",
            "MEME50_PROVIDER_POLICY": "hkgai-deepseek-v1",
            "MEME50_HKUST_API_KEY": "controlled-school-key",
            "MEME50_HKUST_MODEL": "gemini-2.5-flash-lite",
            "MEME50_HKGAI_API_KEY": "controlled-hkgai-key",
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
    assert dotenv_values(path)["MEME50_VISION_PROVIDER"] == "hkgai"
    assert dotenv_values(path)["MEME50_PROVIDER_POLICY"] == "hkgai-deepseek-v1"
    assert dotenv_values(path)["MEME50_HKGAI_API_KEY"] == "controlled-hkgai-key"


def test_explicit_test_credentials_override_all_dotenv_aliases(tmp_path):
    from services.search_agent.meme_types import MemeSettings

    path = tmp_path / ".env"
    fields = {
        "hkust_api_key": "MEME50_HKUST_API_KEY",
        "hkgai_api_key": "MEME50_HKGAI_API_KEY",
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
            if name in {"deepseek_api_key", "hkgai_api_key"}
            else getattr(settings, name)
        )
        == "controlled-constructor-value"
        for name in fields
    )
