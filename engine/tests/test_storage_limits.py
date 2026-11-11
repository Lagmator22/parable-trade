import io
import zipfile

import pytest

from agents_support import make_account, make_client
from market_support import make_listing, make_seller
from parable import guard, proofs
from parable.db import execute, one, rows
from parable.errors import LabError
from parable.lab import tables


def test_reruns_and_test_drives_store_no_bars(manager):
    listing = make_listing()
    before = one("SELECT COUNT(*) AS n FROM bar_sets")["n"]
    checker = make_seller("Checker", "checker@example.com")
    proofs.rerun_listing(listing["id"], checker["id"])
    proofs.test_drive(listing["id"], checker["id"], symbol="fake:ETHUSDT")
    assert one("SELECT COUNT(*) AS n FROM bar_sets")["n"] == before


def test_old_plain_backtests_are_pruned_but_headlines_survive(manager, monkeypatch):
    monkeypatch.setattr(proofs, "KEEP_BACKTESTS_PER_VERSION", 3)
    seller = make_seller()
    listing = make_listing(seller)
    version_id = listing["version_id"]
    from parable.lab import markets
    from parable.lab.backtest import run_backtest
    from parable.lab.spec import load_spec

    spec = load_spec(version_id)
    execute("UPDATE proofs SET created_at = 1 WHERE id = ?", (listing["proof_id"],))
    for limit in range(100, 110):
        bars = markets.candles("fake:BTCUSDT", "1h", limit)
        result = run_backtest(spec, bars, symbol="fake:BTCUSDT", interval="1h", quote="USDT", source_kind="market")
        proofs.store_proof("backtest", version_id, spec, result, bars=bars)
        proofs.prune_backtests(version_id)
    kept = rows("SELECT id FROM proofs WHERE version_id = ? AND kind = 'backtest'", (version_id,))
    assert listing["proof_id"] in {row["id"] for row in kept} and len(kept) == 4
    assert one("SELECT COUNT(*) AS n FROM bar_sets")["n"] <= 4


def test_daily_cap_on_checks_is_per_requester(manager, monkeypatch):
    monkeypatch.setattr(proofs, "MAX_CHECKS_PER_LISTING_PER_DAY", 2)
    listing = make_listing()
    greedy = make_seller("C0", "c0@example.com")["id"]
    for _ in range(2):
        proofs.rerun_listing(listing["id"], greedy)
    with pytest.raises(LabError) as capped:
        proofs.rerun_listing(listing["id"], greedy)
    assert capped.value.status == 429


def test_anonymous_and_seller_checks_never_block_a_buyer(manager, monkeypatch):
    monkeypatch.setattr(proofs, "MAX_CHECKS_PER_LISTING_PER_DAY", 2)
    monkeypatch.setattr(proofs, "MAX_ANONYMOUS_CHECKS_PER_LISTING_PER_DAY", 2)
    listing = make_listing()
    for requester in ("v_visitor0000000a", listing["seller_id"]):
        for _ in range(2):
            proofs.rerun_listing(listing["id"], requester)
        with pytest.raises(LabError):
            proofs.rerun_listing(listing["id"], requester)
    buyer = make_seller("Buyer", "buyer@example.com")["id"]
    assert proofs.rerun_listing(listing["id"], buyer)["match"] is True


def test_rotating_visitor_ids_hit_the_shared_anonymous_cap(manager, monkeypatch):
    monkeypatch.setattr(proofs, "MAX_ANONYMOUS_CHECKS_PER_LISTING_PER_DAY", 3)
    listing = make_listing()
    for i in range(3):
        proofs.rerun_listing(listing["id"], f"v_visitor{i:09d}")
    with pytest.raises(LabError) as capped:
        proofs.rerun_listing(listing["id"], "v_visitor999999999")
    assert capped.value.status == 429


def test_signed_in_buyer_passes_after_anonymous_cap_is_used_up(manager, monkeypatch):
    monkeypatch.setattr(proofs, "MAX_ANONYMOUS_CHECKS_PER_LISTING_PER_DAY", 2)
    listing = make_listing()
    for i in range(2):
        proofs.rerun_listing(listing["id"], f"v_visitor{i:09d}")
    with pytest.raises(LabError):
        proofs.rerun_listing(listing["id"], "v_visitor888888888")
    buyer = make_seller("Buyer2", "buyer2@example.com")["id"]
    assert proofs.rerun_listing(listing["id"], buyer)["match"] is True


def test_listings_per_account_are_capped(manager, monkeypatch):
    monkeypatch.setenv("MAX_LISTINGS_PER_ACCOUNT", "2")
    from parable.config import get_settings

    get_settings.cache_clear()
    seller = make_seller()
    make_listing(seller, title="First one")
    make_listing(seller, title="Second one")
    with pytest.raises(LabError) as capped:
        make_listing(seller, title="Third one")
    assert capped.value.status == 429


def make_xlsx(sheet: bytes, extra: dict | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return out.getvalue()


HEAD = b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'


def test_zip_bomb_entry_is_refused_before_parsing():
    bomb = make_xlsx(HEAD + b'<row><c r="A1"><v>1</v></c></row>' * 300_000 + b"</sheetData></worksheet>")
    with pytest.raises(LabError) as refused:
        tables.parse_upload("bomb.xlsx", bomb)
    assert refused.value.status == 413


def test_row_cap_stops_xlsx_parsing(monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_ROWS", "5")
    from parable.config import get_settings

    get_settings.cache_clear()
    rows_xml = b"".join(f'<row><c r="A1"><v>{n}</v></c><c r="B1"><v>{n}</v></c></row>'.encode() for n in range(100))
    with pytest.raises(LabError) as refused:
        tables.parse_upload("rows.xlsx", make_xlsx(HEAD + rows_xml + b"</sheetData></worksheet>"))
    assert refused.value.status == 413


def test_utf16_xml_is_refused():
    sheet = ('<?xml version="1.0" encoding="UTF-16"?><worksheet/>').encode("utf-16")
    with pytest.raises(LabError):
        tables.parse_upload("u.xlsx", make_xlsx(sheet))


def test_huge_csv_field_is_a_clean_400():
    content = b"time,close\n1," + b"9" * 200_000 + b"\n"
    with pytest.raises(LabError) as refused:
        tables.parse_upload("big.csv", content)
    assert refused.value.status == 400


def test_uploads_are_rate_limited(client, monkeypatch):
    from parable.routes_lab import UPLOADS_PER_HOUR

    account = make_account("Uploader")
    session = make_client(account)
    codes = {session.post("/api/datasets", files={"file": ("a.txt", b"nope")}).status_code
             for _ in range(UPLOADS_PER_HOUR + 2)}
    assert 429 in codes


def test_one_ip_cannot_drain_the_anonymous_pool(manager):
    listing = make_listing()
    token = guard.client_ip.set("203.0.113.7")
    try:
        for i in range(20):
            proofs.rerun_listing(listing["id"], f"v_visitor{i:09d}")
        with pytest.raises(LabError) as capped:
            proofs.rerun_listing(listing["id"], "v_visitor777777777")
        assert capped.value.status == 429 and capped.value.code == "rate_limited"
        assert "retry_after" in capped.value.extra
        buyer = make_seller("Buyer3", "buyer3@example.com")["id"]
        assert proofs.rerun_listing(listing["id"], buyer)["match"] is True
    finally:
        guard.client_ip.reset(token)
    other = guard.client_ip.set("198.51.100.9")
    try:
        assert proofs.rerun_listing(listing["id"], "v_visitor555555555")["match"] is True
    finally:
        guard.client_ip.reset(other)
