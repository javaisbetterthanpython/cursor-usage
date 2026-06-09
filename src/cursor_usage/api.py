"""Minimal client for the Cursor dashboard usage API (stdlib only).

Endpoints used (all on ``https://cursor.com``):
  GET  /api/auth/me                                  -> {email, id, sub, ...}
  GET  /api/usage?user=<id>                          -> legacy counter + startOfMonth
  POST /api/dashboard/get-aggregated-usage-events    -> per-model tokens + cents
  POST /api/dashboard/get-filtered-usage-events       -> per-event log (paginated)

State-changing POSTs require an ``Origin: https://cursor.com`` header (CSRF guard).
Auth is the ``WorkosCursorSessionToken`` cookie, value ``<sub>::<jwt>`` (the ``::``
is sent URL-encoded as ``%3A%3A``).
"""

import json
import urllib.error
import urllib.request

from . import __version__

BASE = "https://cursor.com"
USER_AGENT = "cursor-usage/%s" % __version__


class CursorAPIError(RuntimeError):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__("HTTP %s: %s" % (status, body[:300]))


class CursorClient:
    def __init__(self, cookie_value, timeout=30):
        self._cookie = "WorkosCursorSessionToken=" + cookie_value.replace("::", "%3A%3A")
        self._timeout = timeout

    def _request(self, path, method="GET", body=None):
        headers = {
            "Cookie": self._cookie,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Origin"] = BASE  # required: dashboard CSRF check
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            raise CursorAPIError(exc.code, exc.read().decode("utf-8", "ignore"))
        return json.loads(raw) if raw else {}

    # -- endpoints ---------------------------------------------------------
    def me(self):
        return self._request("/api/auth/me")

    def usage(self, user_id):
        return self._request("/api/usage?user=%s" % user_id)

    def aggregated_usage(self, user_id, start_ms, end_ms):
        return self._request(
            "/api/dashboard/get-aggregated-usage-events", "POST",
            {"teamId": 0, "startDate": str(start_ms), "endDate": str(end_ms),
             "userId": user_id},
        )

    def _events_page(self, user_id, start_ms, end_ms, page, page_size):
        return self._request(
            "/api/dashboard/get-filtered-usage-events", "POST",
            {"teamId": 0, "startDate": str(start_ms), "endDate": str(end_ms),
             "userId": user_id, "page": page, "pageSize": page_size},
        )

    def all_events(self, user_id, start_ms, end_ms, page_size=1000, progress=None):
        """Fetch every usage event in the window by paginating.

        Returns ``(events, total_reported)``. ``progress(fetched, total)`` is
        called after each page if provided.
        """
        first = self._events_page(user_id, start_ms, end_ms, 1, page_size)
        total = int(first.get("totalUsageEventsCount", 0) or 0)
        events = list(first.get("usageEventsDisplay", []))
        if progress:
            progress(len(events), total)
        page = 2
        while len(events) < total and page <= 1000:  # 1000-page safety cap
            chunk = self._events_page(user_id, start_ms, end_ms, page, page_size)
            rows = chunk.get("usageEventsDisplay", [])
            if not rows:
                break
            events.extend(rows)
            if progress:
                progress(len(events), total)
            page += 1
        return events, total
