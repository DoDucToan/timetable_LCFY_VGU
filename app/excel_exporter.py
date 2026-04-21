from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from sqlalchemy import select
from sqlalchemy.orm import Session

from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from .scheduler import build_timetable_payload, teacher_load_rows
from .models import StudyProgram

FILL_MAP = {
    "ielts": "9FC5E8",
    "german": "F9CB9C",
    "ae": "EAD1DC",
    "core": "F4B183",
    "shared": "D99A9A",
    "elective": "C49A00",
    "other": "D9D2E9",
}

PROGRAM_FILL_VARIANTS = [
    "C9DAF8",
    "F4B183",
    "D9D2E9",
    "B6D7A8",
    "EAD1DC",
    "FFF2CC",
    "D0E0E3",
    "FCE4D6",
    "E2EFDA",
    "F9CB9C",
]

BLANK_FILL = "D9D9D9"
REQUIRED_ROW_HEIGHT = 78
OVERLAY_ROW_HEIGHT = 26


def _format_item(item: Dict[str, Any]) -> str:
    parts = [item["course_name"]]
    if item["program_codes"]:
        parts.append(f"[{', '.join(item['program_codes'])}]")
    if item["notes"]:
        parts.append(item["notes"])
    if item["teacher_name"]:
        parts.append(item["teacher_name"])
    if item["room_name"]:
        parts.append(f"Room: {item['room_name']}")
    return "_".join(parts)


