import pytest

from scripts.check_public_beta import LIBRARY_PATH, check, origin_for


@pytest.mark.parametrize(
    "url,local",
    [
        ("http://product.example/web/", False),
        ("https://localhost/web/", False),
        ("https://192.168.1.1/", False),
        ("https://product.example/", True),
        ("https://user:secret@product.example/", False),
        ("https://product.example/web/?setup=secret", False),
    ],
)
def test_rejects_wrong_scope_and_credentials(url, local):
    with pytest.raises(ValueError):
        origin_for(url, local)


def test_accepts_only_explicit_loopback_rehearsal_or_https_site():
    assert origin_for("http://[::1]:8000/web/", True) == "http://[::1]:8000"
    assert origin_for("https://product.example/web/", False) == "https://product.example"


ORIGIN = "https://product.example"
RESPONSES = {
    ORIGIN + "/web/": (200, "text/html", b'<form id="account-form"><script src="./account.js">'),
    ORIGIN + "/health/ready": (200, "application/json", b'{"service":"api","status":"ok"}'),
    ORIGIN + LIBRARY_PATH: (401, "application/json", b'{"detail":"Sign in to open your library."}'),
}


def test_pass_describes_only_the_anonymous_entry():
    result = check(ORIGIN, False, RESPONSES.__getitem__)
    assert result["entry_passed"] is True
    assert "private library enabled after login" in result["unverified"]


@pytest.mark.parametrize(
    "path,response",
    [
        ("/web/", (200, "text/html", b"<form>unrelated login</form>")),
        ("/web/", (302, "text/html", b"")),
        ("/health/ready", (200, "application/json", b"invalid json")),
        ("/health/ready", (503, "application/json", b'{"detail":"Database unavailable"}')),
        (LIBRARY_PATH, (404, "application/json", b'{"detail":"Not Found"}')),
        (LIBRARY_PATH, (401, "application/json", b'{"detail":"proxy auth"}')),
    ],
)
def test_partial_or_unrelated_deployment_fails(path, response):
    responses = {**RESPONSES, ORIGIN + path: response}
    assert check(ORIGIN, False, responses.__getitem__)["entry_passed"] is False


def test_unreachable_service_reports_each_failure():
    def unreachable(url):
        raise TimeoutError

    result = check(ORIGIN, False, unreachable)
    assert result["entry_passed"] is False
    assert all(item["error"] == "TimeoutError" for item in result["checks"].values())
