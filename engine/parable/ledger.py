import copy
import hashlib
import json
import time

from parable.db import DB_LOCK, execute, one, rows

GENESIS = "0" * 64


def encode_data(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def entry_hash(seq: int, at: int, kind: str, subject: str, data_json: str, prev_hash: str) -> str:
    return hashlib.sha256(f"{seq}|{at}|{kind}|{subject}|{data_json}|{prev_hash}".encode()).hexdigest()


def public_row(row: dict) -> dict:
    return {
        "seq": row["seq"],
        "at": row["at"],
        "kind": row["kind"],
        "subject": row["subject"],
        "data": json.loads(row["data_json"]),
        "prev_hash": row["prev_hash"],
        "hash": row["hash"],
    }


def append(kind: str, subject: str, data: dict) -> dict:
    data_json = encode_data(data)
    with DB_LOCK:
        last = one("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1")
        seq = last["seq"] + 1 if last else 1
        prev_hash = last["hash"] if last else GENESIS
        at = int(time.time())
        digest = entry_hash(seq, at, kind, subject, data_json, prev_hash)
        execute(
            "INSERT INTO ledger (seq, at, kind, subject, data_json, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
            (seq, at, kind, subject, data_json, prev_hash, digest),
        )
    return public_row({"seq": seq, "at": at, "kind": kind, "subject": subject, "data_json": data_json,
                       "prev_hash": prev_hash, "hash": digest})


def entries(subject: str | None = None, kind: str | None = None, limit: int = 100,
            before_seq: int | None = None) -> list[dict]:
    clauses, params = [], []
    for column, value in (("subject", subject), ("kind", kind)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if before_seq is not None:
        clauses.append("seq < ?")
        params.append(before_seq)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(f"SELECT * FROM ledger {where} ORDER BY seq DESC LIMIT ?", (*params, limit))
    return [public_row(row) for row in found]


def head() -> dict:
    last = one("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1")
    return {"seq": last["seq"], "hash": last["hash"]} if last else {"seq": 0, "hash": GENESIS}


def raw_rows() -> list[dict]:
    return rows("SELECT * FROM ledger ORDER BY seq ASC")


def stored_data_json(row: dict) -> str:
    return row["data_json"] if "data_json" in row else encode_data(row["data"])


def row_is_valid(row: dict, expected_seq: int, expected_prev: str) -> bool:
    if row["seq"] != expected_seq or row["prev_hash"] != expected_prev:
        return False
    digest = entry_hash(row["seq"], row["at"], row["kind"], row["subject"], stored_data_json(row),
                        row["prev_hash"])
    return digest == row["hash"]


def verify(rows_to_check: list[dict] | None = None) -> dict:
    chain = raw_rows() if rows_to_check is None else rows_to_check
    expected_prev = GENESIS
    for index, row in enumerate(chain, start=1):
        if not row_is_valid(row, index, expected_prev):
            return {"ok": False, "checked": index, "first_bad_seq": row["seq"],
                    "head": chain[-1]["hash"]}
        expected_prev = row["hash"]
    return {"ok": True, "checked": len(chain), "first_bad_seq": None, "head": expected_prev}


def pick_tamper_target(chain: list[dict]) -> dict | None:
    ended = [r for r in chain if r["kind"] == "run.ended"]
    losers = [r for r in ended if json.loads(r["data_json"]).get("cause") == "loss_limit"]
    pool = losers or ended or chain
    return pool[-1] if pool else None


def rewrite_history(data: dict) -> dict:
    forged = copy.deepcopy(data)
    if forged.get("cause") == "loss_limit":
        forged["cause"] = "expired"
    elif "final_equity_usd" in forged:
        forged["final_equity_usd"] = forged["final_equity_usd"] * 3 // 2 + 1_000_000
    else:
        forged["tampered"] = True
    return forged


def tamper_demo() -> dict:
    chain = copy.deepcopy(raw_rows())
    target = pick_tamper_target(chain)
    if target is None:
        return {"edited_seq": None, "before": None, "after": None, "verify": verify(chain)}
    before = json.loads(target["data_json"])
    after = rewrite_history(before)
    target["data_json"] = encode_data(after)
    return {"edited_seq": target["seq"], "kind": target["kind"], "before": before, "after": after,
            "verify": verify(chain)}
