"""Round 1's spreadsheet import, ported - including Round 1's own qualifier export."""
from __future__ import annotations

import io

from openpyxl import Workbook, load_workbook

from app.services import export_service
from app.services.team_import_service import (
    ParsedSheet,
    build_rows,
    detect_columns,
    generate_team_code,
    normalise_phone,
    parse_sheet,
    password_from_phone,
)
from tests.helpers import seed

API = "/api/v1"


def test_phone_rules_match_round1():
    assert normalise_phone("+91 98765 43210") == "9876543210"
    assert password_from_phone("98765 43210") == "9876"
    assert password_from_phone(9876543210.0) == "9876"
    assert password_from_phone("12") == ""


def test_generated_codes_are_round1_format():
    taken: set[str] = set()
    codes = {generate_team_code(taken) for _ in range(50)}
    assert len(codes) == 50 and all(c.startswith("B@GCEE-") and c.endswith("#") and len(c) == 12 for c in codes)


def test_column_detection_handles_round1_qualifier_export():
    headers = ["Seed", "Team Code", "Team Name", "Room", "Room Rank", "Leader", "Phone", "Email", "MindMaze", "Total"]
    mapping = detect_columns(headers)
    assert mapping["team_code"] == 1 and mapping["team_name"] == 2
    assert mapping["leader_name"] == 5 and mapping["leader_phone"] == 6 and mapping["leader_email"] == 7


def test_existing_codes_are_kept_and_duplicates_flagged():
    parsed = ParsedSheet(
        headers=["Team Code", "Team Name", "Phone"],
        rows=[["B@GCEE-7391#", "Alpha", "9876543210"], ["B@GCEE-7391#", "Beta", "9123456780"], ["", "Gamma", "9000000000"]],
        header_row_number=1,
    )
    rows = build_rows(parsed, detect_columns(parsed.headers), existing_names=[], existing_codes=[], capacity=60)
    assert rows[0].status == "OK" and rows[0].team_code == "B@GCEE-7391#" and rows[0].password == "9876"
    assert rows[1].status == "DUPLICATE_CODE"
    assert rows[2].status == "OK" and rows[2].team_code.startswith("B@GCEE-")


def _qualifier_sheet() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Round 2 Qualifiers"
    ws.append(["Round 1 - qualifiers"])  # title banner, like Round 1's export
    ws.append([])
    ws.append(["Seed", "Team Code", "Team Name", "Room", "Leader", "Phone", "Email", "Total"])
    ws.append([1, "B@GCEE-4242#", "Night Owls", "R01", "Priya", "+91 99887 76655", "p@x.com", 50])
    ws.append([2, "B@GCEE-5151#", "Sky Walkers", "R02", "Vijay", "9012345678", "", 48])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_import_round1_qualifiers_keeps_their_logins(client):
    demo = seed(client)
    files = {"file": ("qualifiers.xlsx", _qualifier_sheet(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    preview = client.post(f"{API}/admin/events/{demo.event_id}/teams/import/preview", files=files, headers=demo.admin).json()
    assert preview["header_row_number"] == 3 and preview["importable_count"] == 2
    rows = [r for r in preview["rows"] if r["status"] == "OK"]
    assert [r["team_code"] for r in rows] == ["B@GCEE-4242#", "B@GCEE-5151#"]

    created = client.post(f"{API}/admin/events/{demo.event_id}/teams/import", json={"rows": rows}, headers=demo.admin)
    assert created.status_code == 201 and created.json()["created_count"] == 2
    login = client.post(f"{API}/auth/team/login", json={"team_code": "B@GCEE-4242#", "password": "9988"})
    assert login.status_code == 200 and login.json()["team_name"] == "Night Owls"

    sheet = client.post(f"{API}/admin/teams/credentials-export", json=created.json(), headers=demo.admin)
    wb = load_workbook(io.BytesIO(sheet.content))
    values = [c for row in wb.active.iter_rows(values_only=True) for c in row]
    assert "B@GCEE-4242#" in values and "9988" in values


def test_template_round_trips_through_the_importer():
    parsed = parse_sheet(export_service.build_import_template(), "template.xlsx")
    mapping = detect_columns(parsed.headers)
    assert {"team_code", "team_name", "leader_name", "leader_phone", "leader_email"} <= set(mapping)
    assert len(parsed.rows) == 2
