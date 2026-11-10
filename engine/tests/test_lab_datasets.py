import io
import json
import zipfile

import pytest

from lab_support import make_bars
from parable.errors import LabError
from parable.lab import datasets, llm
from parable.lab.consts import MAX_BARS_STORED
from parable.lab.datasets import ParsedTable, detect_columns, normalise, parse_upload


def csv_bytes(rows: int = 60, header: str = "Date,Open,High,Low,Close,Volume", day: int = 86400) -> bytes:
    lines = [header]
    for i in range(rows):
        t = 1_700_000_000 + i * day
        lines.append(f"{t},{100 + i},{101 + i},{99 + i},{100.5 + i},{1000 + i}")
    return "\n".join(lines).encode()


def xlsx_bytes(rows: list[list], shared: bool = True) -> bytes:
    strings: list[str] = []

    def ref(i: int, j: int) -> str:
        return f"{chr(65 + j)}{i + 1}"

    sheet = ['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for i, row in enumerate(rows):
        sheet.append(f'<row r="{i + 1}">')
        for j, value in enumerate(row):
            if isinstance(value, str) and shared:
                strings.append(value)
                sheet.append(f'<c r="{ref(i, j)}" t="s"><v>{len(strings) - 1}</v></c>')
            elif isinstance(value, str):
                sheet.append(f'<c r="{ref(i, j)}" t="inlineStr"><is><t>{value}</t></is></c>')
            else:
                sheet.append(f'<c r="{ref(i, j)}"><v>{value}</v></c>')
        sheet.append("</row>")
    sheet.append("</sheetData></worksheet>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", "".join(sheet))
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    return buffer.getvalue()


def docx_bytes(rows: list[list[str]]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>" for r in rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body><w:p/><w:tbl>{body}</w:tbl></w:body></w:document>')
    return buffer.getvalue()


def ohlc_rows(n: int = 40) -> list[list]:
    return [["time", "close"]] + [[1_700_000_000 + i * 3600, 10 + i] for i in range(n)]


def test_csv_tsv_semicolon_pipe_and_txt():
    for delim, name in ((",", "a.csv"), ("\t", "a.tsv"), (";", "a.csv"), ("|", "a.txt")):
        content = csv_bytes().decode().replace(",", delim).encode()
        table = parse_upload(name, content)
        assert table.columns[0] == "Date" and len(table.rows) == 60 and len(table.columns) == 6


def test_csv_with_bom_and_blank_lines():
    table = parse_upload("a.csv", b"\xef\xbb\xbftime,close\n\n1,2\n\n3,4\n")
    assert table.columns == ["time", "close"] and table.rows == [["1", "2"], ["3", "4"]]


def test_json_shapes():
    objects = json.dumps([{"time": 1, "close": 2}, {"time": 3, "close": 4}]).encode()
    arrays = json.dumps([["time", "close"], [1, 2], [3, 4]]).encode()
    wrapped = {k: json.dumps({k: [{"time": 1, "close": 2.5}]}).encode() for k in ("data", "rows", "candles")}
    assert parse_upload("a.json", objects).rows == [["1", "2"], ["3", "4"]]
    assert parse_upload("a.json", arrays).columns == ["time", "close"]
    for content in wrapped.values():
        assert parse_upload("a.json", content).rows == [["1", "2.5"]]
    for bad in (b"{", b"[]", b'{"x": 1}', b"[1,2,3]"):
        with pytest.raises(LabError) as err:
            parse_upload("a.json", bad)
        assert err.value.code == "bad_request"


def test_xlsx_shared_and_inline_strings():
    rows = [["Date", "Close"]] + [[45000 + i, 10.5 + i] for i in range(35)]
    for shared in (True, False):
        table = parse_upload("book.xlsx", xlsx_bytes(rows, shared))
        assert table.columns == ["Date", "Close"] and len(table.rows) == 35 and table.rows[0] == ["45000", "10.5"]
    bars, interval, _ = normalise(parse_upload("book.xlsx", xlsx_bytes(rows)), detect_columns(parse_upload("book.xlsx", xlsx_bytes(rows))))
    assert interval == "1d" and bars[0][0] == 1_678_838_400.0


def test_xlsx_formulas_are_not_evaluated():
    rows = [["time", "close"], [1_700_000_000, "=1+1"]]
    sheet_text = parse_upload("b.xlsx", xlsx_bytes(rows)).rows[0][1]
    assert sheet_text == "=1+1"


def test_docx_first_table():
    table = parse_upload("d.docx", docx_bytes([["Date", "Close"], ["1700000000", "5"], ["1700086400", "6"]]))
    assert table.columns == ["Date", "Close"] and table.rows[1] == ["1700086400", "6"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="x"><w:body/></w:document>')
    with pytest.raises(LabError):
        parse_upload("d.docx", buffer.getvalue())


def test_rejected_types_and_bad_files():
    for name, content in (("a.pdf", b"%PDF-1.4"), ("a.csv", b"%PDF-1.4 hello"), ("a.exe", b"x"),
                          ("a.xlsx", b"not a zip"), ("a.csv", b"\x00\x01\x02\x03"), ("a.csv", b"")):
        with pytest.raises(LabError) as err:
            parse_upload(name, content)
        assert err.value.status == 400 and err.value.code == "bad_request"
    other = io.BytesIO()
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(LabError):
        parse_upload("x.csv", other.getvalue())


def test_extension_is_not_trusted_for_zip_content():
    assert parse_upload("renamed.csv", xlsx_bytes(ohlc_rows())).columns == ["time", "close"]


def test_size_and_row_limits(monkeypatch):
    with pytest.raises(LabError) as err:
        parse_upload("a.csv", b"t,c\n" + b"1,2\n" * 1_300_000)
    assert err.value.status == 413 and err.value.code == "too_large"
    monkeypatch.setenv("UPLOAD_MAX_ROWS", "20")
    from parable.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(LabError) as err:
        parse_upload("a.csv", csv_bytes(30))
    assert err.value.status == 413


def test_zip_bomb_and_too_many_entries():
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", b"0" * 60_000_000)
    assert len(bomb.getvalue()) < 5_000_000
    with pytest.raises(LabError) as err:
        parse_upload("bomb.xlsx", bomb.getvalue())
    assert err.value.status == 413
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        for i in range(250):
            z.writestr(f"junk/{i}.txt", "x")
    with pytest.raises(LabError) as err:
        parse_upload("many.xlsx", many.getvalue())
    assert err.value.status == 413


def test_xml_entities_rejected():
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><worksheet>&a;</worksheet>')
    with pytest.raises(LabError):
        parse_upload("evil.xlsx", evil.getvalue())


def test_detect_columns_rules():
    def table(*cols):
        return ParsedTable(list(cols), [["1"] * len(cols)])

    full = detect_columns(table(" Timestamp ", "OPEN", "High", "LOW", "Adj Close", "Vol"))
    assert full == {"t": " Timestamp ", "open": "OPEN", "high": "High", "low": "LOW", "close": "Adj Close", "volume": "Vol"}
    for name in ("close", "c", "adj close", "adj_close", "price", "last", "nav", "value"):
        assert detect_columns(table("Date", name))["close"] == name
    for name in ("time", "timestamp", "date", "datetime", "t", "day", "period"):
        assert detect_columns(table(name, "close"))["t"] == name
    only_price = detect_columns(table("date", "NAV"))
    assert only_price == {"t": "date", "open": "NAV", "high": "NAV", "low": "NAV", "close": "NAV"}
    assert detect_columns(table("foo", "close")) is None
    assert detect_columns(table("date", "foo")) is None


def mapped(rows, cols=("date", "close")):
    table = ParsedTable(list(cols), rows)
    return normalise(table, detect_columns(table))


def test_normalise_time_formats():
    day = lambda i: f"2024-01-{i + 1:02d}"
    bars, interval, warnings = mapped([[day(i), str(10 + i)] for i in range(30)])
    assert interval == "1d" and bars[0][0] == 1_704_067_200.0 and not warnings
    bars, _, _ = mapped([[f"{1_700_000_000_000 + i * 86_400_000}", "5"] for i in range(30)])
    assert bars[0][0] == 1_700_000_000.0
    bars, _, _ = mapped([[f"2024-01-01T{i % 24:02d}:00:00Z".replace("01T", f"{1 + i // 24:02d}T"), "5"] for i in range(48)])
    assert bars[1][0] - bars[0][0] == 3600
    bars, interval, _ = mapped([[f"2024-03-{i + 1:02d} 10:00:00+02:00", "5"] for i in range(30)])
    assert bars[0][0] == 1_709_280_000.0
    assert interval == "1d"


def test_normalise_ambiguous_and_day_first_dates():
    base = [[f"{(i % 28) + 1:02d}/03/2024", "10"] for i in range(28)] + [["01/04/2024", "10"], ["02/04/2024", "10"]]
    bars, _, warnings = mapped(base)
    assert bars[0][0] == 1_709_251_200.0 and not warnings
    ambiguous = [[f"{m:02d}/{d:02d}/2024", "10"] for m in (1, 2, 3) for d in range(1, 13)]
    _, _, warnings = mapped(ambiguous)
    assert any("month/day/year" in w for w in warnings)


def test_normalise_number_cleaning_and_drops():
    rows = [["2024-01-%02d" % (i + 1), f"${1000 + i:,}.50"] for i in range(30)]
    rows += [["garbage", "1"], ["2024-02-10", "n/a"], ["2024-02-11", "0"], ["2024-01-05", "999"]]
    bars, _, warnings = mapped(rows)
    assert len(bars) == 30 and bars[0][4] == 1000.5 and bars[3][4] == 1003.5
    assert any("3 rows were skipped" in w for w in warnings)
    rows = [["2024-01-%02d" % (i + 1), f"{5 + i}%"] for i in range(30)]
    assert mapped(rows)[0][0][4] == 5.0


def test_normalise_fixes_envelope_and_sorts():
    rows = [[f"2024-01-{i + 1:02d}", "10", "9", "11", "10.5", "100"] for i in range(30)][::-1]
    table = ParsedTable(["date", "open", "high", "low", "close", "volume"], rows)
    bars, _, _ = normalise(table, detect_columns(table))
    assert bars[0][0] < bars[-1][0]
    assert all(b[2] >= max(b[1], b[4]) and b[3] <= min(b[1], b[4]) for b in bars)
    assert bars[0][5] == 100.0


def test_normalise_interval_detection():
    for step, expected in ((60, "1m"), (3600, "1h"), (14400, "4h"), (86400, "1d"), (604800, "1w")):
        bars, interval, _ = mapped([[str(1_700_000_000 + i * step), "5"] for i in range(40)])
        assert interval == expected
    with pytest.raises(LabError) as err:
        mapped([[str(1_700_000_000 + i * 2_592_000), "5"] for i in range(40)])
    assert err.value.code == "bad_request"
    with pytest.raises(LabError):
        mapped([[str(1_700_000_000 + i * 86400), "5"] for i in range(10)])


def test_normalise_caps_stored_bars(monkeypatch):
    monkeypatch.setattr(datasets, "MAX_BARS_STORED", 40)
    bars, _, warnings = mapped([[str(1_700_000_000 + i * 3600), "5"] for i in range(60)])
    assert len(bars) == 40 and bars[-1][0] == 1_700_000_000 + 59 * 3600 and any("newest" in w for w in warnings)
    assert MAX_BARS_STORED == 100_000


def test_ai_mapping_with_faked_chat_json(monkeypatch):
    table = ParsedTable(["When", "Px", "Qty"], [["2024-01-01", "5", "2"]] * 3)
    auth = llm.AiAuth(provider="platform", model="gemini:x")
    seen = {}

    def fake(a, prompt, **kw):
        seen["model"] = a.model
        seen["prompt"] = prompt
        return {"t": "When", "close": "Px", "volume": "Qty", "open": None}

    monkeypatch.setattr(llm, "chat_json", fake)
    mapping = datasets.ai_map_columns(table, auth, "gemini:other")
    assert mapping == {"t": "When", "close": "Px", "volume": "Qty", "open": "Px", "high": "Px", "low": "Px"}
    assert seen["model"] == "gemini:other" and "When" in seen["prompt"]
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"t": "When", "close": "Nope"})
    with pytest.raises(LabError) as err:
        datasets.ai_map_columns(table, auth, None)
    assert err.value.status == 502 and err.value.code == "bad_output"
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"t": "When"})
    with pytest.raises(LabError) as err:
        datasets.ai_map_columns(table, auth, None)
    assert err.value.code == "bad_output"
    with pytest.raises(LabError) as err:
        datasets.ai_map_columns(table, None, None)
    assert err.value.code == "model_unavailable"


