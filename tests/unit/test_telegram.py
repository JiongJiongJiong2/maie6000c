import asyncio
from datetime import datetime, timezone
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_telegram_requires_server_configuration(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "0")
    response = client.post("/telegram/session")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "telegram_unconfigured"


def test_authorizes_on_same_device_with_code_and_optional_password(monkeypatch):
    telethon = pytest.importorskip("telethon")
    pytest.importorskip("phonenumbers")
    from fastapi.testclient import TestClient

    from services.api.app import accounts, telegram
    from services.api.app.main import app
    from services.common.accounts import digest

    class Client:
        connected = False
        ready = False
        ended = False

        async def connect(self):
            self.connected = True

        def is_connected(self):
            return self.connected

        async def send_code_request(self, phone):
            assert phone == "+85255550123"
            return SimpleNamespace(type=telethon.types.auth.SentCodeTypeApp(length=5))

        async def sign_in(self, *, phone=None, code=None, password=None):
            if code is not None:
                assert phone == "+85255550123"
                if code != "12345":
                    raise telethon.errors.PhoneCodeInvalidError(request=None)
                raise telethon.errors.SessionPasswordNeededError(request=None)
            assert password == "test-pass"
            self.ready = True

        async def is_user_authorized(self):
            return self.ready

        async def log_out(self):
            self.ended = True

        async def disconnect(self):
            self.connected = False

    telegram_client = Client()
    monkeypatch.setattr(telethon, "TelegramClient", lambda *args, **kwargs: telegram_client)
    monkeypatch.setattr(
        accounts,
        "identify",
        lambda raw: SimpleNamespace(username=raw, workspace=f"acct_{digest(raw)[:32]}")
        if raw
        else None,
    )
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "test")
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "true")
    monkeypatch.setattr(telegram, "SESSION_TIMEOUT", 0.5)
    with TestClient(app, base_url="https://testserver") as browser:
        assert browser.get("/telegram/regions").status_code == 401
        headers = {"Cookie": "memeretrieve_session=alice"}
        regions = browser.get("/telegram/regions", headers=headers).json()
        assert regions["HK"] == 852 and regions["GB"] == 44
        invalid = browser.post(
            "/telegram/session/phone", headers=headers, json={"phone": "1234", "region": "HK"}
        )
        assert invalid.json()["detail"]["code"] == "telegram_invalid_phone"
        started = browser.post(
            "/telegram/session/phone", headers=headers, json={"phone": "5555 0123", "region": "HK"}
        )
        assert started.status_code == 201
        assert started.json()["state"] == "code"
        assert started.json()["retry_after"] == telegram.PHONE_COOLDOWN
        limited = browser.post(
            "/telegram/session/phone", headers=headers, json={"phone": "+85255550123"}
        )
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
        headers["X-Telegram-Session"] = started.json()["session"]
        other = {**headers, "Cookie": "memeretrieve_session=bob"}
        assert browser.get("/telegram/session", headers=other).status_code == 404
        assert browser.delete("/telegram/session", headers=other).status_code == 200
        rejected = browser.post("/telegram/session/code", headers=headers, json={"value": "99999"})
        assert rejected.status_code == 400
        assert "99999" not in rejected.text
        code = browser.post("/telegram/session/code", headers=headers, json={"value": "12345"})
        assert code.json() == {"state": "password"}
        password = browser.post(
            "/telegram/session/password", headers=headers, json={"value": "test-pass"}
        )
        assert password.json() == {"state": "authorized"}
        assert browser.get("/telegram/session", headers=headers).json() == {"state": "authorized"}
        for _ in range(40):
            if telegram_client.ended:
                break
            sleep(0.05)
        assert telegram_client.ended
        assert browser.get("/telegram/session", headers=headers).status_code == 404
        assert browser.delete("/telegram/session", headers=headers).json() == {"state": "closed"}
    assert telegram_client.ended


def test_phone_normalizes_trunk_prefix_full_paste_and_full_width_digits():
    pytest.importorskip("phonenumbers")
    from pydantic import SecretStr

    from services.api.app.telegram import PhoneLogin, normalize_phone

    def phone(value, region=None):
        return normalize_phone(PhoneLogin(phone=SecretStr(value), region=region))

    assert phone("07911 123456", "GB") == "+447911123456"
    assert phone("００８５２ ５５５５ ０１２３", "GB") == "+85255550123"


def test_explicitly_saves_new_gif_and_retries_without_reuploading():
    telethon = pytest.importorskip("telethon")
    from services.api.app.telegram import collect_gif

    functions, types = telethon.functions, telethon.types
    document = types.Document(
        id=22,
        access_hash=33,
        file_reference=b"test",
        date=datetime.now(timezone.utc),
        mime_type="video/mp4",
        size=64,
        dc_id=2,
        attributes=[types.DocumentAttributeAnimated()],
    )
    preserved = SimpleNamespace(id=11)

    class Telegram:
        gifs = {preserved.id, document.id}
        uploads = 0
        mutations = []
        reject_once = True

        async def get_me(self):
            return SimpleNamespace(premium=False)

        async def upload_file(self, data, *, file_name):
            assert data == b"test GIF"
            assert file_name.endswith(".gif")
            self.uploads += 1
            return types.InputFile(1, 1, file_name, "")

        async def __call__(self, request):
            if isinstance(request, functions.messages.GetSavedGifsRequest):
                return types.messages.SavedGifs(
                    hash=0,
                    gifs=[doc for doc in (preserved, document) if doc.id in self.gifs],
                )
            if isinstance(request, functions.help.GetAppConfigRequest):
                return SimpleNamespace(
                    config=types.JsonObject(
                        [types.JsonObjectValue("saved_gifs_limit_default", types.JsonNumber(200))]
                    )
                )
            if isinstance(request, functions.messages.UploadMediaRequest):
                assert isinstance(request.peer, types.InputPeerSelf)
                assert request.media.mime_type == "image/gif"
                self.gifs.add(document.id)
                return SimpleNamespace(document=document)
            assert isinstance(request, functions.messages.SaveGifRequest)
            assert request.id.id == document.id
            self.mutations.append(request.unsave)
            if request.unsave:
                self.gifs.remove(document.id)
            elif self.reject_once:
                self.reject_once = False
                return False
            else:
                self.gifs.add(document.id)
            return True

    async def exercise():
        client = Telegram()
        client.gifs = {preserved.id}
        session = SimpleNamespace(
            client=client,
            ready=True,
            saved={},
            pending={},
            lock=asyncio.Lock(),
            stop=asyncio.Event(),
            deadline=monotonic() + 60,
        )
        with pytest.raises(HTTPException) as error:
            await collect_gif(session, b"test GIF")
        assert error.value.detail["code"] == "telegram_unverified"
        assert client.gifs == {preserved.id}
        await collect_gif(session, b"test GIF")
        await collect_gif(session, b"test GIF")
        assert client.gifs == {preserved.id, document.id}
        assert client.uploads == 1
        assert client.mutations == [True, False, False]

    asyncio.run(exercise())
