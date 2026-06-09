# How this tool was built (a guide for the next LLM/engineer)

This document is a reproducible recipe for rebuilding `cursor-usage-cli` from
scratch — including the dead-ends — so another agent can recreate or extend it
without re-deriving everything. Nothing here is secret; it's all observable by
probing Cursor's own endpoints with a session you already own.

> Scope/ethics: this reads **your own** local Cursor session to query **your own**
> usage from Cursor's own servers. Don't use it against accounts you don't control.

## 1. The goal and the first wrong turn

Goal: "show my Cursor usage from the CLI." The obvious idea is to use a Cursor
**API key** (`crsr_…`). That's a dead end for usage:

- `GET https://api.cursor.com/v1/me` → `200` (key is valid, it's a *User* key).
- `GET https://api.cursor.com/v1/models` → `200`.
- Anything usage/spend/analytics (`/teams/daily-usage-data`,
  `/teams/filtered-usage-events`, `/analytics/team/*`) → `401 Invalid Team API Key`.

Conclusion: there are **two** key types. A *User/Agent* key (`crsr_…`) drives the
Agent/Background API only. Usage & spend live on the **Admin/Team API**, which
needs a different (team admin) key. If you only have a personal account, there is
**no API key** that returns your usage.

## 2. The insight: the dashboard uses a *session*, not an API key

The web dashboard at `cursor.com/dashboard` clearly shows usage, so an endpoint
exists — it's just gated differently. Probing:

- `GET https://cursor.com/api/usage?user=<id>` with the API key as a Bearer or
  cookie → `401 not_authenticated`. So it wants a real **session**, not the key.

Cursor authenticates the web app with a WorkOS session cookie named
`WorkosCursorSessionToken`. We need that token.

## 3. Finding the session token locally

The Cursor app and the `cursor-agent` CLI both store the session after login.
Two reliable, cross-platform sources:

- **macOS Keychain** (written by `cursor-agent`):
  `security find-generic-password -s cursor-access-token -w` → a JWT.
- **Cursor IDE SQLite state DB** (works on every OS, identical schema):
  `state.vscdb`, table `ItemTable`, key `cursorAuth/accessToken` → the same JWT.
  - macOS: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
  - Linux: `~/.config/Cursor/User/globalStorage/state.vscdb`
  - Windows: `%APPDATA%\Cursor\User\globalStorage\state.vscdb`

Decode the JWT payload (middle segment, base64url) to confirm it's a session:
`{"sub":"github|user_01…","aud":"https://cursor.com","type":"session", ...}`.
The `sub` claim matters next.

## 4. Cracking the cookie format

The cookie value is **not** just the JWT. Trying `/api/auth/me` with different
shapes:

| cookie value           | result                                   |
|------------------------|-------------------------------------------|
| `<jwt>`                | `204` (no identity)                       |
| `<numericUserId>::<jwt>` | `404 User not found`                    |
| `<sub>::<jwt>`         | **`200`** with `{email, id, sub, ...}`    |

So the format is `WorkosCursorSessionToken=<sub>::<jwt>`, where `<sub>` is the
JWT's `sub` claim (e.g. `user_01ABC…`). The `::` is sent URL-encoded as `%3A%3A`.

(Interesting wrinkle: `/api/usage` accepts both `numericUserId::jwt` and
`sub::jwt`, but `/api/auth/me` only accepts `sub::jwt`. Use `sub::jwt` — it works
for everything.)

## 5. The CSRF gotcha

The read endpoints (`GET /api/auth/me`, `GET /api/usage?user=…`) work with just
the cookie. The dashboard data is behind **POST** endpoints that add a CSRF
check:

- POST without an Origin header → `403 Invalid origin for state-changing request`.
- Add `Origin: https://cursor.com` → works.

## 6. The endpoints that matter

All on `https://cursor.com`, cookie `WorkosCursorSessionToken=<sub>::<jwt>`:

| method | path | purpose |
|--------|------|---------|
| GET  | `/api/auth/me` | identity: `email`, numeric `id`, `sub` |
| GET  | `/api/usage?user=<id>` | legacy request counter + `startOfMonth` (use for the billing-window start) |
| POST | `/api/dashboard/get-aggregated-usage-events` | per-model totals: `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens`, `totalCents` |
| POST | `/api/dashboard/get-filtered-usage-events` | per-event log + `totalUsageEventsCount` (paginate with `page`/`pageSize`) |
| POST | `/api/dashboard/get-hard-limit` | `{"noUsageBasedAllowed":true}` ⇒ overage off ⇒ everything is included |

POST body shape:
```json
{"teamId": 0, "startDate": "<epoch_ms>", "endDate": "<epoch_ms>", "userId": <id>}
```
`get-filtered-usage-events` additionally takes `"page": 1, "pageSize": 1000`.

Per-event entry (`usageEventsDisplay[]`) fields used here:
`timestamp` (ms string), `model`, `kind` (e.g. `USAGE_EVENT_KIND_INCLUDED_IN_ULTRA`),
`tokenUsage.{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens,totalCents}`,
`chargedCents`, `requestsCosts`, `isHeadless`, `owningUser`.

## 7. Turning it into a tool

- **Token resolution** (`auth.py`): env var → macOS keychain → `keyring` →
  state.vscdb. Derive `sub` from the JWT so the whole cookie comes from just the
  token. Accept a pre-formed `sub::jwt` (or `%3A%3A`) override too.
- **API client** (`api.py`): stdlib `urllib`; always send `Origin` on POST;
  paginate `all_events` until `len >= totalUsageEventsCount`.
- **Reporting** (`report.py`): summary from the aggregated endpoint; per-day
  buckets and CSV from the event log (bucket by local date).
- **CLI** (`cli.py`): default window = current billing month from
  `startOfMonth`; flags `--by-day`, `--csv`, `--days/--month/--start/--end`,
  `--json`.

## 8. Cross-OS notes

- Token: keychain is macOS-only; `keyring` covers Linux/Windows; the SQLite
  state DB covers all three with no dependency — prefer it as the universal path.
- Everything else (urllib, sqlite3, base64, csv) is stdlib and OS-agnostic.
- Windows edge case: if a future Cursor build encrypts the state-DB token
  (DPAPI), fall back to `CURSOR_SESSION_TOKEN` copied from the browser.

## 9. How to re-verify quickly (one-liner, macOS)

```bash
TOKEN=$(security find-generic-password -s cursor-access-token -w)
SUB=$(python3 -c "import base64,json,sys;p=sys.argv[1].split('.')[1];p+='='*(-len(p)%4);print(json.loads(base64.urlsafe_b64decode(p))['sub'])" "$TOKEN")
ID=$(curl -s -H "Cookie: WorkosCursorSessionToken=$SUB%3A%3A$TOKEN" https://cursor.com/api/auth/me | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X POST -H "Cookie: WorkosCursorSessionToken=$SUB%3A%3A$TOKEN" \
  -H "Content-Type: application/json" -H "Origin: https://cursor.com" \
  -d "{\"teamId\":0,\"startDate\":\"0\",\"endDate\":\"9999999999999\",\"userId\":$ID}" \
  https://cursor.com/api/dashboard/get-aggregated-usage-events
```

If that returns `aggregations`, the whole approach is intact and any breakage in
the Python tool is local, not protocol-level.
