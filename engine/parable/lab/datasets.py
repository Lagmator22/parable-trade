import json
import math
import re
import secrets
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from parable import db
from parable.config import get_settings
from parable.errors import LabError
from parable.lab.consts import INTERVAL_SECONDS, MAX_BARS_STORED, MIN_BARS
from parable.lab.tables import ParsedTable, parse_upload

Mapping = dict[str, str]
Bar = list[float]
TIME_NAMES = ("datetime", "timestamp", "date", "time", "t", "day", "period")
OPEN_NAMES, HIGH_NAMES, LOW_NAMES = ("open", "o"), ("high", "h"), ("low", "l")
CLOSE_NAMES = ("close", "c", "adj close", "adj_close", "price", "last", "nav", "value")
VOLUME_NAMES = ("volume", "vol", "v", "qty")
DRAFT_TTL_S = 600
MAX_DRAFTS = 200
INTERVAL_TOLERANCE = 0.25
DATE_PARTS = re.compile(r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
EXTRA_FORMATS = ("%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y", "%Y%m%d")

_drafts: dict[str, dict] = {}
_drafts_lock = threading.Lock()
clock: Callable[[], float] = time.time


def detect_columns(table: ParsedTable) -> Mapping | None:
    names = {c.strip().lower(): c for c in table.columns}

    def pick(options: tuple[str, ...]) -> str | None:
        return next((names[o] for o in options if o in names), None)

    t, close = pick(TIME_NAMES), pick(CLOSE_NAMES)
    if t is None or close is None:
        return None
    found = {"t": t, "close": close}
    for key, options in (("open", OPEN_NAMES), ("high", HIGH_NAMES), ("low", LOW_NAMES)):
        found[key] = pick(options) or close
    volume = pick(VOLUME_NAMES)
    if volume:
        found["volume"] = volume
    return found


def ai_map_columns(table: ParsedTable, auth, model: str | None = None) -> Mapping:
    from parable.lab import llm

    if auth is None:
        raise LabError(503, "model_unavailable", "no AI model is available to map the columns")
    use = auth.model_copy(update={"model": model}) if model else auth
    prompt = ("Map the columns of this table of market prices. Reply with JSON using these keys: t (time or date), "
              "open, high, low, close (the price column if only one exists), volume (optional). Values must be exact "
              "column names from the header or null.\n"
              + json.dumps({"header": table.columns, "rows": table.rows[:5]}))
    answer = llm.chat_json(use, prompt)
    mapping: Mapping = {}
    for key in ("t", "open", "high", "low", "close", "volume"):
        value = answer.get(key) if isinstance(answer, dict) else None
        if value is None:
            continue
        if value not in table.columns:
            raise LabError(502, "bad_output", "the model named a column that does not exist")
        mapping[key] = value
    if "t" not in mapping or "close" not in mapping:
        raise LabError(502, "bad_output", "the model could not find the time and price columns")
    for key in ("open", "high", "low"):
        mapping.setdefault(key, mapping["close"])
    return mapping


def parse_number(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.eE+\-]", "", str(text).replace(",", ""))
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def epoch_of(text: str) -> float | None:
    raw = str(text).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = None
    if value is not None:
        if not math.isfinite(value):
            return None
        if value > 1e11:
            return value / 1000.0
        if value >= 1e8:
            return value
        if 10_000 <= value < 100_000:
            return (datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=value)).timestamp()
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        pass
    for fmt in EXTRA_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def slash_dates(values: list[str]) -> tuple[Callable[[str], float | None], str | None]:
    parts = [DATE_PARTS.match(v.strip()) for v in values]
    parts = [p for p in parts if p and len(p.group(3)) == 4]
    day_first = any(int(p.group(1)) > 12 for p in parts)
    month_first = any(int(p.group(2)) > 12 for p in parts)
    warning = "dates were ambiguous, read as month/day/year" if parts and not day_first and not month_first else None

    def convert(text: str) -> float | None:
        m = DATE_PARTS.match(text.strip())
        if not m or len(m.group(3)) != 4:
            return epoch_of(text)
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (a, b) if day_first and not month_first else (b, a)
        try:
            return datetime(year, month, day, int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
                            tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    return convert, warning


def pick_interval(times: list[float]) -> str:
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not deltas:
        raise LabError(400, "bad_request", "could not work out the bar interval")
    median = statistics.median(deltas)
    name = min(INTERVAL_SECONDS, key=lambda k: abs(INTERVAL_SECONDS[k] - median))
    if abs(INTERVAL_SECONDS[name] - median) / INTERVAL_SECONDS[name] > INTERVAL_TOLERANCE:
        raise LabError(400, "bad_request", "the spacing between rows does not match a supported interval")
    return name


def normalise(table: ParsedTable, mapping: Mapping) -> tuple[list[Bar], str, list[str]]:
    index = {c: i for i, c in enumerate(table.columns)}
    for key in ("t", "close"):
        if mapping.get(key) not in index:
            raise LabError(400, "bad_request", f"the {key} column is missing")
    pos = {k: index[mapping.get(k, mapping["close"])] for k in ("t", "open", "high", "low", "close")}
    vol = index.get(mapping.get("volume", ""))
    warnings: list[str] = []
    to_time, note = slash_dates([r[pos["t"]] for r in table.rows[:2000]])
    if note:
        warnings.append(note)
    parsed: dict[float, Bar] = {}
    dropped = 0
    for row in table.rows:
        t = to_time(row[pos["t"]])
        prices = [parse_number(row[pos[k]]) for k in ("open", "high", "low", "close")]
        if t is None or None in prices or min(prices) <= 0:
            dropped += 1
            continue
        o, h, low, c = prices
        volume = parse_number(row[vol]) if vol is not None else 0.0
        parsed.setdefault(t, [t, o, max(o, h, low, c), min(o, h, low, c), c, volume if volume and volume > 0 else 0.0])
    if dropped:
        warnings.append(f"{dropped} rows were skipped because the time or price could not be read")
    bars = [parsed[t] for t in sorted(parsed)]
    if len(bars) < MIN_BARS:
        raise LabError(400, "bad_request", f"need at least {MIN_BARS} usable rows, found {len(bars)}")
    if len(bars) > MAX_BARS_STORED:
        warnings.append(f"only the newest {MAX_BARS_STORED} bars were kept")
        bars = bars[-MAX_BARS_STORED:]
    return bars, pick_interval([b[0] for b in bars]), warnings


def view(row: dict, with_bars: bool) -> dict:
    out = {"id": row["id"], "symbol": f"upload:{row['id']}", "name": row["name"], "interval": row["interval"],
           "quote": row["quote"], "start": row["start_t"], "end": row["end_t"], "data_hash": row["data_hash"],
           "created_at": row["created_at"]}
    if with_bars:
        out["bars"] = json.loads(row["bars_json"])
    else:
        out["bar_count"] = row["bars"]
    return out


def store_dataset(owner_id: str, name: str, quote: str, bars: list[Bar], interval: str) -> dict:
    from parable.lab.backtest import data_hash

    name = (name or "").strip()[:60]
    if not name:
        raise LabError(400, "bad_request", "give the dataset a name")
    quote = (quote or "USD").strip().upper()
    if not re.fullmatch(r"[A-Z]{3,5}", quote):
        raise LabError(400, "bad_request", "quote must be 3 to 5 letters, like USD")
    if interval not in INTERVAL_SECONDS or len(bars) < MIN_BARS:
        raise LabError(400, "bad_request", "not enough bars to store")
    with db.DB_LOCK:
        count = db.one("SELECT COUNT(*) AS n FROM datasets WHERE owner_id = ?", (owner_id,))["n"]
        if count >= get_settings().max_datasets_per_account:
            raise LabError(409, "conflict", "dataset limit reached, delete one first")
        dataset_id = "d_" + secrets.token_hex(5)
        db.execute(
            "INSERT INTO datasets (id, owner_id, name, interval, quote, bars, start_t, end_t, data_hash, bars_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dataset_id, owner_id, name, interval, quote, len(bars), bars[0][0], bars[-1][0], data_hash(bars),
             json.dumps(bars, separators=(",", ":")), int(time.time())))
    return get_dataset(dataset_id, owner_id)


