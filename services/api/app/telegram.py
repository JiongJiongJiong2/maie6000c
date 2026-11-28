from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import secrets
from collections import deque
from hashlib import sha256
from math import ceil
from time import monotonic
from unicodedata import normalize
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from services.api.app.accounts import COOKIE
from services.api.app.search import Database, authorize, fail, read_media
from services.common.accounts import digest
from services.common.config import get_settings
from services.common.search_models import Candidate

logger = logging.getLogger(__name__)
QR_TIMEOUT = 180
SESSION_TIMEOUT = 900
MAX_SESSIONS = 8
PHONE_COOLDOWN = 45


def require_telegram(request: Request) -> None:
    settings = get_settings()
    if not (
        (settings.account_login_enabled or settings.device_token)
        and settings.telegram_api_id
        and settings.telegram_api_hash
    ):
        raise fail(
            503,
            "telegram_unconfigured",
            "Saving to Telegram is currently unavailable on this site.",
        )
    loopback = (
        request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if request.url.scheme != "https" and not loopback:
        raise fail(
            403, "telegram_https_required", "Open this site over HTTPS to connect to Telegram."
        )


router = APIRouter(prefix="/telegram", dependencies=[Depends(require_telegram), Depends(authorize)])
sessions: dict[str, TelegramSession] = {}
save_lock = asyncio.Lock()
recent_codes: deque[tuple[float, str]] = deque()


class PhoneLogin(BaseModel):
    phone: SecretStr
    region: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class LoginSecret(BaseModel):
    value: SecretStr


def browser_key(request: Request) -> str:
    if get_settings().account_login_enabled:
        return digest(request.cookies.get(COOKIE, ""))
    return "device"


def rate_limited(seconds: float) -> HTTPException:
    wait = max(1, ceil(seconds))
    return HTTPException(
        429,
        detail={
            "code": "telegram_code_rate_limited",
            "message": "Too many verification attempts. Wait before trying again.",
            "retry_after": wait,
        },
        headers={"Retry-After": str(wait)},
    )


class TelegramSession:
    def __init__(self, client, owner: str, *, phone_login: bool = False):
        self.client = client
        self.owner = owner
        self.phone_login = phone_login
        self.authorized = asyncio.Event()
        self.login_step = ""
        self.phone = ""
        self.attempts = 0
        self.ready = False
        self.closing = False
        self.qr = ""
        self.error = ""
        self.error_code = ""
        self.saved: dict[bytes, int] = {}
        self.pending: dict[bytes, object] = {}
        self.deadline = monotonic() + QR_TIMEOUT
        self.lock = asyncio.Lock()
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self.run())

    def complete_auth(self):
        self.ready = True
        self.phone = ""
        self.login_step = ""
        self.deadline = monotonic() + SESSION_TIMEOUT
        self.authorized.set()

    async def close(self) -> None:
        self.stop.set()
        if not self.ready and not self.closing and not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def run(self) -> None:
        import qrcode
        from telethon import errors

        try:
            async with asyncio.timeout(QR_TIMEOUT):
                if self.phone_login:
                    await self.authorized.wait()
                else:
                    await self.client.connect()
                    login = await self.client.qr_login()
                    while not self.stop.is_set():
                        png = io.BytesIO()
                        qrcode.make(login.url).save(png, format="PNG")
                        self.qr = base64.b64encode(png.getvalue()).decode("ascii")
                        try:
                            await login.wait()
                            break
                        except TimeoutError:
                            await login.recreate()
                    if not self.stop.is_set():
                        self.complete_auth()
            if self.stop.is_set():
                return
            self.qr = ""
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=SESSION_TIMEOUT)
            except TimeoutError:
                pass
        except errors.SessionPasswordNeededError:
            self.error_code = "telegram_qr_password_required"
            self.error = "This account has two-step verification. Use your phone number to sign in."
        except TimeoutError:
            self.error_code = "telegram_login_timeout"
            self.error = "Telegram sign-in timed out. Start again."
        except (errors.RPCError, OSError) as exc:
            self.error_code = "telegram_connection_failed"
            self.error = "Could not connect to Telegram. Try again in a moment."
            logger.warning("telegram_login_failed:%s", type(exc).__name__)
        finally:
            self.closing = True
            self.phone = ""
            self.qr = ""
            async with self.lock:
                self.ready = False
                try:
                    async with asyncio.timeout(5):
                        if self.client.is_connected() and await self.client.is_user_authorized():
                            await self.client.log_out()
                except (TimeoutError, errors.RPCError, OSError) as exc:
                    logger.warning("telegram_logout_failed:%s", type(exc).__name__)
                finally:
                    await self.client.disconnect()


