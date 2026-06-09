from cursor_usage.report import event_row, render_by_day, render_summary, write_csv

SAMPLE = {
    "timestamp": "1780526996230",
    "model": "composer-2.5",
    "kind": "USAGE_EVENT_KIND_INCLUDED_IN_PRO",
    "tokenUsage": {
        "inputTokens": 100, "outputTokens": 20,
        "cacheReadTokens": 5, "cacheWriteTokens": 1, "totalCents": 12.5,
    },
    "chargedCents": 12.5, "requestsCosts": 1, "isHeadless": False, "owningUser": "42",
}
META = {"email": "you@example.com", "start": "2026-06-01", "end": "2026-06-08"}


def test_event_row_extracts_fields():
    r = event_row(SAMPLE)
    assert r["model"] == "composer-2.5"
    assert r["input_tokens"] == 100
    assert r["output_tokens"] == 20
    assert r["value_cents"] == 12.5
    assert r["date"].count("-") == 2  # YYYY-MM-DD


def test_event_row_tolerates_empty():
    r = event_row({})
    assert r["input_tokens"] == 0
    assert r["model"] == ""
    assert r["timestamp_ms"] == 0


def test_render_by_day_totals():
    out = render_by_day([SAMPLE, SAMPLE], META)
    assert "BY DAY" in out
    assert "TOTAL" in out
    assert "200" in out  # 100 in-tokens * 2 events


def test_render_summary_money():
    agg = {"aggregations": [
        {"modelIntent": "composer-2.5", "inputTokens": "1",
         "outputTokens": "2", "totalCents": 100},
    ]}
    out = render_summary(agg, META)
    assert "$1.00" in out
    assert "composer-2.5" in out


def test_write_csv(tmp_path):
    path = tmp_path / "out.csv"
    n = write_csv([SAMPLE], str(path))
    assert n == 1
    text = path.read_text()
    assert "input_tokens" in text  # header
    assert "composer-2.5" in text  # row
