"""Browser account sessions and server-selected private workspaces."""

import hashlib
import hmac
import re
import secrets
from time import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from services.common.accounts import (
    accounts,
    digest,
    new_workspace,
    owner_setup,
    provision_workspace,
    sessions,
)
from services.common.config import get_settings, use_workspace
from services.common.db import get_session_factory

router = APIRouter(prefix="/auth")
COOKIE = "memeretrieve_session"
LIFETIME = 30 * 86400


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr
    owner_setup: str | None = Field(default=None, max_length=128)


class Registration(Credentials):
    beta_invite_code: SecretStr | None = None


def password_hash(password, salt):
    return hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024
    ).hex()


def identify(raw):
    if not raw or len(raw) > 128:
        return None
    with get_session_factory()() as db:
        return db.execute(
            select(accounts.c.username, accounts.c.workspace)
            .join(sessions)
            .where(sessions.c.digest == digest(raw), sessions.c.expires > int(time()))
        ).first()


async def select_account(request: Request, call_next):
    path = request.url.path
    if not get_settings().account_login_enabled:
        if path.startswith("/auth/"):
            return JSONResponse({"detail": "Accounts are disabled."}, status_code=404)
        return await call_next(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get(
            "sec-fetch-site"
        ) == "cross-site":
            return JSONResponse({"detail": "Open this action in your library."}, status_code=403)
    if path.startswith("/auth/") or path in {"/health/live", "/health/ready", "/metrics", "/"}:
        return await call_next(request)
    if path.startswith("/web/") and path != "/web/":
        return await call_next(
            request
        )  # Only explicitly shipped static assets or the sign-in page.
    account = await run_in_threadpool(identify, request.cookies.get(COOKIE))
    request.state.account = account
    if account is None and path not in {"/web", "/web/"}:
        return JSONResponse({"detail": "Sign in to open your library."}, status_code=401)
    expected = request.headers.get("x-library-account")
    if expected and (not account or expected != account.username):
        return JSONResponse({"detail": "Your signed-in account has changed."}, status_code=401)
    with use_workspace(account.workspace if account else "public"):
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def set_session(db, request, response, username):
    raw = secrets.token_urlsafe(32)
    now = int(time())
    previous = request.cookies.get(COOKIE, "")
    db.execute(
        sessions.delete().where(
            (sessions.c.expires <= now) | (sessions.c.digest == digest(previous))
        )
    )
    db.execute(
        sessions.insert().values(digest=digest(raw), username=username, expires=now + LIFETIME)
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        raw,
        max_age=LIFETIME,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"username": username}


def validated_credentials(payload):
    username = payload.username.strip().lower()
    password = payload.password.get_secret_value()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", username):
        raise HTTPException(
            422, "Use letters, digits, periods, underscores or hyphens for your username."
        )
    if len(password) > 256:
        raise HTTPException(422, "Use a password of up to 256 characters.")
    return username, password


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request, response: Response):
    settings = get_settings()
    if settings.beta_invite_required:
        supplied = payload.beta_invite_code.get_secret_value() if payload.beta_invite_code else ""
        if not hmac.compare_digest(
            supplied.encode(), settings.beta_invite_code.get_secret_value().encode()
        ):
            raise HTTPException(403, "Enter a valid beta invitation code to register.")
    username, password = validated_credentials(payload)
    if len(password) < 8:
        raise HTTPException(422, "Choose a password with at least 8 characters.")
    salt = secrets.token_hex(16)
    encoded = salt + ":" + password_hash(password, salt)
    with get_session_factory()() as db:
        name = new_workspace()
        if payload.owner_setup is not None:
            claimed = db.execute(
                owner_setup.delete().where(
                    owner_setup.c.id == 1,
                    owner_setup.c.digest == digest(payload.owner_setup),
                    owner_setup.c.expires > int(time()),
                )
            )
            if claimed.rowcount != 1:
                raise HTTPException(
                    409, "This setup link expired or was used. Reopen the Mac launcher."
                )
            name = "public"
        try:
            db.execute(
                accounts.insert().values(username=username, password_hash=encoded, workspace=name)
            )
        except IntegrityError as exc:
            raise HTTPException(409, "That username is already in use.") from exc
        if name != "public":
            provision_workspace(db, name)
        return set_session(db, request, response, username)


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response):
    username, password = validated_credentials(payload)
    with get_session_factory()() as db:
        encoded = db.scalar(select(accounts.c.password_hash).where(accounts.c.username == username))
        salt, _, expected = (encoded or ("00" * 16 + ":" + "00" * 64)).partition(":")
        if not hmac.compare_digest(password_hash(password, salt), expected) or not encoded:
            raise HTTPException(401, "Incorrect username or password.")
        return set_session(db, request, response, username)


@router.post("/logout")
def logout(request: Request, response: Response):
    with get_session_factory()() as db:
        db.execute(
            sessions.delete().where(sessions.c.digest == digest(request.cookies.get(COOKIE, "")))
        )
        db.commit()
    response.delete_cookie(
        COOKIE, httponly=True, samesite="strict", secure=request.url.scheme == "https"
    )
    response.headers["Cache-Control"] = "no-store"
    return {"signed_out": True}