def get_dataset(dataset_id: str, owner_id: str) -> dict:
    row = db.one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
    if row is None:
        raise LabError(404, "not_found", "no such dataset")
    if row["owner_id"] != owner_id:
        raise LabError(403, "forbidden", "that dataset belongs to someone else")
    return view(row, True)


def raw_dataset(dataset_id: str) -> dict | None:
    row = db.one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
    return view(row, True) if row else None


def list_datasets(owner_id: str) -> list[dict]:
    return [view(r, False) for r in db.rows("SELECT * FROM datasets WHERE owner_id = ? ORDER BY created_at DESC, id", (owner_id,))]


def delete_dataset(dataset_id: str, owner_id: str) -> None:
    get_dataset(dataset_id, owner_id)
    db.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))


def hold_draft(owner_id: str, table: ParsedTable) -> str:
    draft_id = "dr_" + secrets.token_hex(5)
    with _drafts_lock:
        for key in [k for k, d in _drafts.items() if d["expires"] < clock()]:
            del _drafts[key]
        while len(_drafts) >= MAX_DRAFTS:
            del _drafts[next(iter(_drafts))]
        _drafts[draft_id] = {"owner": owner_id, "table": table, "expires": clock() + DRAFT_TTL_S}
    return draft_id


def take_draft(draft_id: str, owner_id: str) -> ParsedTable:
    with _drafts_lock:
        draft = _drafts.get(draft_id)
        if draft is None or draft["expires"] < clock():
            _drafts.pop(draft_id, None)
            raise LabError(404, "not_found", "that upload expired, upload it again")
        if draft["owner"] != owner_id:
            raise LabError(403, "forbidden", "that upload belongs to someone else")
        return draft["table"]


def finish_upload(owner_id: str, table: ParsedTable, mapping: Mapping, name: str, quote: str) -> dict:
    bars, interval, warnings = normalise(table, mapping)
    return {"status": "stored", "dataset": store_dataset(owner_id, name, quote, bars, interval), "warnings": warnings}


def ingest(owner_id: str, filename: str, content: bytes, name: str, quote: str, auth=None) -> dict:
    table = parse_upload(filename, content)
    mapping = detect_columns(table)
    if mapping is None and auth is not None:
        try:
            mapping = ai_map_columns(table, auth)
        except LabError:
            mapping = None
    if mapping is None:
        return {"status": "needs_mapping", "draft_id": hold_draft(owner_id, table), "columns": table.columns,
                "preview": table.rows[:5]}
    return finish_upload(owner_id, table, mapping, name, quote)


def clear_drafts() -> None:
    with _drafts_lock:
        _drafts.clear()