def test_store_get_list_delete_and_ownership():
    bars = make_bars(40, interval_s=86400)
    stored = datasets.store_dataset("s_owner", "My data", "inr", bars, "1d")
    assert stored["symbol"] == f"upload:{stored['id']}" and stored["quote"] == "INR"
    assert stored["bars"] == bars and stored["start"] == bars[0][0] and stored["end"] == bars[-1][0]
    assert len(stored["data_hash"]) == 64 and stored["id"].startswith("d_") and len(stored["id"]) == 12
    assert datasets.get_dataset(stored["id"], "s_owner")["data_hash"] == stored["data_hash"]
    with pytest.raises(LabError) as err:
        datasets.get_dataset(stored["id"], "s_other")
    assert err.value.status == 403
    with pytest.raises(LabError) as err:
        datasets.get_dataset("d_missing", "s_owner")
    assert err.value.status == 404
    listed = datasets.list_datasets("s_owner")
    assert len(listed) == 1 and listed[0]["bar_count"] == 40 and "bars" not in listed[0]
    assert datasets.list_datasets("s_other") == []
    with pytest.raises(LabError):
        datasets.delete_dataset(stored["id"], "s_other")
    datasets.delete_dataset(stored["id"], "s_owner")
    assert datasets.list_datasets("s_owner") == []


