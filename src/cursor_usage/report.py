"""Turn raw API payloads into summaries, day breakdowns and CSV rows."""

import csv
from collections import OrderedDict
from datetime import datetime, timezone


# --- field extraction -----------------------------------------------------
def _i(d, k):
    try:
        return int(d.get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _f(d, k):
    try:
        return float(d.get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def event_row(ev):
    """Flatten one ``usageEventsDisplay`` entry into a plain dict."""
    tu = ev.get("tokenUsage") or {}
    ts_ms = _i(ev, "timestamp")
    local = datetime.fromtimestamp(ts_ms / 1000).astimezone() if ts_ms else None
    return OrderedDict([
        ("datetime_local", local.isoformat() if local else ""),
        ("timestamp_ms", ts_ms),
        ("date", local.strftime("%Y-%m-%d") if local else ""),
        ("model", ev.get("model", "")),
        ("kind", ev.get("kind", "")),
        ("input_tokens", _i(tu, "inputTokens")),
        ("output_tokens", _i(tu, "outputTokens")),
        ("cache_read_tokens", _i(tu, "cacheReadTokens")),
        ("cache_write_tokens", _i(tu, "cacheWriteTokens")),
        ("value_cents", round(_f(tu, "totalCents"), 6)),
        ("charged_cents", round(_f(ev, "chargedCents"), 6)),
        ("requests_costs", ev.get("requestsCosts", 0)),
        ("is_headless", bool(ev.get("isHeadless", False))),
        ("owning_user", ev.get("owningUser", "")),
    ])


# --- formatting helpers ---------------------------------------------------
def _money(cents):
    return "$%s" % format(cents / 100.0, ",.2f")


def _n(x):
    return format(int(x), ",")


def _rule(width=78):
    return "-" * width


# --- summary (from aggregated endpoint) -----------------------------------
def render_summary(agg, meta):
    rows = agg.get("aggregations", []) or []
    cents = lambda r: _f(r, "totalCents")
    total = sum(cents(r) for r in rows)
    ti = sum(_i(r, "inputTokens") for r in rows)
    to = sum(_i(r, "outputTokens") for r in rows)
    tcr = sum(_i(r, "cacheReadTokens") for r in rows)
    tcw = sum(_i(r, "cacheWriteTokens") for r in rows)

    out = ["=" * 78]
    out.append("CURSOR USAGE  |  %s  |  %s -> %s"
               % (meta["email"], meta["start"], meta["end"]))
    out.append("=" * 78)
    out.append("Included value used : %s   (compute consumed; included in plan)" % _money(total))
    out.append("Tokens   in=%s  out=%s" % (_n(ti), _n(to)))
    out.append("         cacheRead=%s  cacheWrite=%s" % (_n(tcr), _n(tcw)))
    out.append(_rule())
    out.append("%-36s%10s%14s%12s" % ("model", "$ value", "in tok", "out tok"))
    out.append(_rule())
    for r in sorted(rows, key=lambda x: -cents(x)):
        out.append("%-36s%10s%14s%12s" % (
            r.get("modelIntent", "?"),
            format(cents(r) / 100.0, ",.2f"),
            _n(_i(r, "inputTokens")),
            _n(_i(r, "outputTokens")),
        ))
    return "\n".join(out)


# --- per-day breakdown (from events) --------------------------------------
def render_by_day(events, meta):
    days = OrderedDict()
    for ev in events:
        row = event_row(ev)
        d = row["date"] or "unknown"
        b = days.setdefault(d, {"n": 0, "in": 0, "out": 0, "cents": 0.0})
        b["n"] += 1
        b["in"] += row["input_tokens"]
        b["out"] += row["output_tokens"]
        b["cents"] += row["value_cents"]

    out = ["=" * 78]
    out.append("CURSOR USAGE BY DAY  |  %s  |  %s -> %s"
               % (meta["email"], meta["start"], meta["end"]))
    out.append("=" * 78)
    out.append("%-12s%9s%12s%15s%13s" % ("date", "events", "$ value", "in tok", "out tok"))
    out.append(_rule())
    tot = {"n": 0, "in": 0, "out": 0, "cents": 0.0}
    for d in sorted(days):
        b = days[d]
        out.append("%-12s%9s%12s%15s%13s" % (
            d, _n(b["n"]), format(b["cents"] / 100.0, ",.2f"), _n(b["in"]), _n(b["out"])))
        for k in tot:
            tot[k] += b[k]
    out.append(_rule())
    out.append("%-12s%9s%12s%15s%13s" % (
        "TOTAL", _n(tot["n"]), format(tot["cents"] / 100.0, ",.2f"),
        _n(tot["in"]), _n(tot["out"])))
    return "\n".join(out)


# --- CSV ------------------------------------------------------------------
def write_csv(events, path):
    rows = [event_row(e) for e in events]
    rows.sort(key=lambda r: r["timestamp_ms"])
    fields = list(event_row({}).keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