async def close_telegram_sessions() -> None:
    active = list(sessions.values())
    sessions.clear()
    recent_codes.clear()
    await asyncio.gather(*(session.close() for session in active))


async def disconnect_browser(request: Request) -> None:
    owner = browser_key(request)
    selected = [key for key, session in sessions.items() if session.owner == owner]
    await asyncio.gather(*(sessions.pop(key).close() for key in selected))


def get_session(request: Request) -> TelegramSession:
    session = sessions.get(request.headers.get("x-telegram-session", ""))
    if session is None or session.owner != browser_key(request) or session.stop.is_set():
        raise fail(
            404,
            "telegram_session_missing",
            "Your Telegram session has expired. Reconnect to continue.",
        )
    if (session.task.done() or monotonic() >= session.deadline) and not session.error:
        raise fail(
            404,
            "telegram_session_missing",
            "Your Telegram session has expired. Reconnect to continue.",
        )
    return session


def new_session(request: Request, *, phone_login: bool = False) -> tuple[str, TelegramSession]:
    try:
        import qrcode  # noqa: F401
        from telethon import TelegramClient
        from telethon.sessions import MemorySession
    except ImportError as exc:
        raise fail(
            503,
            "telegram_unconfigured",
            "Saving to Telegram is currently unavailable on this site.",
        ) from exc
    for handle in [key for key, session in sessions.items() if session.task.done()]:
        del sessions[handle]
    if len(sessions) >= MAX_SESSIONS:
        raise fail(
            429, "telegram_busy", "Too many Telegram sessions are active. Try again in a moment."
        )
    settings = get_settings()
    handle = secrets.token_urlsafe(32)
    sessions[handle] = TelegramSession(
        TelegramClient(
            MemorySession(),
            settings.telegram_api_id,
            settings.telegram_api_hash.get_secret_value(),
            device_model="MemeRetrieve GIF",
            timeout=7,
            connection_retries=1,
            request_retries=1,
            flood_sleep_threshold=0,
        ),
        browser_key(request),
        phone_login=phone_login,
    )
    return handle, sessions[handle]


@router.post("/session", status_code=201)
async def start_session(request: Request, response: Response) -> dict:
    handle, _ = new_session(request)
    response.headers["Cache-Control"] = "no-store"
    return {"session": handle}


def phone_metadata():
    try:
        import phonenumbers
    except ImportError as exc:
        raise fail(
            503,
            "telegram_unconfigured",
            "Saving to Telegram is currently unavailable on this site.",
        ) from exc
    return phonenumbers


@router.get("/regions")
async def phone_regions() -> dict[str, int]:
    numbers = phone_metadata()
    return {
        region: numbers.country_code_for_region(region)
        for region in sorted(numbers.SUPPORTED_REGIONS)
    }


