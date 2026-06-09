"""Cross-platform resolution of the Cursor web session token.

Why this exists
---------------
A personal Cursor API key (``crsr_...``) only reaches the Agent API
(``api.cursor.com/v1/*``). It CANNOT read usage/spend -- those endpoints reject
it with "Invalid Team API Key". The data the web dashboard shows comes from
``cursor.com/api/*`` and is gated by a WorkOS *session* cookie
(``WorkosCursorSessionToken``), not the API key.

The Cursor app/CLI stores that session JWT locally. We read it from whichever of
these is available, in priority order (all are local-only; nothing is sent
anywhere except cursor.com):

1. ``$CURSOR_SESSION_TOKEN`` -- explicit override (raw JWT, or full ``sub::jwt``).
2. macOS Keychain service ``cursor-access-token`` (used by ``cursor-agent``).
3. OS keyring via the optional ``keyring`` package (Linux Secret Service /
   Windows Credential Locker / macOS Keychain).
4. The Cursor IDE SQLite state DB (``state.vscdb`` -> ``cursorAuth/accessToken``),
   whose layout is identical on macOS, Linux and Windows.

The dashboard cookie value is ``<workos_sub>::<jwt>``; ``sub`` is the ``sub``
claim of the JWT, so we can derive the whole cookie from just the token.
"""

import base64
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

KEYCHAIN_SERVICE = "cursor-access-token"
KEYCHAIN_ACCOUNT = "cursor-user"


class SessionNotFound(RuntimeError):
    """Raised when no Cursor session token can be located."""


def _jwt_claims(token):
    """Decode a JWT payload to a dict, or ``{}`` if it can't be parsed."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore base64url padding
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _cookie_id(claims):
    """Return the cookie id from a token's ``sub`` claim, or ``None``.

    WorkOS subjects look like ``<connection>|<user_id>`` (e.g.
    ``github|user_01ABC...``). The dashboard cookie wants the bare ``user_...``
    part (what ``/api/auth/me`` reports as ``sub``), so strip any connection
    prefix before the last ``|``.
    """
    sub = claims.get("sub")
    return sub.split("|")[-1] if sub else None


def _from_env():
    return os.environ.get("CURSOR_SESSION_TOKEN")


def _from_macos_keychain():
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _from_keyring():
    try:
        import keyring  # optional dependency
    except Exception:
        return None
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception:
        return None


def _state_db_candidates():
    """Yield possible Cursor IDE ``state.vscdb`` paths for the current OS."""
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    else:  # linux / other unix
        base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    for app in ("Cursor", "Cursor Nightly"):
        yield base / app / "User" / "globalStorage" / "state.vscdb"


def _from_state_db():
    for path in _state_db_candidates():
        if not path.exists():
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key = ?",
                    ("cursorAuth/accessToken",),
                ).fetchone()
            finally:
                con.close()
        except Exception:
            continue
        if row and row[0]:
            value = row[0]
            if isinstance(value, bytes):
                value = value.decode("utf-8", "ignore")
            return value.strip().strip('"')
    return None


# Local credential stores, tried in order (env override is handled separately).
_LOCAL_SOURCES = (
    ("macOS keychain", _from_macos_keychain),
    ("OS keyring", _from_keyring),
    ("Cursor state DB", _from_state_db),
)


def _log(verbose, name):
    if verbose:
        print("[auth] using session from %s" % name, file=sys.stderr)


def resolve_cookie_value(verbose=False):
    """Return ``"<id>::<jwt>"`` suitable for the dashboard cookie.

    Only a WorkOS *session* token authenticates the dashboard; an
    ``api_key_token`` (which ``cursor-agent`` may store in the keychain) returns
    HTTP 204 and is skipped. Raises :class:`SessionNotFound` if none is found.
    """
    # 1. Explicit override always wins (raw JWT, or full ``id::jwt`` cookie).
    env = _from_env()
    if env:
        env = env.strip().replace("%3A%3A", "::")
        if "::" in env:
            _log(verbose, "$CURSOR_SESSION_TOKEN")
            return env
        cid = _cookie_id(_jwt_claims(env))
        if cid:
            _log(verbose, "$CURSOR_SESSION_TOKEN")
            return "%s::%s" % (cid, env)

    # 2. Local stores -- require a session token; skip api_key_token.
    tried = ["$CURSOR_SESSION_TOKEN"]
    saw_api_key = False
    for name, source in _LOCAL_SOURCES:
        tried.append(name)
        token = source()
        if not token:
            continue
        token = token.strip().replace("%3A%3A", "::")
        if "::" in token:  # already a full "id::jwt" cookie value
            _log(verbose, name)
            return token
        claims = _jwt_claims(token)
        cid = _cookie_id(claims)
        if not cid:
            continue
        if claims.get("type") == "api_key_token":
            saw_api_key = True  # valid token, but not a *web* session
            continue
        _log(verbose, name)
        return "%s::%s" % (cid, token)

    hint = ""
    if saw_api_key:
        hint = ("\nNote: found an api_key_token (Agent API), but that does not "
                "authenticate the\nusage dashboard. A *web session* is needed.")
    raise SessionNotFound(
        "Could not find a usable Cursor session token.\n"
        "Tried: %s.%s\n\n"
        "Fix one of:\n"
        "  - Sign in via the Cursor app (this stores a web session), or\n"
        "  - Set CURSOR_SESSION_TOKEN to your WorkosCursorSessionToken cookie\n"
        "    (cursor.com -> DevTools -> Application -> Cookies)."
        % (", ".join(tried), hint)
    )
