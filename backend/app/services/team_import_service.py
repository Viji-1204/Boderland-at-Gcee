"""Bulk team registration from a spreadsheet (ported from Round 1).

Same login rules as Round 1:
    team_code : kept from the sheet if it has a "Team Code" column (so Round 1
                qualifiers keep their login), otherwise B@GCEE-#### (random)
    password  : the first 4 digits of the team leader's phone number

Round 1's "Round 2 Qualifiers" export imports as-is: columns are matched by
header name, title banner rows are skipped.

Two-phase, as in Round 1: ``parse_upload`` only reads and reports exactly
what would be created, and ``commit_import`` writes the reviewed rows in one
transaction. Everything above ``parse_upload`` is pure and unit-tested.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError
from app.core.security import hash_password
from app.models import Event, EventStatus, Team, TeamStatus
from app.services.event_settings import event_settings

TEAM_CODE_PREFIX = "B@GCEE-"
TEAM_CODE_SUFFIX = "#"
TEAM_CODE_DIGITS = 4
PASSWORD_DIGITS = 4
MAX_TEAMS = 60
HEADER_SCAN_ROWS = 10
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "team_code": ("team code", "team id", "login code", "login id", "team login"),
    "team_name": ("team name", "name of the team", "name of team", "team title", "group name", "team", "group"),
    "leader_name": ("team leader name", "leader name", "name of the leader", "team leader", "leader", "captain", "team lead", "representative"),
    "leader_phone": (
        "leader phone number", "whatsapp number", "contact number", "mobile number", "phone number",
        "contact no", "mobile no", "phone no", "whatsapp", "mobile", "contact", "phone",
    ),
    "leader_email": ("email address", "email id", "e mail", "email", "mail id", "gmail", "mail"),
    "sentence": ("secret sentence", "team sentence", "sentence", "phrase"),
}
REQUIRED_FIELDS = ("team_name", "leader_phone")


def normalise_header(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def _score_header(header: str, synonyms: Sequence[str]) -> int:
    if not header:
        return 0
    best = 0
    for index, synonym in enumerate(synonyms):
        specificity = len(synonyms) - index
        if header == synonym:
            best = max(best, 1000 + specificity)
        elif synonym in header:
            best = max(best, 100 + len(synonym) * 2 + specificity)
    return best


def detect_columns(headers: Sequence[Any]) -> dict[str, int]:
    normalised = [normalise_header(h) for h in headers]
    candidates: list[tuple[int, str, int]] = []
    for field_name, synonyms in COLUMN_SYNONYMS.items():
        for col, header in enumerate(normalised):
            score = _score_header(header, synonyms)
            if score:
                candidates.append((score, field_name, col))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for _score, field_name, col in candidates:
        if field_name in mapping or col in used:
            continue
        mapping[field_name] = col
        used.add(col)
    return mapping


def _resolve_override(override: str, headers: Sequence[Any]) -> int:
    override = override.strip()
    if not override:
        raise AppError("Empty column override")
    if override.isdigit():
        index = int(override)
        if not 0 <= index < len(headers):
            raise AppError(f"Column index {index} is outside the sheet (0-{len(headers) - 1})")
        return index
    if re.fullmatch(r"[A-Za-z]{1,3}", override):
        index = 0
        for char in override.upper():
            index = index * 26 + (ord(char) - ord("A") + 1)
        index -= 1
        if 0 <= index < len(headers):
            return index
    target = normalise_header(override)
    for col, header in enumerate(headers):
        if normalise_header(header) == target:
            return col
    raise AppError(f"No column named '{override}' in the sheet")


def apply_overrides(mapping: dict[str, int], headers: Sequence[Any], overrides: dict[str, str | None]) -> dict[str, int]:
    resolved = dict(mapping)
    for field_name, override in overrides.items():
        if override is None or not str(override).strip():
            continue
        if field_name not in COLUMN_SYNONYMS:
            raise AppError(f"Unknown column override '{field_name}'")
        resolved[field_name] = _resolve_override(str(override), headers)
    return resolved


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def team_name_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _cell_text(value)).strip().casefold()


def normalise_phone(raw: Any) -> str:
    digits = re.sub(r"\D", "", _cell_text(raw))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def password_from_phone(raw: Any) -> str:
    digits = normalise_phone(raw)
    if len(digits) < PASSWORD_DIGITS:
        return ""
    return digits[:PASSWORD_DIGITS]


def clean_team_code(raw: Any) -> str:
    code = re.sub(r"\s+", "", _cell_text(raw))
    return code[:40]


def generate_team_code(taken: set[str]) -> str:
    space = 10**TEAM_CODE_DIGITS

    def code_for(number: int) -> str:
        return f"{TEAM_CODE_PREFIX}{number:0{TEAM_CODE_DIGITS}d}{TEAM_CODE_SUFFIX}"

    for _ in range(64):
        code = code_for(secrets.randbelow(space))
        if code not in taken:
            taken.add(code)
            return code
    start = secrets.randbelow(space)
    for offset in range(space):
        code = code_for((start + offset) % space)
        if code not in taken:
            taken.add(code)
            return code
    raise ConflictError("Could not generate a free team code - every code is already in use.")


@dataclass
class ParsedSheet:
    headers: list[str]
    rows: list[list[Any]]
    header_row_number: int
    sheet_name: str | None = None


def _rows_from_csv(data: bytes) -> tuple[list[list[Any]], str | None]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)], None


def _rows_from_xlsx(data: bytes) -> tuple[list[list[Any]], str | None]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise AppError("Excel support needs openpyxl: run `pip install openpyxl`.") from exc
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AppError("That file could not be opened as an Excel workbook. Re-save it as .xlsx and try again.") from exc
    sheet = workbook.active
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    name = sheet.title
    workbook.close()
    return rows, name


def _find_header_row(rows: Sequence[Sequence[Any]]) -> int:
    best_index, best_score = 0, -1
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if not any(_cell_text(cell) for cell in row):
            continue
        mapping = detect_columns(row)
        score = sum(1 for f in COLUMN_SYNONYMS if f in mapping) + sum(2 for f in REQUIRED_FIELDS if f in mapping)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def parse_sheet(data: bytes, filename: str) -> ParsedSheet:
    if not data:
        raise AppError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    lower = (filename or "").lower()
    if lower.endswith((".csv", ".txt")):
        rows, sheet_name = _rows_from_csv(data)
    elif lower.endswith((".xlsx", ".xlsm")):
        rows, sheet_name = _rows_from_xlsx(data)
    elif lower.endswith(".xls"):
        raise AppError("Legacy .xls files aren't supported. Re-save the file as .xlsx and upload again.")
    elif data[:2] == b"PK":
        rows, sheet_name = _rows_from_xlsx(data)
    else:
        rows, sheet_name = _rows_from_csv(data)
    if not rows:
        raise AppError("The sheet has no rows.")
    header_index = _find_header_row(rows)
    headers = [_cell_text(cell) for cell in rows[header_index]]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise AppError("Could not find a header row in the sheet.")
    data_rows = [row for row in rows[header_index + 1 :] if any(_cell_text(c) for c in row)]
    return ParsedSheet(headers=headers, rows=data_rows, header_row_number=header_index + 1, sheet_name=sheet_name)


STATUS_OK = "OK"
STATUS_NAME_TOO_LONG = "NAME_TOO_LONG"
STATUS_MISSING_TEAM_NAME = "MISSING_TEAM_NAME"
STATUS_INVALID_PHONE = "INVALID_PHONE"
STATUS_DUPLICATE_IN_FILE = "DUPLICATE_IN_FILE"
STATUS_DUPLICATE_IN_DB = "DUPLICATE_IN_DB"
STATUS_DUPLICATE_CODE = "DUPLICATE_CODE"
STATUS_OVER_CAPACITY = "OVER_CAPACITY"

STATUS_MESSAGES = {
    STATUS_OK: "Ready to import",
    STATUS_NAME_TOO_LONG: "Team name is longer than 120 characters",
    STATUS_MISSING_TEAM_NAME: "No team name in this row",
    STATUS_INVALID_PHONE: f"Leader's phone has fewer than {PASSWORD_DIGITS} digits - no password can be derived",
    STATUS_DUPLICATE_IN_FILE: "Another row in this file uses the same team name",
    STATUS_DUPLICATE_IN_DB: "A team with this name already exists in this event",
    STATUS_DUPLICATE_CODE: "This team code is already used by another team",
    STATUS_OVER_CAPACITY: f"Would exceed the {MAX_TEAMS}-team limit",
}


@dataclass
class ImportRow:
    row_number: int
    team_name: str
    leader_name: str
    leader_phone: str
    leader_email: str
    team_code: str
    password: str
    sentence: str
    status: str
    message: str

    @property
    def is_importable(self) -> bool:
        return self.status == STATUS_OK


@dataclass
class ImportPreview:
    rows: list[ImportRow]
    headers: list[str]
    column_map: dict[str, int]
    unmapped_required: list[str] = field(default_factory=list)
    header_row_number: int = 1
    sheet_name: str | None = None
    existing_team_count: int = 0
    capacity_remaining: int = MAX_TEAMS


def build_rows(
    parsed: ParsedSheet,
    column_map: dict[str, int],
    *,
    existing_names: Iterable[str],
    existing_codes: Iterable[str],
    capacity: int,
) -> list[ImportRow]:
    existing_name_keys = {team_name_key(n) for n in existing_names}
    taken_codes = set(existing_codes)
    seen_names: set[str] = set()
    seen_codes: set[str] = set()

    def cell(row: Sequence[Any], name: str) -> str:
        index = column_map.get(name)
        if index is None or index >= len(row):
            return ""
        return _cell_text(row[index])

    out: list[ImportRow] = []
    accepted = 0
    for offset, raw in enumerate(parsed.rows):
        row_number = parsed.header_row_number + 1 + offset
        team_name = cell(raw, "team_name")
        phone_raw = cell(raw, "leader_phone")
        sheet_code = clean_team_code(cell(raw, "team_code"))
        password = password_from_phone(phone_raw)
        key = team_name_key(team_name)

        if not team_name:
            status = STATUS_MISSING_TEAM_NAME
        elif len(team_name) > 120:
            status = STATUS_NAME_TOO_LONG
        elif key in seen_names:
            status = STATUS_DUPLICATE_IN_FILE
        elif key in existing_name_keys:
            status = STATUS_DUPLICATE_IN_DB
        elif sheet_code and (sheet_code in taken_codes or sheet_code in seen_codes):
            status = STATUS_DUPLICATE_CODE
        elif not password:
            status = STATUS_INVALID_PHONE
        elif accepted >= capacity:
            status = STATUS_OVER_CAPACITY
        else:
            status = STATUS_OK
        if team_name:
            seen_names.add(key)

        code = ""
        if status == STATUS_OK:
            if sheet_code:
                code = sheet_code
                taken_codes.add(code)
            else:
                code = generate_team_code(taken_codes)
            seen_codes.add(code)
            accepted += 1

        out.append(
            ImportRow(
                row_number=row_number,
                team_name=team_name,
                leader_name=cell(raw, "leader_name")[:120],
                leader_phone=(normalise_phone(phone_raw) or phone_raw)[:32],
                leader_email=cell(raw, "leader_email")[:160],
                team_code=code,
                password=password,
                sentence=cell(raw, "sentence")[:1000],
                status=status,
                message=STATUS_MESSAGES[status],
            )
        )
    return out


def _existing(db: Session, event_id: str) -> tuple[list[str], list[str]]:
    rows = db.execute(select(Team.team_name, Team.team_code).where(Team.event_id == event_id)).all()
    return [r[0] for r in rows], [r[1] for r in rows]


def parse_upload(db: Session, event: Event, *, data: bytes, filename: str, overrides: dict[str, str | None] | None = None) -> ImportPreview:
    parsed = parse_sheet(data, filename)
    column_map = detect_columns(parsed.headers)
    if overrides:
        column_map = apply_overrides(column_map, parsed.headers, overrides)
    unmapped = [f for f in REQUIRED_FIELDS if f not in column_map]
    names, codes = _existing(db, event.id)
    capacity = max(0, MAX_TEAMS - len(names))
    rows = [] if unmapped else build_rows(parsed, column_map, existing_names=names, existing_codes=codes, capacity=capacity)
    return ImportPreview(
        rows=rows,
        headers=parsed.headers,
        column_map=column_map,
        unmapped_required=unmapped,
        header_row_number=parsed.header_row_number,
        sheet_name=parsed.sheet_name,
        existing_team_count=len(names),
        capacity_remaining=capacity,
    )


def commit_import(db: Session, event: Event, *, rows: Sequence[dict]) -> list[dict]:
    if event.status != EventStatus.DRAFT:
        raise ConflictError("Teams can only be imported while the event is in DRAFT.")
    if not rows:
        raise AppError("No rows to import.")
    names, codes = _existing(db, event.id)
    name_keys = {team_name_key(n) for n in names}
    taken = set(codes)
    if len(names) + len(rows) > MAX_TEAMS:
        raise ConflictError(f"Importing {len(rows)} teams would exceed the {MAX_TEAMS}-team limit ({len(names)} already registered).")

    start_points = int(event_settings(event)["starting_power_points"])
    created: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        team_name = str(row.get("team_name", "")).strip()
        if not team_name:
            raise AppError("A row in the confirmed list has no team name.")
        key = team_name_key(team_name)
        if key in seen or key in name_keys:
            raise ConflictError(f"Duplicate team name in the import: '{team_name}'")
        seen.add(key)

        password = str(row.get("password", "")).strip() or password_from_phone(row.get("leader_phone"))
        if not password:
            raise AppError(f"No password could be derived for team '{team_name}'.")

        code = clean_team_code(row.get("team_code"))
        if code and code in taken:
            raise ConflictError(f"Team code '{code}' is already in use.")
        if not code:
            code = generate_team_code(taken)
        else:
            taken.add(code)

        team = Team(
            event_id=event.id,
            team_code=code,
            team_name=team_name,
            password_hash=hash_password(password),
            leader_name=str(row.get("leader_name", "")).strip() or None,
            leader_phone=str(row.get("leader_phone", "")).strip() or None,
            leader_email=str(row.get("leader_email", "")).strip() or None,
            sentence=str(row.get("sentence", "")).strip() or None,
            status=TeamStatus.NOT_STARTED,
            power_points=start_points,
        )
        db.add(team)
        db.flush()
        created.append(
            {
                "team_id": team.id,
                "team_code": code,
                "team_name": team_name,
                "password": password,
                "leader_name": team.leader_name,
                "leader_phone": team.leader_phone,
                "leader_email": team.leader_email,
            }
        )
    return created
