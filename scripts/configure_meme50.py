"""Enter credentials locally with no echo, or report presence without network calls.

Only the current project's .env is updated. Blank answers preserve existing
values; unrelated lines are untouched. No value is printed or accepted in argv.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from dotenv import dotenv_values

from services.search_agent.meme_types import MemeSettings, VISION_PROVIDER_POLICIES

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "DEEPSEEK_API_KEY",
    "MEME50_HKUST_API_KEY",
    "MEME50_HKGAI_API_KEY",
    "MEME50_GEMINI_API_KEY",
    "MEME50_GOOGLE_VISION_API_KEY",
    "MEME50_BRAVE_API_KEY",
)
MODEL = "MEME50_VISION_MODEL"
HKUST_MODEL = "MEME50_HKUST_MODEL"
HKGAI_MODEL = "MEME50_HKGAI_MODEL"
PROVIDER = "MEME50_VISION_PROVIDER"
POLICY = "MEME50_PROVIDER_POLICY"
DEEPSEEK_MODEL = "MEME50_DEEPSEEK_MODEL"
POLICY_FIELDS = {
    "MEME50_KEYWORD_PROVIDER": "deepseek",
    "MEME50_REVERSE_IMAGE_PROVIDER": "disabled",
}
VISION_POLICIES = {provider: policy for policy, provider in VISION_PROVIDER_POLICIES.items()}


def _protect_windows_file(path: Path) -> None:
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = """
        $ErrorActionPreference = 'Stop'
        $path = $env:MEMERETRIEVE_ENV_ACL_TARGET
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl = [System.Security.AccessControl.FileSecurity]::new()
        $acl.SetSecurityDescriptorSddlForm("D:P(A;;FA;;;$user)", 'Access')
        $acl.SetAccessRuleProtection($true, $false)
        [System.IO.File]::SetAccessControl($path, $acl)

        $acl = [System.IO.File]::GetAccessControl($path, 'Access')
        $rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
        if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 1 -or
            $rules[0].IdentityReference -ne $user -or $rules[0].IsInherited -or
            $rules[0].AccessControlType -ne 'Allow' -or
            $rules[0].FileSystemRights -ne 'FullControl') {
            exit 1
        }
    """
    try:
        subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "MEMERETRIEVE_ENV_ACL_TARGET": str(path)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
    except subprocess.SubprocessError:
        raise OSError("configuration ACL could not be secured") from None


def merge_private_env(path: Path, updates: dict[str, str]):
    """Atomic, owner-only update; refuse symlinks and unsupported field names."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("configuration must be a regular file")
    model_fields = (MODEL, HKUST_MODEL, HKGAI_MODEL, DEEPSEEK_MODEL)
    if not set(updates) <= {*FIELDS, *model_fields, PROVIDER, POLICY, *POLICY_FIELDS}:
        raise ValueError("unsupported configuration field")
    updates = {key: value for key, value in updates.items() if value}
    if any(any(c in value for c in "\r\n\0") for value in updates.values()):
        raise ValueError("multiline configuration is not accepted")
    for field in model_fields:
        pattern = r"[A-Za-z0-9._-]+" if field == HKGAI_MODEL else r"[A-Za-z0-9.-]+"
        if field in updates and not re.fullmatch(pattern, updates[field]):
            raise ValueError("invalid model identifier")
    if PROVIDER in updates and updates[PROVIDER] not in VISION_POLICIES:
        raise ValueError("unsupported vision provider")
    if POLICY in updates and (
        updates[POLICY] not in VISION_PROVIDER_POLICIES
        or (PROVIDER in updates and VISION_POLICIES[updates[PROVIDER]] != updates[POLICY])
    ):
        raise ValueError("invalid vision provider policy")
    if any(k in updates and updates[k] != value for k, value in POLICY_FIELDS.items()):
        raise ValueError("unsupported provider policy")
    if not updates:
        return False
    existed = path.exists()
    original = path.read_text(encoding="utf-8") if existed else ""
    lines, handled = [], set()
    for line in original.splitlines(keepends=True):
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=", line)
        key = match.group(1) if match else None
        if key in updates:
            if key not in handled:
                value = updates[key].replace("\\", "\\\\").replace("'", "\\'")
                lines.append(f"{key}='{value}'\n")
                handled.add(key)
        else:
            lines.append(line)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    for key, value in updates.items():
        if key not in handled:
            value = value.replace("\\", "\\\\").replace("'", "\\'")
            lines.append(f"{key}='{value}'\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".meme50-env-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            # Set and verify permissions before the temporary file receives credentials.
            if os.name == "nt":
                _protect_windows_file(Path(temporary))
            else:
                os.fchmod(stream.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            stream.write("".join(lines))
            stream.flush()
            os.fsync(stream.fileno())
        # Parse before promotion; diagnostics never contain a value.
        parsed = dotenv_values(temporary)
        if any(parsed.get(k) != v for k, v in updates.items()):
            raise ValueError("configuration encoding failed")
        if path.is_symlink():
            raise ValueError("configuration changed to a symlink")
        if path.exists() != existed or (existed and path.read_text(encoding="utf-8") != original):
            raise ValueError("configuration was concurrently modified")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def presence():
    settings = MemeSettings()
    visual_keys = {
        "hkust": bool(settings.hkust_api_key.strip()),
        "hkgai": bool(settings.hkgai_api_key.get_secret_value().strip()),
    }
    return dict(
        provider_policy=settings.provider_policy,
        vision_provider=settings.vision_provider,
        visual_key_present=(
            VISION_PROVIDER_POLICIES.get(settings.provider_policy) == settings.vision_provider
            and visual_keys.get(settings.vision_provider, False)
        ),
        hkust_key_present=visual_keys["hkust"],
        hkgai_key_present=visual_keys["hkgai"],
        deepseek_key_present=bool(settings.deepseek_api_key.get_secret_value()),
        deepseek_model=settings.deepseek_model,
        keyword_provider=settings.keyword_provider,
        reverse_image_provider=settings.reverse_image_provider,
        vision_model=settings.effective_vision_model,
        authorization_verified=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Presence only; no API calls")
    parser.add_argument(
        "--provider", choices=tuple(VISION_POLICIES), help="Vision service (defaults to configured)"
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--vision-only", action="store_true", help="Configure/check vision only")
    scope.add_argument(
        "--search-only",
        "--deepseek-only",
        action="store_true",
        help="Configure/check only the DeepSeek key and Flash model",
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        if not args.check:
            if not sys.stdin.isatty():
                raise ValueError("run locally in an interactive terminal; no secret argv/stdin")
            settings = MemeSettings()
            print("Enter authorized credentials locally. Input is hidden; blank preserves values.")
            fields = []
            model_defaults = {}
            updates = dict(POLICY_FIELDS)
            if not args.search_only:
                provider = args.provider or settings.vision_provider
                if provider not in VISION_POLICIES:
                    raise ValueError("unsupported vision provider")
                model_field, model_default = (
                    (HKUST_MODEL, settings.hkust_model)
                    if provider == "hkust"
                    else (HKGAI_MODEL, settings.hkgai_model)
                )
                fields.append(f"MEME50_{provider.upper()}_API_KEY")
                model_defaults[model_field] = model_default
                updates.update({PROVIDER: provider, POLICY: VISION_POLICIES[provider]})
            if not args.vision_only:
                fields.append("DEEPSEEK_API_KEY")
                model_defaults[DEEPSEEK_MODEL] = settings.deepseek_model
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                updates.update({key: getpass.getpass(key + ": ") for key in fields})
            print("Press Enter to use each shown default; probe verifies actual access.")
            for field, default in model_defaults.items():
                updates[field] = input(f"{field} [{default}]: ").strip() or default
            merge_private_env(ROOT / ".env", updates)
        report = presence()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        has_vision = report["visual_key_present"] and (
            args.provider is None or report["vision_provider"] == args.provider
        )
        configured = (args.search_only or has_vision) and (
            args.vision_only or report["deepseek_key_present"]
        )
        raise SystemExit(0 if configured else 2)
    except (ValueError, OSError, getpass.GetPassWarning):
        print(json.dumps({"status": "configuration_error", "values_disclosed": False}))
        raise SystemExit(3) from None


if __name__ == "__main__":
    main()