def test_store_validation_and_cap(monkeypatch):
    bars = make_bars(40, interval_s=86400)
    for name, quote in (("", "USD"), ("x", "US"), ("x", "TOOLONG"), ("x", "U$D")):
        with pytest.raises(LabError) as err:
            datasets.store_dataset("s_a", name, quote, bars, "1d")
        assert err.value.code == "bad_request"
    with pytest.raises(LabError):
        datasets.store_dataset("s_a", "x", "USD", bars[:5], "1d")
    assert datasets.store_dataset("s_a", "x", "", bars, "1d")["quote"] == "USD"
    monkeypatch.setenv("MAX_DATASETS_PER_ACCOUNT", "2")
    from parable.config import get_settings

    get_settings.cache_clear()
    datasets.store_dataset("s_a", "y", "USD", bars, "1d")
    with pytest.raises(LabError) as err:
        datasets.store_dataset("s_a", "z", "USD", bars, "1d")
    assert err.value.status == 409
    datasets.store_dataset("s_b", "z", "USD", bars, "1d")


def test_upload_provider_serves_candles_and_info():
    from parable.lab import markets

    bars = make_bars(40, interval_s=86400)
    stored = datasets.store_dataset("s_a", "Mine", "USD", bars, "1d")
    markets.reset_providers(offline=True)
    assert markets.candles(stored["symbol"], "1d", 100) == bars
    info = markets.symbol_info(stored["symbol"])
    assert info.kind == "mine" and not info.live and markets.source_kind(stored["symbol"]) == "creator"
    with pytest.raises(LabError):
        markets.candles(stored["symbol"], "1h", 100)
    with pytest.raises(LabError):
        markets.symbol_info("upload:d_nope")


