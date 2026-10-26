"""Bounded, lossless tabular import and constrained Google Sheets retrieval.

Original files are retained by the API, while this module emits JSON-safe tables.
Headers and worksheet/table choices are reversible until an import is finalized.
All row/header offsets are zero-based. No formulas or macros are executed.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePath
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100_000
MAX_TOTAL_ROWS = 250_000
MAX_COLUMNS = 500
MAX_TABLES = 100
MAX_CELL_CHARS = 100_000
MAX_PDF_PAGES = 200
MAX_JSON_DEPTH = 32
SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt", ".json", ".xlsx", ".xls", ".pdf"}


def _offset(options: dict, name: str, default: int | None = None) -> int | None:
    value = options.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_ROWS:
        raise ValueError(f"{name.replace('_', ' ').capitalize()} must be a nonnegative whole number.")
    return value


def _scalar(value):
    """Retain values without non-JSON NaN, Infinity or executable structures."""
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.replace("\x00", "")
        if len(value) > MAX_CELL_CHARS:
            raise ValueError(f"A cell exceeds the {MAX_CELL_CHARS:,}-character limit. Split oversized content before importing.")
        return value if value.strip() else None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _blank(row) -> bool:
    return all(value is None or (isinstance(value, str) and not value.strip()) for value in row)


def _headers(values: list, width: int) -> tuple[list[str], bool]:
    headers, counts = [], {}
    changed = False
    for i in range(width):
        raw = values[i] if i < len(values) else None
        base = str(raw).strip() if raw is not None else ""
        if not base:
            base = f"Column {i + 1}"
            changed = True
        if len(base) > 200:
            raise ValueError("A column name exceeds 200 characters. Choose a different header row or shorten the source header.")
        candidate = base
        counter = counts.get(base, 0) + 1
        while candidate in headers:
            candidate = f"{base} ({counter})"
            counter += 1
            changed = True
        counts[base] = counter
        headers.append(candidate)
    return headers, changed


def _header_index(matrix: list[list]) -> int:
    """Find a dense, mostly textual header after optional report title rows."""
    if not matrix:
        return 0
    sample = matrix[:30]
    widths = [sum(value is not None and str(value).strip() != "" for value in row) for row in sample]
    max_width = max(widths, default=0)
    for index, row in enumerate(sample):
        nonempty = [value for value in row if value is not None and str(value).strip()]
        if not nonempty:
            continue
        if len(nonempty) < max(1, max_width * 0.6):
            continue
        texts = sum(isinstance(v, str) and not re.fullmatch(r"[\d\s.,%$€£()+-]+", v.strip()) for v in nonempty)
        if texts / len(nonempty) >= 0.5 and len({str(v).strip() for v in nonempty}) >= len(nonempty) * 0.5:
            return index
    return next((index for index, row in enumerate(sample) if not _blank(row)), 0)


def _matrix_table(key: str, name: str, matrix: list[list], options: dict, warnings: list[str]) -> dict | None:
    skip_rows = _offset(options, "skip_rows", 0)
    header_row = _offset(options, "header_row")
    if skip_rows:
        matrix = matrix[skip_rows:]
    while matrix and _blank(matrix[-1]):
        matrix.pop()
    if not matrix or all(_blank(row) for row in matrix):
        return None
    header_row = _header_index(matrix) if header_row is None else header_row
    if header_row >= len(matrix):
        raise ValueError(f"The header row is outside table '{name}'. Choose a smaller header row or skip count.")
    data = matrix[header_row + 1:]
    if not data:
        return None
    width = max(len(matrix[header_row]), *(len(row) for row in data))
    if width > MAX_COLUMNS:
        raise ValueError(f"Table '{name}' has more than {MAX_COLUMNS} columns. Select a narrower table.")
    # Trailing wholly blank spreadsheet columns should not create phantom fields.
    while width and all(len(row) < width or row[width - 1] is None or str(row[width - 1]).strip() == "" for row in matrix[header_row:]):
        width -= 1
    if not width:
        return None
    columns, changed = _headers(matrix[header_row], width)
    if changed:
        warnings.append(f"{name}: blank or repeated headers were assigned unique names; all columns were retained.")
    if header_row:
        warnings.append(f"{name}: detected header at row {header_row + skip_rows + 1}; preceding report rows were excluded. You can override the header row.")
    rows = []
    for row in data:
        if _blank(row):
            continue
        rows.append({column: _scalar(row[i]) if i < len(row) else None for i, column in enumerate(columns)})
        if len(rows) > MAX_ROWS:
            raise ValueError(f"Table '{name}' exceeds {MAX_ROWS:,} records. Split the source into smaller files.")
    if not rows:
        return None
    return {"key": key, "name": name, "columns": columns, "rows": rows, "header_row": header_row + skip_rows}


def _decode_csv(content: bytes, options: dict, warnings: list[str]) -> str:
    encoding = options.get("encoding")
    if encoding is not None and encoding not in {"utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin-1"}:
        raise ValueError("Unsupported text encoding. Use UTF-8, UTF-16, Windows-1252 or Latin-1.")
    if not encoding:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        elif content.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"
        elif b"\x00" in content[:1000]:
            encoding = "utf-16-le" if content[:1000:2].count(0) < content[1:1000:2].count(0) else "utf-16-be"
        else:
            encoding = "utf-8"
    try:
        return content.decode(encoding)
    except UnicodeDecodeError:
        if options.get("encoding"):
            raise ValueError(f"The file cannot be decoded as {encoding}. Choose its correct encoding.") from None
        try:
            text = content.decode("cp1252")
        except UnicodeDecodeError:
            raise ValueError("The CSV encoding could not be detected. Re-save it as UTF-8, or choose its encoding.") from None
        warnings.append("Windows-1252 encoding was detected. Review accented characters in the preview.")
        return text


def _csv_tables(filename: str, content: bytes, options: dict, warnings: list[str]) -> list[dict]:
    text = _decode_csv(content, options, warnings)
    delimiter = options.get("delimiter")
    if delimiter is not None and delimiter not in {",", ";", "\t", "|"}:
        raise ValueError("The CSV delimiter must be a comma, semicolon, tab or vertical bar.")
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(text[:16000], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = "\t" if PurePath(filename).suffix.lower() == ".tsv" else ","
            warnings.append("The delimiter was uncertain; comma/tab detection was used. Set a delimiter if the preview is not correct.")
    previous_field_limit = csv.field_size_limit(MAX_CELL_CHARS)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        matrix = []
        for row in reader:
            if len(matrix) >= MAX_ROWS + 100:
                raise ValueError(f"The CSV exceeds {MAX_ROWS:,} records. Split the file before importing.")
            if len(row) > MAX_COLUMNS:
                raise ValueError(f"The CSV exceeds {MAX_COLUMNS} columns. Check the delimiter or split the source.")
            matrix.append(row)
    except csv.Error as exc:
        raise ValueError(f"The CSV contains malformed quoting or an oversized cell near line {reader.line_num}. Repair the row and try again.") from exc
    finally:
        csv.field_size_limit(previous_field_limit)
    lengths = {len(row) for row in matrix if not _blank(row)}
    if len(lengths) > 1:
        warnings.append("Inconsistent CSV row widths were detected. Missing values are blank; additional columns have been retained.")
    table = _matrix_table("table-0", PurePath(filename).stem, matrix, options, warnings)
    return [table] if table else []


def _guard_xlsx(content: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = archive.infolist()
            if len(files) > 10000:
                raise ValueError("The workbook contains too many internal files.")
            total = sum(info.file_size for info in files)
            if total > 200 * 1024 * 1024:
                raise ValueError("The workbook expands beyond the 200 MB safety limit. Save a smaller workbook.")
            for info in files:
                if info.flag_bits & 1:
                    raise ValueError("Encrypted workbooks are unsupported. Upload an unencrypted copy.")
                if info.file_size > 100 * 1024 * 1024 or (info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > 1000):
                    raise ValueError("The workbook has an unsafe compressed size. Save a smaller workbook.")
    except zipfile.BadZipFile as exc:
        raise ValueError("The Excel workbook is corrupted or is not a valid .xlsx file.") from exc


def _excel_tables(filename: str, content: bytes, options: dict, warnings: list[str]) -> list[dict]:
    tables, total = [], 0
    extension = PurePath(filename).suffix.lower()
    if extension == ".xlsx":
        from openpyxl import load_workbook
        _guard_xlsx(content)
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
            try:
                if len(workbook.worksheets) > MAX_TABLES:
                    raise ValueError(f"Workbooks with more than {MAX_TABLES} worksheets are unsupported. Split the workbook.")
                for i, sheet in enumerate(workbook.worksheets):
                    # Do not trust inflated producer dimensions. Stream real rows,
                    # but refuse unbounded dimensions before any allocation.
                    if (sheet.max_column or 0) > MAX_COLUMNS:
                        raise ValueError(f"Worksheet '{sheet.title}' has more than {MAX_COLUMNS} columns. Remove unused formatted columns and try again.")
                    if (sheet.max_row or 0) > MAX_ROWS + 100:
                        raise ValueError(f"Worksheet '{sheet.title}' exceeds {MAX_ROWS:,} rows. Remove unused formatted rows or split it.")
                    matrix = []
                    for row in sheet.iter_rows(values_only=True):
                        if len(matrix) > MAX_ROWS + 100:
                            raise ValueError(f"Worksheet '{sheet.title}' exceeds the row limit.")
                        matrix.append(list(row))
                    table = _matrix_table(f"sheet-{i}", sheet.title, matrix, options, warnings)
                    if table:
                        total += len(table["rows"])
                        tables.append(table)
                    else:
                        warnings.append(f"Worksheet '{sheet.title}' contains no data rows and was skipped.")
            finally:
                workbook.close()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The Excel workbook could not be read. Check that it is unencrypted and not corrupted.") from exc
    else:
        import xlrd
        if not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ValueError("The .xls file is not a valid legacy Excel workbook. If it is CSV or XLSX, upload it with the correct extension.")
        try:
            book = xlrd.open_workbook(file_contents=content, on_demand=True)
            try:
                if book.nsheets > MAX_TABLES:
                    raise ValueError(f"Workbooks with more than {MAX_TABLES} worksheets are unsupported.")
                for i in range(book.nsheets):
                    sheet = book.sheet_by_index(i)
                    if sheet.nrows > MAX_ROWS + 100 or sheet.ncols > MAX_COLUMNS:
                        raise ValueError(f"Worksheet '{sheet.name}' exceeds the row or column safety limit.")
                    matrix = []
                    for row_index in range(sheet.nrows):
                        row = []
                        for cell in sheet.row(row_index):
                            if cell.ctype == xlrd.XL_CELL_DATE:
                                value = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                                value = bool(cell.value)
                            elif cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR}:
                                value = None
                            else:
                                value = cell.value
                            row.append(value)
                        matrix.append(row)
                    table = _matrix_table(f"sheet-{i}", sheet.name, matrix, options, warnings)
                    if table:
                        total += len(table["rows"])
                        tables.append(table)
                    else:
                        warnings.append(f"Worksheet '{sheet.name}' contains no data rows and was skipped.")
            finally:
                book.release_resources()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The legacy Excel workbook could not be read. Check that it is unencrypted and not corrupted.") from exc
    if total > MAX_TOTAL_ROWS:
        raise ValueError(f"The workbook contains more than {MAX_TOTAL_ROWS:,} total records. Import a smaller selection.")
    warnings.append("Excel formulas are never executed. Only cached formula values saved by Excel are imported; recalculate and save the workbook first if formula cells are blank.")
    return tables


def _flatten(obj: dict, prefix: str = "", output: dict | None = None) -> dict:
    output = {} if output is None else output
    for key, value in obj.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if len(name) > 200:
            raise ValueError("A nested JSON field name exceeds 200 characters. Simplify the object structure.")
        if isinstance(value, dict) and value:
            _flatten(value, name, output)
        else:
            if name in output:
                raise ValueError(f"Nested JSON fields collide at '{name}'. Rename literal dotted keys before importing.")
            if isinstance(value, list):
                serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)
                # A common API response wraps a large records array. Keep a
                # clear reference in its metadata row rather than rejecting an
                # otherwise valid dataset or duplicating megabytes in one cell.
                # Full records are discovered as child tables below and the
                # source file is retained by the API.
                if len(serialized) > MAX_CELL_CHARS:
                    output[name] = f"[Nested table: {len(value):,} items in '{name}'. Select its child table; full values remain in the original source.]"
                else:
                    output[name] = _scalar(serialized)
            else:
                output[name] = _scalar(value)
        if len(output) > MAX_COLUMNS:
            raise ValueError(f"A JSON object has more than {MAX_COLUMNS} flattened fields. Choose a narrower data export.")
    return output


def _json_tables(content: bytes, options: dict, warnings: list[str]) -> list[dict]:
    def reject_constant(value):
        raise ValueError(f"JSON contains nonstandard numeric value {value}. Replace it with null.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON contains duplicate key '{key}'. Rename duplicate keys to avoid losing data.")
            result[key] = value
        return result

    try:
        obj = json.loads(content.decode("utf-8-sig"), parse_constant=reject_constant, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("The JSON is invalid or too deeply nested. Upload valid UTF-8 JSON containing records.") from exc
    if not isinstance(obj, (dict, list)):
        raise ValueError("JSON must contain an object or array of records, not a single scalar value.")
    # Validate depth before flattening or serializing nested arrays. An
    # iterative traversal prevents deeply nested input from exhausting Python's
    # stack during table discovery.
    pending = [(obj, 0)]
    checked_nodes = 0
    while pending:
        node, depth = pending.pop()
        checked_nodes += 1
        if checked_nodes > 500_000:
            raise ValueError("The JSON contains too many values. Split it into smaller documents.")
        if depth > MAX_JSON_DEPTH:
            raise ValueError(f"JSON nesting exceeds {MAX_JSON_DEPTH} levels. Flatten the document first.")
        if isinstance(node, dict):
            pending.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            if len(node) > MAX_ROWS:
                raise ValueError(f"A JSON array exceeds {MAX_ROWS:,} values. Split it into smaller documents.")
            pending.extend((value, depth + 1) for value in node)
    tables = []
    candidate_paths = set()
    visited_nodes = 0
    total = 0

    def add(path: str, values: list, parent_context: dict | None = None):
        nonlocal total
        if len(values) > MAX_ROWS:
            raise ValueError(f"JSON table '{path}' exceeds {MAX_ROWS:,} records.")
        if not values:
            return
        if len(tables) >= MAX_TABLES:
            raise ValueError(f"The JSON contains more than {MAX_TABLES} record arrays. Split it into smaller documents.")
        rows, columns = [], []
        for value in values:
            row = _flatten(value) if isinstance(value, dict) else {"value": _scalar(value)}
            if parent_context:
                for k, v in parent_context.items():
                    if k not in row:
                        row[k] = v
            for column in row:
                if column not in columns:
                    columns.append(column)
            if len(columns) > MAX_COLUMNS:
                raise ValueError(f"JSON table '{path}' exceeds {MAX_COLUMNS} unique columns.")
            rows.append(row)
        if not columns:
            return
        for row in rows:
            for column in columns:
                row.setdefault(column, None)
        total += len(rows)
        if total > MAX_TOTAL_ROWS:
            raise ValueError(f"JSON tables exceed {MAX_TOTAL_ROWS:,} combined records. Split the document.")
        tables.append({"key": path, "name": path if path != "$" else "JSON records", "columns": columns, "rows": rows})
        candidate_paths.add(path)

    def walk(value, path: str, depth: int = 0):
        nonlocal visited_nodes
        visited_nodes += 1
        if visited_nodes > 500_000:
            raise ValueError("The JSON contains too many nested structures. Split it into smaller documents.")
        if depth > MAX_JSON_DEPTH:
            raise ValueError(f"JSON nesting exceeds {MAX_JSON_DEPTH} levels. Flatten the document first.")
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}", depth + 1)
        elif isinstance(value, list):
            if path not in candidate_paths:
                add(path, value)
            # Nested record arrays remain in their parent as serialized JSON,
            # and are also offered independently with a traceable parent index.
            nested_arrays: dict[str, list] = {}
            for parent_index, child in enumerate(value):
                if isinstance(child, dict):
                    def collect(item, prefix):
                        if isinstance(item, dict):
                            for key, val in item.items():
                                collect(val, f"{prefix}.{key}" if prefix else key)
                        elif isinstance(item, list):
                            bucket = nested_arrays.setdefault(prefix, [])
                            for nested in item:
                                record = dict(nested) if isinstance(nested, dict) else {"value": nested}
                                if "__parent_index" in record:
                                    raise ValueError("JSON field '__parent_index' conflicts with nested-record tracing. Rename it before importing.")
                                bucket.append({"__parent_index": parent_index, **record})
                    collect(child, "")
                elif isinstance(child, list):
                    walk(child, f"{path}[{parent_index}]", depth + 1)
            for field, values in nested_arrays.items():
                child_path = f"{path}[].{field}"
                if child_path not in candidate_paths:
                    add(child_path, values)
                # Continue discovering deeper arrays, with a hard depth bound.
                if depth + 1 > MAX_JSON_DEPTH:
                    raise ValueError("The JSON nesting is too deep.")
                for child in values:
                    if isinstance(child, dict):
                        for field_name, val in child.items():
                            if isinstance(val, (dict, list)):
                                walk(val, f"{child_path}.{field_name}", depth + 1)
    if isinstance(obj, list):
        walk(obj, "$")
    else:
        # Preserve metadata fields as a recoverable one-row table rather than
        # silently dropping them when choosing the usual response.data array.
        add("$", [obj])
        walk(obj, "$")
    if len(tables) > 1:
        warnings.append("Multiple JSON record paths were found. Choose the relevant table; nested arrays remain preserved in parent records and are also offered as separate tables.")
    if any(isinstance(value, (dict, list)) for value in (obj if isinstance(obj, list) else obj.values())):
        warnings.append("Nested object fields use dotted names. Array fields are preserved as JSON text or explicit child-table references when oversized; the original source retains full values. Child tables include a zero-based __parent_index when applicable.")
    skip = _offset(options, "skip_rows", 0)
    if skip:
        for table in tables:
            table["rows"] = table["rows"][skip:]
        tables = [table for table in tables if table["rows"]]
    return tables


def _pdf_tables(content: bytes, options: dict, warnings: list[str]) -> list[dict]:
    import pdfplumber
    if not content.lstrip().startswith(b"%PDF-"):
        raise ValueError("The file is not a valid PDF document.")
    tables, total = [], 0
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ValueError(f"PDFs with more than {MAX_PDF_PAGES} pages are unsupported. Upload the pages containing tables.")
            for page_number, page in enumerate(pdf.pages, 1):
                candidates = page.extract_tables()
                if not candidates and page.extract_text():
                    # Text-only tables without ruled cells can still be found
                    # through aligned text. Clearly flag this less certain pass.
                    candidates = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text", "min_words_vertical": 2})
                    if candidates:
                        warnings.append(f"Page {page_number}: a table was inferred from aligned text. Review its columns before importing.")
                for table_number, matrix in enumerate(candidates, 1):
                    if len(tables) >= MAX_TABLES:
                        raise ValueError(f"The PDF contains more than {MAX_TABLES} detected tables. Split the document.")
                    if len(matrix) > MAX_ROWS + 100:
                        raise ValueError("A PDF table exceeds the record limit.")
                    table = _matrix_table(f"page-{page_number}-table-{table_number}", f"Page {page_number} · Table {table_number}", matrix, options, warnings)
                    if table:
                        total += len(table["rows"])
                        tables.append(table)
            if total > MAX_TOTAL_ROWS:
                raise ValueError("The PDF contains too many extracted records. Split the document.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The PDF could not be read. It may be encrypted, damaged or unsupported. Upload an unencrypted text-based PDF.") from exc
    if not tables:
        raise ValueError("No tables were detected. Scanned/image-only PDFs require OCR, which is not enabled. Use a text-based PDF, Excel or CSV instead.")
    warnings.append("PDF extraction is heuristic. Review table boundaries, merged cells and numeric values before creating a dataset. OCR is not enabled for scanned PDFs.")
    return tables


def inspect_source(filename: str, content: bytes, options: dict | None = None) -> dict:
    """Extract all selectable tables from supported source bytes.

    `header_row` overrides automatic header detection, after `skip_rows` are
    removed. CSV accepts an explicit delimiter and encoding. Empty worksheets
    are skipped with a visible warning; no user-provided code is evaluated.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A filename is required.")
    if not isinstance(content, bytes):
        raise ValueError("The uploaded file must contain binary file data.")
    if not content:
        raise ValueError("The uploaded file is empty.")
    if len(content) > MAX_BYTES:
        raise ValueError("The file exceeds the 25 MB upload limit. Split or reduce it before importing.")
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported file type. Upload CSV, JSON, Excel (.xlsx/.xls) or a text-based PDF.")
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("Import options must be an object.")
    _offset(options, "skip_rows", 0)
    _offset(options, "header_row")
    warnings: list[str] = []
    try:
        if extension in {".csv", ".tsv", ".txt"}:
            tables = _csv_tables(filename, content, options, warnings)
        elif extension in {".xlsx", ".xls"}:
            tables = _excel_tables(filename, content, options, warnings)
        elif extension == ".json":
            tables = _json_tables(content, options, warnings)
        else:
            tables = _pdf_tables(content, options, warnings)
    except (MemoryError, RecursionError) as exc:
        raise ValueError("The file is too complex to import safely. Split or flatten it and try again.") from exc
    if not tables:
        raise ValueError("No nonempty tables with data rows were found. Include a header row and at least one record.")
    return {"tables": tables, "warnings": list(dict.fromkeys(warnings))}


