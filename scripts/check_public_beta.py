"""Check the deployed sign-in page, API readiness and anonymous account gate with GETs."""

import argparse
import ipaddress
import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


# A single, nonexistent fixture ID avoids enumerating anyone's collection.
LIBRARY_PATH = "/library/assets/00000000-0000-0000-0000-000000000000"


def origin_for(url, local):
    parts = urlsplit(url)
    if (
        not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/", "/web", "/web/"}
        or parts.scheme not in {"http", "https"}
    ):
        raise ValueError("Supply the site origin or /web/ without credentials, query or fragment.")
    # Force validation of a non-numeric or out-of-range port before making a request.
    _ = parts.port
    host = parts.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    loopback = address.is_loopback if address else host == "localhost"
    if local and not loopback:
        raise ValueError("--local requires a loopback IP address or localhost.")
    if not local and (
        parts.scheme != "https" or loopback or (address is not None and not address.is_global)
    ):
        raise ValueError("Use the public HTTPS origin. For a loopback rehearsal, add --local.")
    return f"{parts.scheme}://{parts.netloc}"


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A different location cannot verify the advertised product entry.


def fetch(url):
    req = Request(url, headers={"User-Agent": "MemeRetrieve-beta-preflight/1"})
    try:
        response = build_opener(NoRedirects()).open(req, timeout=8)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers.get_content_type(), response.read(65536)


def check(origin, local, get=fetch):
    checks = {}
    for name, path in (
        ("sign_in_page", "/web/"),
        ("api_ready", "/health/ready"),
        ("anonymous_library_gate", LIBRARY_PATH),
    ):
        try:
            status, mime, body = get(origin + path)
            if name == "sign_in_page":
                passed = (
                    status == 200
                    and mime == "text/html"
                    and b'id="account-form"' in body
                    and b"./account.js" in body
                )
            elif name == "api_ready":
                passed = (
                    status == 200
                    and mime == "application/json"
                    and json.loads(body) == {"service": "api", "status": "ok"}
                )
            else:
                passed = (
                    status == 401
                    and mime == "application/json"
                    and json.loads(body) == {"detail": "Sign in to open your library."}
                )
            checks[name] = {"passed": passed, "http_status": status}
        except (URLError, OSError, HTTPException, ValueError) as exc:
            checks[name] = {"passed": False, "error": type(exc).__name__}
    return {
        "origin": origin,
        "scope": "loopback rehearsal" if local else "HTTPS entry from this machine",
        "entry_passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
        "unverified": [
            "private library enabled after login",
            "worker, model and external search providers",
            "independent tester access and end-to-end task completion",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Product origin or /web/ URL")
    parser.add_argument("--local", action="store_true", help="Rehearse on a loopback URL")
    args = parser.parse_args(argv)
    try:
        origin = origin_for(args.url, args.local)
    except ValueError as exc:
        parser.error(str(exc))
    report = check(origin, args.local)
    print(json.dumps(report, indent=2))
    return 0 if report["entry_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