def normalize_phone(payload: PhoneLogin) -> str:
    numbers = phone_metadata()
    entered = normalize("NFKC", payload.phone.get_secret_value()).strip()
    phone = re.sub(r"[\s()-]", "", entered)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    invalid = fail(
        422,
        "telegram_invalid_phone",
        "Check the country code and number length, or paste the full number starting with +.",
    )
    if len(entered) > 40 or not re.fullmatch(r"\+?[0-9]{4,15}", phone):
        raise invalid
    try:
        parsed = numbers.parse(phone, payload.region)
    except numbers.NumberParseException:
        raise invalid from None
    if not numbers.is_possible_number(parsed):
        raise invalid
    return numbers.format_number(parsed, numbers.PhoneNumberFormat.E164)


@router.post("/session/phone", status_code=201)
async def start_phone_login(payload: PhoneLogin, request: Request, response: Response) -> dict:
    phone = normalize_phone(payload)
    now = monotonic()
    while recent_codes and recent_codes[0][0] <= now - 60:
        recent_codes.popleft()
    owner = browser_key(request)
    last_attempt = next((when for when, key in reversed(recent_codes) if key == owner), None)
    if last_attempt is not None and now - last_attempt < PHONE_COOLDOWN:
        raise rate_limited(last_attempt + PHONE_COOLDOWN - now)
    if len(recent_codes) >= MAX_SESSIONS:
        raise rate_limited(recent_codes[0][0] + 60 - now)
    handle, session = new_session(request, phone_login=True)
    from telethon import errors, types

    recent_codes.append((now, owner))
    try:
        async with asyncio.timeout(25), session.lock:
            await session.client.connect()
            sent = await session.client.send_code_request(phone)
            if isinstance(sent.type, types.auth.SentCodeTypeApp):
                message = "Check the Telegram service chat, then enter the code in this tab."
            elif isinstance(sent.type, (types.auth.SentCodeTypeSms, types.auth.SentCodeTypeCall)):
                message = "Check this phone for the code from Telegram, then enter it in this tab."
            else:
                raise fail(
                    409,
                    "telegram_code_unsupported",
                    "Telegram requires a verification method this site does not support. "
                    "Check the phone number or try again from a device signed in to Telegram.",
                )
            session.phone = phone
            session.login_step = "code"
    except errors.PhoneNumberInvalidError as exc:
        raise fail(
            422,
            "telegram_invalid_phone",
            "Telegram did not recognize this phone number. Check it and try again.",
        ) from exc
    except errors.FloodWaitError as exc:
        raise rate_limited(exc.seconds) from exc
    except (errors.FloodError, errors.PhoneNumberFloodError) as exc:
        raise fail(
            429,
            "telegram_code_rate_limited",
            "Telegram has limited verification requests. Try again later.",
        ) from exc
    except (errors.RPCError, OSError, TimeoutError) as exc:
        logger.warning("telegram_phone_login_failed:%s", type(exc).__name__)
        raise fail(
            502,
            "telegram_code_unavailable",
            "Telegram could not send a code. Try again in a moment.",
        ) from exc
    finally:
        if not session.login_step:
            sessions.pop(handle, None)
            await session.close()
    response.headers["Cache-Control"] = "no-store"
    return {
        "session": handle,
        "state": "code",
        "message": message,
        "retry_after": PHONE_COOLDOWN,
    }