def _sheet_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Enter a valid Google Sheets sharing URL.")
    try:
        parsed = urlsplit(url.strip())
        valid_authority = parsed.hostname == "docs.google.com" and parsed.username is None and parsed.password is None and parsed.port in {None, 443}
    except ValueError:
        raise ValueError("Enter a valid HTTPS Google Sheets URL.") from None
    if parsed.scheme != "https" or not valid_authority:
        raise ValueError("Use an HTTPS Google Sheets URL on docs.google.com. Other hosts, credentials and ports are not allowed.")
    match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]{10,200})(?:/(?:edit|view|preview|export))?/?", parsed.path)
    if not match:
        raise ValueError("Use the standard Google Sheets sharing link: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit . Published /d/e/ links are not supported.")
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = (query.get("gid") or fragment.get("gid") or ["0"])[0]
    if not re.fullmatch(r"\d{1,20}", gid):
        raise ValueError("The worksheet gid must be numeric. Copy the worksheet URL from Google Sheets.")
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?" + urlencode({"format": "csv", "gid": gid})


def fetch_sheet(url: str) -> tuple[str, bytes]:
    """Fetch one explicitly selected sheet through a constrained HTTPS route.

    Only a verified Google Sheets ID/gid is used. Automatic arbitrary redirects
    are forbidden; Google-owned sheet download hosts are checked each time.
    Optional GOOGLE_SHEETS_ACCESS_TOKEN stays server-side and is only sent to
    docs.google.com, never to a redirected host. No login is assumed to exist.
    """
    target = _sheet_url(url)
    token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN")
    for _ in range(5):
        host = urlsplit(target).hostname or ""
        headers = {"Accept": "text/csv"}
        if token and host == "docs.google.com":
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = requests.get(target, headers=headers, timeout=(8, 30), allow_redirects=False, stream=True)
        except requests.RequestException as exc:
            raise ValueError("Google Sheets could not be reached. Check network access to docs.google.com and try again.") from exc
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                try:
                    redirect = urlsplit(location)
                    redirect_host = redirect.hostname or ""
                    if redirect_host == "accounts.google.com":
                        raise ValueError("This sheet requires permission. Enable public link access, upload an exported file, or configure a server-side Google access token.")
                    if redirect.scheme != "https" or redirect.username is not None or redirect.password is not None or redirect.port not in {None, 443}:
                        raise ValueError("Google Sheets returned an unsafe redirect, which was blocked.")
                    if not (redirect_host == "docs.google.com" or redirect_host == "sheets.googleusercontent.com" or redirect_host.endswith(".sheets.googleusercontent.com")):
                        raise ValueError("Google Sheets redirected to an unsupported host. Export the sheet as CSV and upload it instead.")
                except ValueError as exc:
                    raise ValueError(str(exc)) from None
                target = location
                continue
            if response.status_code in {401, 403, 404}:
                raise ValueError("The sheet is unavailable or private. Verify its sharing permissions and worksheet ID, or upload an Excel/CSV export. Private access requires a server-side Google access token.")
            if response.status_code == 429:
                raise ValueError("Google Sheets is rate limiting downloads. Wait a moment and try again.")
            if response.status_code != 200:
                raise ValueError(f"Google Sheets could not be imported (HTTP {response.status_code}). Check the link and try again.")
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise ValueError("Google Sheets returned a sign-in page instead of CSV. Make the sheet accessible or upload an exported file.")
            declared_length = response.headers.get("Content-Length", "")
            if declared_length.isdigit() and int(declared_length) > MAX_BYTES:
                raise ValueError("The Google Sheet exceeds the 25 MB import limit. Export a smaller range.")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("The Google Sheet exceeds the 25 MB import limit. Export a smaller range.")
                chunks.append(chunk)
            content = b"".join(chunks)
            if not content.strip():
                raise ValueError("The selected Google worksheet is empty.")
            if content.lstrip()[:100].lower().startswith((b"<!doctype html", b"<html")):
                raise ValueError("The sheet requires Google sign-in. Enable sharing or upload an exported file.")
            return "google-sheet.csv", content
        except requests.RequestException as exc:
            raise ValueError("The Google Sheets download was interrupted. Try again or upload an exported file.") from exc
        finally:
            response.close()
    raise ValueError("Google Sheets returned too many redirects. Export it as CSV or Excel and upload the file.")
