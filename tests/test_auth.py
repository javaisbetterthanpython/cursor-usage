import base64
import json

from cursor_usage.auth import _cookie_id, _jwt_claims


def _make_jwt(claims):
    seg = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header.%s.signature" % seg


def test_cookie_id_strips_connection_prefix():
    assert _cookie_id({"sub": "github|user_01ABC"}) == "user_01ABC"
    assert _cookie_id({"sub": "user_01ABC"}) == "user_01ABC"
    assert _cookie_id({}) is None


def test_jwt_claims_roundtrip():
    tok = _make_jwt({"sub": "github|user_01XYZ", "type": "session"})
    claims = _jwt_claims(tok)
    assert claims["type"] == "session"
    assert _cookie_id(claims) == "user_01XYZ"


def test_jwt_claims_handles_garbage():
    assert _jwt_claims("not-a-jwt") == {}
    assert _jwt_claims("") == {}