@router.post("/session/{step}")
async def verify_phone_login(
    step: str, payload: LoginSecret, request: Request, response: Response
) -> dict:
    session = get_session(request)
    from telethon import errors

    value = payload.value.get_secret_value()
    is_code = step == "code"
    if (is_code and not re.fullmatch(r"[0-9]{3,10}", value)) or (
        not is_code and not 1 <= len(value) <= 256
    ):
        message = (
            "Enter the numeric code Telegram sent you."
            if is_code
            else "Enter your two-step verification password."
        )
        raise fail(400, "telegram_invalid_login_value", message)
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(25), session.lock:
            if session.ready:
                return {"state": "authorized"}
            if session.closing or session.stop.is_set() or monotonic() >= session.deadline:
                raise fail(
                    404,
                    "telegram_session_missing",
                    "Your sign-in attempt has expired. Start again.",
                )
            if step not in {"code", "password"} or session.login_step != step:
                raise fail(
                    400,
                    "telegram_unexpected_login_step",
                    "Complete the current sign-in step before continuing.",
                )
            if session.attempts >= 5:
                session.task.cancel()
                raise fail(
                    429,
                    "telegram_login_restart",
                    "Too many verification attempts. Request a new code.",
                )
            session.attempts += 1
            try:
                if is_code:
                    await session.client.sign_in(phone=session.phone, code=value)
                else:
                    await session.client.sign_in(password=value)
            except errors.SessionPasswordNeededError:
                session.login_step = "password"
                session.phone = ""
                session.attempts = 0
                return {"state": "password"}
            if session.closing or session.stop.is_set():
                raise fail(
                    404,
                    "telegram_session_missing",
                    "Your sign-in attempt has expired. Start again.",
                )
            session.complete_auth()
    except errors.PhoneCodeInvalidError as exc:
        raise fail(
            400, "telegram_invalid_login_value", "That code is incorrect. Check it and try again."
        ) from exc
    except errors.PasswordHashInvalidError as exc:
        raise fail(
            400,
            "telegram_invalid_login_value",
            "That two-step verification password is incorrect. Try again.",
        ) from exc
    except errors.PhoneCodeExpiredError as exc:
        raise fail(
            404, "telegram_code_expired", "That code has expired. Request a new one."
        ) from exc
    except errors.FloodWaitError as exc:
        raise rate_limited(exc.seconds) from exc
    except (errors.RPCError, OSError, TimeoutError) as exc:
        logger.warning("telegram_verify_login_failed:%s", type(exc).__name__)
        raise fail(
            502,
            "telegram_verification_failed",
            "Telegram could not complete verification. Try again in a moment.",
        ) from exc
    return {"state": "authorized"}


@router.get("/session")
async def session_state(request: Request, response: Response) -> dict:
    session = get_session(request)
    response.headers["Cache-Control"] = "no-store"
    if session.error:
        return {"state": "failed", "message": session.error, "code": session.error_code}
    if session.ready and monotonic() < session.deadline:
        return {"state": "authorized"}
    if session.qr:
        return {"state": "waiting", "qr": session.qr}
    return {"state": "waiting"}


@router.delete("/session")
async def end_session(request: Request) -> dict:
    handle = request.headers.get("x-telegram-session", "")
    session = sessions.get(handle)
    if session is not None and session.owner == browser_key(request):
        sessions.pop(handle)
        await session.close()
    return {"state": "closed"}


def gif_bytes(candidate_id: UUID, db: Database) -> bytes:
    candidate = db.get(Candidate, str(candidate_id))
    if candidate is None:
        raise fail(404, "candidate_not_found", "The selected GIF is no longer available.")
    if candidate.media_format != "GIF" or candidate.frame_count < 2:
        raise fail(422, "telegram_requires_gif", "Choose an animated GIF.")
    return read_media(candidate_id, db).body


