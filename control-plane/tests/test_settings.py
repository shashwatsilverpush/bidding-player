from __future__ import annotations

from app.settings import Settings


def test_beacon_url_forces_https_scheme() -> None:
    # scheme-less PUBLIC_BASE_URL -> https prefixed
    assert Settings(public_base_url="host.example.org").beacon_url() == "https://host.example.org/e"
    # explicit scheme preserved, trailing slash trimmed
    assert Settings(public_base_url="https://x.org/").beacon_url() == "https://x.org/e"


def test_beacon_url_derives_from_request_base() -> None:
    s = Settings(public_base_url=None)
    # localhost keeps its scheme; a bare deployed host gets https
    assert s.beacon_url("http://localhost:8000") == "http://localhost:8000/e"
    assert s.beacon_url("staging.example.org") == "https://staging.example.org/e"