def _required_item(items: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for item in items:
        if item["kind"] == "required":
            return item
    return None


def _overlay_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [item for item in items if item["kind"] != "required"]


def _same_overlay(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = [
        "course_name",
        "teacher_name",
        "room_name",
        "notes",
        "kind",
        "color_key",
        "shared",
    ]
    return all(a.get(k) == b.get(k) for k in keys) and a.get("program_codes", []) == b.get("program_codes", [])


def _same_overlay_connectable(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    # Connect study-program overlays if they share the same course, teacher, room, and kind.
    return (
        a.get("kind") == "program"
        and b.get("kind") == "program"
        and a.get("course_name") == b.get("course_name")
        and a.get("teacher_name") == b.get("teacher_name")
        and a.get("room_name") == b.get("room_name")
        and a.get("notes") == b.get("notes")
        and a.get("color_key") == b.get("color_key")
    )


def _cell(ws: Worksheet, row: int, column: int, value: Any | None = None) -> Cell:
    return cast(Cell, ws.cell(row=row, column=column, value=value))


def _write_overlay_merge(
    ws: Worksheet,
    row_idx: int,
    start_col: int,
    end_col: int,
    item: Dict[str, Any],
    border: Border,
) -> None:
    ws.merge_cells(
        start_row=row_idx,
        start_column=start_col,
        end_row=row_idx,
        end_column=end_col,
    )
    cell = _cell(ws, row_idx, start_col, _format_item(item))
    cell.fill = PatternFill("solid", fgColor=item.get("fill_color", FILL_MAP.get(item["color_key"], "D9D2E9")))
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.font = Font(bold=True, size=10)
    for c in range(start_col, end_col + 1):
        ws.cell(row=row_idx, column=c).border = border


def export_timetable_xlsx(db: Session, output_path: str | Path, timetable_id: Optional[int] = None, study_program_ids: Optional[List[int]] = None) -> Path:
    output_path = Path(output_path)
    payload = build_timetable_payload(db, timetable_id, study_program_ids=study_program_ids)

    selected_program_codes: List[str] = []
    if study_program_ids is not None:
        selected_program_codes = [str(prog.code) for prog in db.scalars(select(StudyProgram).where(StudyProgram.id.in_(study_program_ids))).all()]

    wb = Workbook()
    ws = cast(Worksheet, wb.active)
    ws.title = "Phase4 Timetable"
    ws.freeze_panes = "C5"
    ws.sheet_view.showGridLines = False

    title_fill = PatternFill("solid", fgColor="1F4E78")
    header_fill = PatternFill("solid", fgColor="D9E2F3")
    lunch_fill = PatternFill("solid", fgColor="F2F2F2")
    blank_fill = PatternFill("solid", fgColor=BLANK_FILL)
    thin_gray = Side(style="thin", color="444444")
    border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)

    groups = payload["groups"]
    timeslots = payload["timeslots"]
    cell_map = payload["cells"]

    total_cols = 2 + len(groups)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    title_text = "Foundation Year 2025/26: Semester 2 - Phase 4"
    if selected_program_codes:
        title_text += f" - {', '.join(selected_program_codes)}"
    title_cell = _cell(ws, 1, 1, title_text)
    title_cell.fill = title_fill
    title_cell.font = Font(color="FFFFFF", bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
    subtitle_text = "Interactive export with required blocks on top and shared/program/elective strips below"
    if selected_program_codes:
        subtitle_text += f" (Study programs: {', '.join(selected_program_codes)})"
    subtitle_cell = _cell(ws, 2, 1, subtitle_text)
    subtitle_cell.alignment = Alignment(horizontal="center")
    subtitle_cell.font = Font(italic=True)

    ws["A4"] = "Day"
    ws["B4"] = "Time"
    for cell in [ws["A4"], ws["B4"]]:
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for idx, group in enumerate(groups, start=3):
        # Compose group name with study program codes in parentheses
        program_codes = ', '.join([p['code'] for p in group.get('programs', [])])
        group_label = group["code"]
        if program_codes:
            group_label += f" ({program_codes})"
        cell = ws.cell(row=4, column=idx, value=group_label)
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
        ws.column_dimensions[get_column_letter(idx)].width = 24

    row = 5
    weekday_names = {1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY", 4: "THURSDAY", 5: "FRIDAY"}
    day_to_slots: Dict[str, List[Dict[str, Any]]] = {}
    for ts in timeslots:
        day_to_slots.setdefault(ts["weekday"], []).append(ts)

    for day_idx in range(1, 6):
        weekday = weekday_names[day_idx]
        day_slots: List[Dict[str, Any]] = sorted(day_to_slots.get(weekday, []), key=lambda item: item["sort_order"])
        day_start_row = row

        for slot_index, slot in enumerate(day_slots):
            slot_items = cell_map.get(str(slot["id"]), {})
            overlay_depth = 0
            for group in groups:
                items = slot_items.get(str(group["id"]), [])
                overlay_depth = max(overlay_depth, len(_overlay_items(items)))

            slot_start_row = row
            required_row = row
            overlay_rows = [required_row + i + 1 for i in range(overlay_depth)]
            slot_end_row = required_row + overlay_depth

            ws.merge_cells(start_row=slot_start_row, start_column=2, end_row=slot_end_row, end_column=2)
            time_cell = ws.cell(row=slot_start_row, column=2, value=slot["label"])
            time_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            time_cell.border = border

            ws.row_dimensions[required_row].height = REQUIRED_ROW_HEIGHT
            for overlay_row in overlay_rows:
                ws.row_dimensions[overlay_row].height = OVERLAY_ROW_HEIGHT


            # Merge horizontally for required blocks (required_all) if adjacent groups have the same required class
            col_idx = 3
            while col_idx <= total_cols:
                group_index = col_idx - 3
                if group_index >= len(groups):
                    break
                group = groups[group_index]
                items = slot_items.get(str(group["id"]), [])
                req = _required_item(items)
                if not req:
                    col_idx += 1
                    continue
                end_col = col_idx
                next_col = col_idx + 1
                while next_col <= total_cols:
                    next_group = groups[next_col - 3]
                    next_items = slot_items.get(str(next_group["id"]), [])
                    next_req = _required_item(next_items)
                    if not next_req or not _same_overlay(req, next_req):
                        break
                    end_col = next_col
                    next_col += 1
                if end_col > col_idx:
                    _write_overlay_merge(ws, required_row, col_idx, end_col, req, border)
                    col_idx = end_col + 1
                else:
                    req_cell = _cell(ws, required_row, col_idx)
                    req_cell.value = _format_item(req)
                    req_cell.fill = PatternFill("solid", fgColor=FILL_MAP.get(req["color_key"], "D9D2E9"))
                    req_cell.border = border
                    req_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    req_cell.font = Font(bold=True, size=10)
                    col_idx += 1
            # Fill blanks for required blocks with no class
            for col_idx2, group in enumerate(groups, start=3):
                items = slot_items.get(str(group["id"]), [])
                req = _required_item(items)
                req_cell = _cell(ws, required_row, col_idx2)
                if not req_cell.value:
                    req_cell.fill = blank_fill
                    req_cell.border = border

                for overlay_row in overlay_rows:
                    cell = _cell(ws, overlay_row, col_idx2)
                    cell.border = border
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    cell.font = Font(bold=True, size=10)


            # Improved overlay merging: align overlays by content, not index
            # 1. Gather all overlays for this slot across all groups
            overlay_rows_content: List[List[Dict[str, Any]]] = []
            for group in groups:
                items = _overlay_items(slot_items.get(str(group["id"]), []))
                deduped: List[Dict[str, Any]] = []
                for item in items:
                    if not any(_same_overlay(item, d) for d in deduped):
                        deduped.append(item)
                overlay_rows_content.append(deduped)

            # 2. Find all unique overlays (by content) in this slot, in order of first appearance.
            #    Merge study-program overlays that are connectable across columns by teacher/room/course.
            unique_overlays: List[Dict[str, Any]] = []
            for overlays in overlay_rows_content:
                for item in overlays:
                    found = next((uo for uo in unique_overlays if _same_overlay_connectable(item, uo)), None)
                    if found:
                        found["program_codes"] = sorted(set(found.get("program_codes", []) + item.get("program_codes", [])))
                    elif not any(_same_overlay(item, uo) for uo in unique_overlays):
                        unique_overlays.append({**item, "program_codes": list(item.get("program_codes", []))})

            # 3. For each unique overlay, place the overlay item on its aligned row and merge horizontally.
            for overlay_idx, overlay_item in enumerate(unique_overlays):
                overlay_row = required_row + 1 + overlay_idx
                row_has_overlay = [any(_same_overlay_connectable(item, overlay_item) for item in group_items) for group_items in overlay_rows_content]
                present_cols = [3 + idx for idx, has in enumerate(row_has_overlay) if has]
                if overlay_item.get("kind") == "program" and len(present_cols) > 1:
                    start_col = min(present_cols)
                    end_col = max(present_cols)
                    _write_overlay_merge(ws, overlay_row, start_col, end_col, overlay_item, border)
                else:
                    col_idx = 3
                    while col_idx <= total_cols:
                        if col_idx - 3 >= len(row_has_overlay):
                            break
                        if not row_has_overlay[col_idx - 3]:
                            col_idx += 1
                            continue
                        end_col = col_idx
                        next_col = col_idx + 1
                        while next_col <= total_cols and next_col - 3 < len(row_has_overlay) and row_has_overlay[next_col - 3]:
                            end_col = next_col
                            next_col += 1
                        _write_overlay_merge(ws, overlay_row, col_idx, end_col, overlay_item, border)
                        col_idx = end_col + 1

            # Fill blanks for any overlay cells that do not contain this overlay item
            for overlay_idx, overlay_item in enumerate(unique_overlays):
                overlay_row = required_row + 1 + overlay_idx
                for col_idx2, group in enumerate(groups, start=3):
                    group_items = overlay_rows_content[col_idx2 - 3]
                    if not any(_same_overlay_connectable(item, overlay_item) for item in group_items):
                        cell = _cell(ws, overlay_row, col_idx2)
                        cell.fill = blank_fill
                        cell.border = border

            for rr in range(slot_start_row, slot_end_row + 1):
                ws.cell(row=rr, column=2).border = border

            row = slot_end_row + 1

            # Lunch must be placed between the morning and afternoon slots.
            if slot_index == 0 and len(day_slots) > 1:
                lunch_row = row
                ws.merge_cells(start_row=lunch_row, start_column=2, end_row=lunch_row, end_column=total_cols)
                lunch = ws.cell(row=lunch_row, column=2, value="Lunch break")
                lunch.fill = lunch_fill
                lunch.alignment = Alignment(horizontal="center")
                lunch.font = Font(italic=True)
                for c in range(2, total_cols + 1):
                    ws.cell(row=lunch_row, column=c).border = border
                row += 1

        day_end_row = row - 1
        ws.merge_cells(start_row=day_start_row, start_column=1, end_row=day_end_row, end_column=1)
        dcell = ws.cell(row=day_start_row, column=1, value=weekday)
        dcell.alignment = Alignment(horizontal="center", vertical="center", text_rotation=90)
        dcell.font = Font(bold=True)
        dcell.fill = PatternFill("solid", fgColor="E2EFDA")
        dcell.border = border
        for rr in range(day_start_row, day_end_row + 1):
            ws.cell(row=rr, column=1).border = border

    # Clean up any cells after the last group column for all timetable rows
    # Timetable rows are from row 5 to (row - 1) before teacher summary
    timetable_end_row = row - 1
    last_group_col = 2 + len(groups)
    max_col = ws.max_column
    white_fill = PatternFill("solid", fgColor="FFFFFF")
    for r in range(5, timetable_end_row + 1):
        for c in range(last_group_col + 1, max_col + 1):
            cell = _cell(ws, r, c)
            cell.value = None
            cell.fill = white_fill
            cell.border = Border()  # Remove all borders

    start_teacher = row + 2
    ws.cell(row=start_teacher, column=1, value="Teacher load summary").font = Font(bold=True, size=12)
    ws.cell(row=start_teacher + 1, column=1, value="Teacher").font = Font(bold=True)
    ws.cell(row=start_teacher + 1, column=2, value="Taught timeslots").font = Font(bold=True)
    for idx, item in enumerate(teacher_load_rows(db, timetable_id, study_program_ids), start=start_teacher + 2):
        ws.cell(row=idx, column=1, value=item["teacher"])
        ws.cell(row=idx, column=2, value=item["timeslot_count"])

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 16
    wb.save(output_path)
    return output_path