async def collect_gif(session: TelegramSession, data: bytes) -> None:
    from telethon import errors, functions, types, utils

    client = session.client
    digest = sha256(data).digest()

    async def saved_ids() -> set[int]:
        result = await client(functions.messages.GetSavedGifsRequest(hash=0))
        if not isinstance(result, types.messages.SavedGifs):
            raise fail(
                502, "telegram_unverified", "Telegram did not return your saved GIFs. Try again."
            )
        return {doc.id for doc in result.gifs}

    try:
        async with asyncio.timeout(55), save_lock, session.lock:
            if not session.ready or session.stop.is_set() or monotonic() >= session.deadline:
                raise fail(
                    404,
                    "telegram_session_missing",
                    "Your Telegram session has expired. Reconnect to continue.",
                )
            before = await saved_ids()
            if session.saved.get(digest) in before:
                return
            me = await client.get_me()
            config = await client(functions.help.GetAppConfigRequest(hash=0))
            key = "saved_gifs_limit_premium" if me.premium else "saved_gifs_limit_default"
            limit = next(
                (
                    item.value.value
                    for item in config.config.value
                    if item.key == key and isinstance(item.value, types.JsonNumber)
                ),
                None,
            )
            if limit is None:
                raise fail(
                    502,
                    "telegram_unverified",
                    "Could not check your Telegram GIF limit. Try again.",
                )
            document = session.pending.get(digest)
            if len(before) >= limit and (document is None or document.id not in before):
                raise fail(409, "telegram_collection_full", "Your Telegram GIF collection is full.")
            if document is None:
                file = await client.upload_file(
                    data, file_name=f"memeretrieve-{digest.hex()[:16]}.gif"
                )
                uploaded = await client(
                    functions.messages.UploadMediaRequest(
                        peer=types.InputPeerSelf(),
                        media=types.InputMediaUploadedDocument(
                            file=file,
                            mime_type="image/gif",
                            attributes=[types.DocumentAttributeAnimated()],
                        ),
                    ),
                )
                document = getattr(uploaded, "document", None)
                if not isinstance(document, types.Document) or not any(
                    isinstance(attr, types.DocumentAttributeAnimated)
                    for attr in document.attributes
                ):
                    raise fail(
                        502,
                        "telegram_invalid_animation",
                        "Telegram did not recognize this file as an animation. Choose another GIF.",
                    )
                if document.id in before:
                    session.saved[digest] = document.id
                    return
                session.pending[digest] = document
            reference = utils.get_input_document(document)
            # Re-add the new entry explicitly to trigger client synchronization.
            # A retry reuses the same document even if the previous request failed.
            if document.id in await saved_ids():
                await client(functions.messages.SaveGifRequest(id=reference, unsave=True))
            saved = await client(functions.messages.SaveGifRequest(id=reference, unsave=False))
            if not saved or document.id not in await saved_ids():
                raise fail(
                    502, "telegram_unverified", "Telegram did not confirm the save. Try again."
                )
            session.saved[digest] = document.id
            session.pending.pop(digest, None)
    except errors.FileReferenceExpiredError as exc:
        session.pending.pop(digest, None)
        raise fail(
            502, "telegram_save_failed", "The Telegram reference for this GIF expired. Try again."
        ) from exc
    except (errors.UnauthorizedError, errors.AuthKeyError) as exc:
        session.stop.set()
        raise fail(
            404,
            "telegram_session_missing",
            "Your Telegram session has expired. Reconnect to continue.",
        ) from exc
    except errors.FloodWaitError as exc:
        wait = max(1, exc.seconds)
        raise HTTPException(
            429,
            detail={
                "code": "telegram_save_rate_limited",
                "message": "Telegram has temporarily limited how often you can save GIFs.",
                "retry_after": wait,
            },
            headers={"Retry-After": str(wait)},
        ) from exc
    except (errors.GifIdInvalidError, errors.MediaInvalidError) as exc:
        raise fail(
            422,
            "telegram_invalid_animation",
            "Telegram could not save this animation. Choose another GIF.",
        ) from exc
    except (errors.RPCError, OSError, TimeoutError) as exc:
        logger.warning("telegram_save_failed:%s", type(exc).__name__)
        raise fail(
            502, "telegram_save_failed", "Telegram could not save this GIF. Try again in a moment."
        ) from exc


@router.post("/gifs/{candidate_id}")
async def save_candidate_gif(candidate_id: UUID, request: Request, db: Database) -> dict:
    session = get_session(request)
    if not session.ready:
        raise fail(
            409, "telegram_authorization_required", "Connect to Telegram before saving a GIF."
        )
    await collect_gif(session, await run_in_threadpool(gif_bytes, candidate_id, db))
    return {"saved": True}
