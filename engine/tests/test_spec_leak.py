import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "parable"
ALLOWED = {"db.py", "agents.py", "spec.py"}
PUBLIC_PATHS = ("/api/listings", "/api/stats", "/api/info", "/api/runs", "/api/ledger?limit=500")


def source_files_with_token(token: str) -> set[str]:
    return {path.name for path in PACKAGE.rglob("*.py") if token in path.read_text()}


def test_only_the_storage_layer_mentions_the_stored_spec_column():
    assert source_files_with_token("spec_json") <= ALLOWED


def test_the_scanner_catches_spec_text_and_passes_clean_json():
    spec = {"entry": "close > sma(close, 20)", "exit": "close < sma(close, 20)", "params": {"fast_len": {"value": 1}}}
    assert leaks(json.dumps({"a": 1}), spec, "steps") == []
    assert leaks(json.dumps({"a": "close > sma(close, 20)"}), spec, "steps") == [spec["entry"]]
    assert leaks('{"fast_len": {"value": 5}}', spec, "steps") == ["param fast_len"]
    assert leaks("my steps here", spec, "steps") == ["steps"]


def leaks(text: str, spec: dict, steps_text: str) -> list[str]:
    hits = [secret for secret in (spec["entry"], spec.get("exit"), steps_text) if secret and secret in text]
    for name in spec.get("params", {}):
        if len(name) > 4 and f'"{name}":' in text and '"value"' in text:
            hits.append(f"param {name}")
    return hits


def public_dump(client, extra_paths=()) -> str:
    pieces = []
    for path in (*PUBLIC_PATHS, *extra_paths):
        response = client.get(path)
        assert response.status_code == 200, path
        pieces.append(response.text)
    return "\n".join(pieces)
