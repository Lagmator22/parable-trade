import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from parable.config import get_settings
from parable.errors import LabError

MAX_ZIP_ENTRIES = 200
MAX_ZIP_BYTES = 50_000_000
TEXT_EXTS = (".csv", ".tsv", ".txt")
KNOWN_EXTS = TEXT_EXTS + (".json", ".xlsx", ".docx")
DELIMITERS = (",", ";", "\t", "|")
NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class ParsedTable:
    columns: list[str]
    rows: list[list[str]]


def bad(detail: str) -> LabError:
    return LabError(400, "bad_request", detail)


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def finish(columns: list[str], rows: list[list[str]]) -> ParsedTable:
    if not columns or not rows:
        raise bad("that file has no table with data in it")
    if len(rows) > get_settings().upload_max_rows:
        raise LabError(413, "too_large", f"too many rows (limit {get_settings().upload_max_rows})")
    width = len(columns)
    return ParsedTable([c.strip() for c in columns], [(r + [""] * width)[:width] for r in rows])


def decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16") if content[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise bad("could not read that file as text")


def parse_delimited(text: str) -> ParsedTable:
    lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    if not lines:
        raise bad("that file is empty")
    delimiter = max(DELIMITERS, key=lambda d: (sum(1 for ln in lines if d in ln), lines[0].count(d)))
    parsed = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(x.strip() for x in row)]
    return finish(parsed[0], parsed[1:])


def parse_json(text: str) -> ParsedTable:
    try:
        data = json.loads(text)
    except ValueError:
        raise bad("that file is not valid JSON") from None
    if isinstance(data, dict):
        data = next((data[k] for k in ("data", "rows", "candles") if isinstance(data.get(k), list)), None)
    if not isinstance(data, list) or not data:
        raise bad("expected a JSON array of rows")
    if all(isinstance(r, dict) for r in data):
        columns: list[str] = []
        for record in data:
            columns += [k for k in record if k not in columns]
        return finish(columns, [[cell_text(r.get(c)) for c in columns] for r in data])
    if all(isinstance(r, list) for r in data) and len(data) > 1:
        return finish([cell_text(c) for c in data[0]], [[cell_text(c) for c in r] for r in data[1:]])
    raise bad("JSON rows must be objects or arrays with a header row")


def open_zip(content: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise bad("that file is not a valid spreadsheet or document") from None
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
        raise LabError(413, "too_large", "that archive is too large to open safely")
    return archive


def read_xml(archive: zipfile.ZipFile, name: str):
    try:
        raw = archive.read(name)
    except KeyError:
        return None
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise bad("that file contains unsupported XML")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise bad("that file contains unreadable XML") from None


def column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    index = 0
    for ch in letters.group(0) if letters else "A":
        index = index * 26 + ord(ch) - 64
    return index - 1


def sheet_rows(archive: zipfile.ZipFile, sheet: str, shared: list[str]) -> list[list[str]]:
    root = read_xml(archive, sheet)
    out = []
    for row in root.iter(f"{NS_MAIN}row") if root is not None else []:
        cells: dict[int, str] = {}
        for cell in row.findall(f"{NS_MAIN}c"):
            kind, value = cell.get("t"), cell.find(f"{NS_MAIN}v")
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{NS_MAIN}t"))
            elif value is None or value.text is None:
                text = ""
            elif kind == "s" and value.text.isdigit() and int(value.text) < len(shared):
                text = shared[int(value.text)]
            else:
                text = value.text
            cells[column_index(cell.get("r", ""))] = text.strip()
        if cells:
            out.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return out


def parse_xlsx(archive: zipfile.ZipFile) -> ParsedTable:
    strings = read_xml(archive, "xl/sharedStrings.xml")
    shared = ["".join(t.text or "" for t in si.iter(f"{NS_MAIN}t")) for si in strings] if strings is not None else []
    sheets = sorted((n for n in archive.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[-1]))
    for sheet in sheets:
        rows = sheet_rows(archive, sheet, shared)
        if len(rows) > get_settings().upload_max_rows + 1:
            raise LabError(413, "too_large", "too many rows")
        if len(rows) >= 2:
            return finish(rows[0], rows[1:])
    raise bad("that workbook has no sheet with data")


def parse_docx(archive: zipfile.ZipFile) -> ParsedTable:
    root = read_xml(archive, "word/document.xml")
    table = next(root.iter(f"{NS_WORD}tbl"), None) if root is not None else None
    if table is None:
        raise bad("that document has no table")
    rows = [["".join(t.text or "" for t in cell.iter(f"{NS_WORD}t")).strip() for cell in tr.findall(f"{NS_WORD}tc")]
            for tr in table.findall(f"{NS_WORD}tr")]
    return finish(rows[0], rows[1:]) if len(rows) >= 2 else finish([], [])


def parse_upload(filename: str, content: bytes) -> ParsedTable:
    if len(content) > get_settings().upload_max_bytes:
        raise LabError(413, "too_large", f"file too large (limit {get_settings().upload_max_bytes} bytes)")
    name = (filename or "").lower()
    if not name.endswith(KNOWN_EXTS):
        raise bad("upload a .csv, .tsv, .txt, .json, .xlsx or .docx file")
    if content[:4] == b"%PDF":
        raise bad("PDF files are not supported, export the table as CSV")
    if content[:4] == b"PK\x03\x04":
        archive = open_zip(content)
        names = archive.namelist()
        if "xl/workbook.xml" in names:
            return parse_xlsx(archive)
        if "word/document.xml" in names:
            return parse_docx(archive)
        raise bad("that archive is not a spreadsheet or document")
    if name.endswith((".xlsx", ".docx")):
        raise bad("that file is not a valid spreadsheet or document")
    if b"\x00" in content[:2048] and content[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise bad("that file does not look like text")
    text = decode(content)
    if name.endswith(".json") or text.lstrip()[:1] in ("{", "["):
        return parse_json(text)
    return parse_delimited(text)
