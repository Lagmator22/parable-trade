from parable.config import get_settings
from parable.db import DB_LOCK, execute, one, rows

TRIM_FRACTION = 10


def insert_point(run_id: int, t: int, equity: int, price: int | None) -> None:
    cap = get_settings().max_run_points_per_run
    with DB_LOCK:
        count = one("SELECT COUNT(*) AS n FROM run_points WHERE run_id = ?", (run_id,))["n"]
        if count >= cap:
            drop = max(1, cap // TRIM_FRACTION)
            execute("DELETE FROM run_points WHERE id IN (SELECT id FROM run_points WHERE run_id = ?"
                    " ORDER BY t, id LIMIT ?)", (run_id, drop))
        execute("INSERT INTO run_points (run_id, t, equity, price) VALUES (?,?,?,?)",
                (run_id, t, equity, price))


def sample(found: list, limit: int) -> list:
    if limit < 1:
        return []
    if len(found) <= limit:
        return found
    if limit == 1:
        return [found[-1]]
    step = (len(found) - 1) / (limit - 1)
    return [found[round(i * step)] for i in range(limit)]


def points(run_id: int, since: int = 0, limit: int = 2000) -> list[list[int]]:
    found = rows("SELECT t, equity, price FROM run_points WHERE run_id = ? AND t >= ? ORDER BY t, id",
                 (run_id, since))
    return sample([[r["t"], r["equity"], r["price"]] for r in found], limit)


def last_price(run_id: int) -> int | None:
    found = one("SELECT price FROM run_points WHERE run_id = ? AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                (run_id,))
    return found["price"] if found else None