def test_drafts_expire_and_are_owner_bound():
    table = ParsedTable(["a", "b"], [["1", "2"]])
    now = [1000.0]
    datasets.clock = lambda: now[0]
    try:
        draft = datasets.hold_draft("s_a", table)
        assert draft.startswith("dr_")
        assert datasets.take_draft(draft, "s_a") is table
        with pytest.raises(LabError) as err:
            datasets.take_draft(draft, "s_b")
        assert err.value.status == 403
        now[0] += 601
        with pytest.raises(LabError) as err:
            datasets.take_draft(draft, "s_a")
        assert err.value.status == 404
    finally:
        import time

        datasets.clock = time.time


def test_ingest_detected_and_needs_mapping():
    done = datasets.ingest("s_a", "px.csv", csv_bytes(40), "Px", "USD")
    assert done["status"] == "stored" and done["dataset"]["interval"] == "1d"
    odd = b"when,thing\n" + b"\n".join(f"{1_700_000_000 + i * 86400},{i + 1}".encode() for i in range(40))
    pending = datasets.ingest("s_a", "odd.csv", odd, "Odd", "USD")
    assert pending["status"] == "needs_mapping" and pending["columns"] == ["when", "thing"] and len(pending["preview"]) == 5
    table = datasets.take_draft(pending["draft_id"], "s_a")
    finished = datasets.finish_upload("s_a", table, {"t": "when", "close": "thing"}, "Odd", "USD")
    assert finished["dataset"]["bars"][0][4] == 1.0
