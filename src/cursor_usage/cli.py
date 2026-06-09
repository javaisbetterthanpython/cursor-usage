"""Command-line entry point for cursor-usage."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from . import __version__
from .api import CursorAPIError, CursorClient
from .auth import SessionNotFound, resolve_cookie_value
from .report import render_by_day, render_summary, write_csv


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _resolve_window(args, client, user_id):
    """Return (start_ms, end_ms, start_label, end_label)."""
    now = datetime.now(timezone.utc)
    end = _parse_date(args.end) + timedelta(days=1) if args.end else now
    if args.start:
        start = _parse_date(args.start)
    elif args.days:
        start = now - timedelta(days=args.days)
    elif args.month:
        y, m = (int(x) for x in args.month.split("-"))
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        if not args.end:
            nm = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=timezone.utc)
            end = min(now, nm)
    else:
        # default: current billing month, per /api/usage startOfMonth
        som = client.usage(user_id).get("startOfMonth")
        start = (datetime.fromisoformat(som.replace("Z", "+00:00"))
                 if som else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    return _ms(start), _ms(end), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _progress(fetched, total):
    if total:
        sys.stderr.write("\r[events] %d/%d" % (fetched, total))
        sys.stderr.flush()
        if fetched >= total:
            sys.stderr.write("\n")


def build_parser():
    p = argparse.ArgumentParser(
        prog="cursor-usage",
        description="Show Cursor (cursor.com) usage, spend and per-event logs "
                    "for the locally signed-in account.",
    )
    p.add_argument("--by-day", action="store_true",
                   help="break usage down by calendar day (fetches per-event data)")
    p.add_argument("--csv", metavar="FILE",
                   help="write the per-event log to FILE as CSV")
    p.add_argument("--json", action="store_true",
                   help="print the raw aggregated-usage JSON and exit")
    g = p.add_argument_group("time window (default: current billing month)")
    g.add_argument("--start", metavar="YYYY-MM-DD", help="window start (inclusive)")
    g.add_argument("--end", metavar="YYYY-MM-DD", help="window end (inclusive)")
    g.add_argument("--days", type=int, metavar="N", help="last N days")
    g.add_argument("--month", metavar="YYYY-MM", help="a specific calendar month")
    p.add_argument("--page-size", type=int, default=1000,
                   help="events per API page when paginating (default: 1000)")
    p.add_argument("-v", "--verbose", action="store_true", help="log the token source")
    p.add_argument("-V", "--version", action="version",
                   version="cursor-usage-cli %s" % __version__)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cookie = resolve_cookie_value(verbose=args.verbose)
    except SessionNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 2

    client = CursorClient(cookie)
    try:
        me = client.me()
        user_id = me.get("id")
        email = me.get("email", "unknown")
        if not user_id:
            print("Session token is invalid or expired (auth/me returned no id).\n"
                  "Re-authenticate: cursor-agent login", file=sys.stderr)
            return 2

        start_ms, end_ms, start_label, end_label = _resolve_window(args, client, user_id)
        meta = {"email": email, "start": start_label, "end": end_label}

        if args.json:
            print(json.dumps(client.aggregated_usage(user_id, start_ms, end_ms), indent=2))
            return 0

        # The aggregated endpoint powers the summary (one cheap call).
        print(render_summary(client.aggregated_usage(user_id, start_ms, end_ms), meta))

        # Per-event data powers --by-day and --csv; fetch it once if needed.
        if args.by_day or args.csv:
            events, total = client.all_events(
                user_id, start_ms, end_ms, page_size=args.page_size, progress=_progress)
            if args.by_day:
                print()
                print(render_by_day(events, meta))
            if args.csv:
                n = write_csv(events, args.csv)
                print("\nWrote %d events to %s" % (n, args.csv))
    except CursorAPIError as exc:
        print("\nCursor API error (HTTP %s): %s" % (exc.status, exc.body[:300]), file=sys.stderr)
        if exc.status in (401, 403):
            print("Session may be expired. Re-authenticate: cursor-agent login", file=sys.stderr)
        return 1
    except OSError as exc:
        print("\nNetwork error talking to cursor.com: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
