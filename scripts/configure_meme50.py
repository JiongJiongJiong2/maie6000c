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
import sys
import tempfile
import warnings
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "DEEPSEEK_API_KEY",
    "MEME50_HKUST_API_KEY",
    "MEME50_GEMINI_API_KEY",
    "MEME50_GOOGLE_VISION_API_KEY",
    "MEME50_BRAVE_API_KEY",
)
MODEL = "MEME50_VISION_MODEL"
HKUST_MODEL = "MEME50_HKUST_MODEL"
PROVIDER = "MEME50_VISION_PROVIDER"
DEEPSEEK_MODEL = "MEME50_DEEPSEEK_MODEL"
POLICY_FIELDS = {
    "MEME50_PROVIDER_POLICY": "hkust-deepseek-v1",
    "MEME50_KEYWORD_PROVIDER": "deepseek",
    "MEME50_REVERSE_IMAGE_PROVIDER": "disabled",
}


def merge_private_env(path: Path, updates: dict[str, str]):
    """Atomic, owner-only update; refuse symlinks and unsupported field names."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("configuration must be a regular file")
    if not set(updates) <= {*FIELDS, MODEL, HKUST_MODEL, DEEPSEEK_MODEL, PROVIDER, *POLICY_FIELDS}:
        raise ValueError("unsupported configuration field")
    updates = {key: value for key, value in updates.items() if value}
    if any(any(c in value for c in "\r\n\0") for value in updates.values()):
        raise ValueError("multiline configuration is not accepted")
    for field in [MODEL, HKUST_MODEL, DEEPSEEK_MODEL]:
        if field in updates and not re.fullmatch(r"[a-zA-Z0-9.\-]+", updates[field]):
            raise ValueError("invalid model identifier")
    if PROVIDER in updates and updates[PROVIDER] != "hkust":
        raise ValueError("unsupported vision provider")
    if any(k in updates and updates[k] != value for k, value in POLICY_FIELDS.items()):
        raise ValueError("unsupported provider policy")
    if not updates:
        return False
    existed = path.exists()
    original = path.read_text() if existed else ""
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
        with os.fdopen(fd, "w") as stream:
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
        if path.exists() != existed or (path.read_text() if path.exists() else "") != original:
            raise ValueError("configuration was concurrently modified")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def presence():
    from services.search_agent.meme_types import MemeSettings

    settings = MemeSettings()
    return dict(
        provider_policy=settings.provider_policy,
        vision_provider=settings.vision_provider,
        visual_key_present=bool(settings.hkust_api_key) and settings.vision_provider == "hkust",
        hkust_key_present=bool(settings.hkust_api_key),
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
        "--provider", choices=["hkust"], default="hkust", help="School vision service"
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
            print("Enter authorized credentials locally. Input is hidden; blank preserves values.")
            print("HKUST primary OR secondary: one school key, only for the HKUST vision provider.")
            print(
                "This task uses HKUST and DeepSeek only. No Google Vision or Brave key is needed."
            )
            vision_key = "MEME50_HKUST_API_KEY"
            fields = [] if args.search_only else [vision_key]
            if not args.vision_only:
                fields += ["DEEPSEEK_API_KEY"]
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                updates = {key: getpass.getpass(key + ": ") for key in fields}
            updates.update(POLICY_FIELDS)
            updates[PROVIDER] = "hkust"
            from services.search_agent.meme_types import MemeSettings

            settings = MemeSettings()
            print("Press Enter to use each shown default; probe verifies actual access.")
            if not args.search_only:
                updates[HKUST_MODEL] = (
                    input(f"{HKUST_MODEL} [{settings.hkust_model}]: ").strip()
                    or settings.hkust_model
                )
            if not args.vision_only:
                updates[DEEPSEEK_MODEL] = (
                    input(f"{DEEPSEEK_MODEL} [{settings.deepseek_model}]: ").strip()
                    or settings.deepseek_model
                )
            merge_private_env(ROOT / ".env", updates)
        report = presence()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(
            0
            if all(
                report[k]
                for k in (
                    ["visual_key_present"]
                    if args.vision_only
                    else ["deepseek_key_present"]
                    if args.search_only
                    else ["visual_key_present", "deepseek_key_present"]
                )
            )
            else 2
        )
    except (ValueError, OSError, getpass.GetPassWarning):
        print(json.dumps({"status": "configuration_error", "values_disclosed": False}))
        raise SystemExit(3) from None


if __name__ == "__main__":
    main()
