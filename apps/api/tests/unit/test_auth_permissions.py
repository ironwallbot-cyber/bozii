"""Unit tests: authentication primitives, rate limiting, permission logic."""

from __future__ import annotations

from bozii.security import ratelimit
from bozii.security.auth import hash_password, hash_token, verify_password
from bozii.security.permissions import (
    PathEscapeError,
    assert_public_url,
    check_permission,
    intersect_permissions,
    requires_approval,
    safe_path,
)


def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong password", stored)
    assert not verify_password("correct horse battery staple", "malformed")


def test_password_hashes_are_salted():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_token_hash_is_stable():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")


def test_rate_limit_blocks_after_limit():
    ratelimit.reset()
    key = "unit-test-key"
    allowed = [ratelimit.hit(key, 3, 60)[0] for _ in range(5)]
    assert allowed == [True, True, True, False, False]
    ratelimit.reset()


def test_permission_intersection_never_widens():
    a = {"fs": "workspace", "net": "fetch", "exec": "sandbox", "delegation": True, "publish": False}
    b = {"fs": "workspace", "net": "search", "exec": "none", "delegation": False, "publish": True}
    merged = intersect_permissions(a, b)
    assert merged["net"] == "search"      # narrowest wins
    assert merged["exec"] == "none"
    assert merged["delegation"] is False  # False AND True
    assert merged["publish"] is False


def test_check_permission_denies_missing():
    granted = {"fs": "workspace", "net": "search", "exec": "none"}
    check_permission(granted, {"fs": "workspace"}, "read")  # satisfied
    try:
        check_permission(granted, {"exec": "sandbox"}, "run")
        raise AssertionError("expected PermissionDenied")
    except Exception as exc:
        assert "exec" in str(exc)
    try:
        check_permission(granted, {"net": "fetch"}, "fetch")
        raise AssertionError("expected PermissionDenied")
    except Exception as exc:
        assert "fetch" in str(exc)


def test_requires_approval_for_consequential_tools():
    class T:
        risk = "consequential"
        required_permissions = {}

    class Safe:
        risk = "safe"
        required_permissions = {}

    class Publish:
        risk = "safe"
        required_permissions = {"publish": True}

    assert requires_approval(T(), {}) is True
    assert requires_approval(Safe(), {}) is False
    assert requires_approval(Publish(), {}) is True


def test_safe_path_confines(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    assert safe_path(root, "a/b.txt") == (root / "a/b.txt").resolve()
    for attempt in ("../escape", "/etc/passwd", "~/secrets"):
        try:
            safe_path(root, attempt)
            raise AssertionError(f"expected escape rejection for {attempt}")
        except PathEscapeError:
            pass


def test_public_url_guard_blocks_private(monkeypatch):
    for url in (
        "ftp://example.com/x",
        "http://localhost/admin",
        "http://127.0.0.1:8080/",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/internal",
    ):
        try:
            assert_public_url(url)
            raise AssertionError(f"expected block for {url}")
        except Exception:
            pass
