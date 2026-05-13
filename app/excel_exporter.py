from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from openpyxl import Workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.dimensions import RowDimension
from openpyxl.worksheet.worksheet import Worksheet
from .scheduler import build_timetable_payload, teacher_load_rows
from .models import Group, GroupStudyProgram, StudyProgram, ScheduledClass
import re

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
    "FFEB9C",
    "B4C6E7",
    "EAD1E7",
    "D9EBCF",
    "F7D9A6",
    "CFE2FF",
]

TAG_FILL_VARIANTS = [
    "F4B183",
    "B6D7A8",
    "C9DAF8",
    "EAD1DC",
    "FCE4D6",
    "D0E0E3",
    "FFF2CC",
    "D9D2E9",
    "E2EFDA",
    "F9CB9C",
]

BLANK_FILL = "D9D9D9"
REQUIRED_ROW_HEIGHT = 117
OVERLAY_ROW_HEIGHT = 40
_LINE_HEIGHT_PTS = 22    # ← add this
_OVERLAY_MIN_HEIGHT = 24  # ← add this

def _format_item(item: Dict[str, Any]) -> str:
    course_name = str(item["course_name"])
    parts: List[str] = []
    if item.get("kind") == "elective":
        parts.append("(Elective)")
    parts.append(course_name)
    group_codes: List[str] = cast(List[str], item.get("group_codes") or [])
    if item.get("kind") == "required":
        if len(group_codes) > 1:
            parts.append(f"({', '.join(group_codes)})")
    elif item.get("kind") != "elective" and group_codes:
        parts.append(f"({', '.join(group_codes)})")
    if item.get("all_group"):
        parts.append("(all group)")
    if item["program_codes"]:
        parts.append(f"[{', '.join(item['program_codes'])}]")
    if item["notes"]:
        parts.append(item["notes"])
    if item["teacher_name"]:
        parts.append(item["teacher_name"])
    if item["room_name"]:
        parts.append(f"Room: {item['room_name']}")
    if item.get("kind") == "required":
        return "\n".join(parts)
    return " ".join(parts)


def _estimate_line_count(text: str, width_cols: int) -> int:
    line_width = max(12, int(18 * width_cols))
    total_lines = 0
    paragraphs = text.split("\n")  # ← NEW: honour hard newlines
    separators = [" ", "_", "-", "/", ",", "(", ")", "["]

    for paragraph in paragraphs:
        words: List[str] = [paragraph]
        for sep in separators:
            parts: List[str] = []
            for word in words:
                parts.extend(word.split(sep))
            words = [part for part in parts if part]

        if not words:
            total_lines += 1
            continue

        line_count = 0
        current_len = 0
        for word in words:
            word_len = len(word)
            if current_len == 0:
                current_len = word_len
            elif current_len + 1 + word_len <= line_width:
                current_len += 1 + word_len
            else:
                line_count += 1
                current_len = word_len
            if word_len >= line_width:
                line_count += word_len // line_width
                current_len = word_len % line_width
        if current_len > 0:
            line_count += 1
        total_lines += max(1, line_count)

    return max(1, total_lines)




def _row_height_for_text(text: str, width_cols: int = 1, min_height: int = 24) -> int:
    line_count = _estimate_line_count(text, width_cols)
    return max(min_height, line_count * _LINE_HEIGHT_PTS + 10)  # ← uses constant


def _program_fill_color(program_codes: List[str]) -> str:
    if not program_codes:
        return PROGRAM_FILL_VARIANTS[0]
    key = "|".join(sorted(program_codes))
    return PROGRAM_FILL_VARIANTS[abs(hash(key)) % len(PROGRAM_FILL_VARIANTS)]


def _get_fill_color(item: Dict[str, Any]) -> str:
    if item.get("kind") == "program":
        if item.get("fill_color"):
            return item["fill_color"]
        program_codes = item.get("program_codes", [])
        return _program_fill_color([str(code) for code in program_codes])

    if item.get("kind") == "elective":
        return FILL_MAP.get("elective", "C49A00")

    color_key = item.get("color_key") or str(item.get("course_code", "other"))
    return FILL_MAP.get(color_key, TAG_FILL_VARIANTS[abs(hash(color_key)) % len(TAG_FILL_VARIANTS)])


def _assign_program_colors_for_slot(overlays: List[Dict[str, Any]], program_color_map: Dict[str, str]) -> None:
    used: set[str] = set(program_color_map.values())
    for item in overlays:
        if item.get("kind") != "program":
            continue
        program_codes = sorted(set(item.get("program_codes", [])))
        if not program_codes:
            continue
        program_key = ",".join(program_codes)
        if program_key not in program_color_map:
            index = abs(hash(program_key)) % len(PROGRAM_FILL_VARIANTS)
            for attempt in range(len(PROGRAM_FILL_VARIANTS)):
                candidate = PROGRAM_FILL_VARIANTS[(index + attempt) % len(PROGRAM_FILL_VARIANTS)]
                if candidate not in used:
                    program_color_map[program_key] = candidate
                    used.add(candidate)
                    break
            else:
                program_color_map[program_key] = PROGRAM_FILL_VARIANTS[index]
                used.add(PROGRAM_FILL_VARIANTS[index])
        item["fill_color"] = program_color_map[program_key]


def _build_program_color_map(payload: Dict[str, Any]) -> Dict[str, str]:
    program_color_map: Dict[str, str] = {}
    groups = payload["groups"]
    timeslots = sorted(payload["timeslots"], key=lambda t: t["sort_order"])
    weekday_order = sorted({(t["day_index"], t["weekday"]) for t in timeslots}, key=lambda d: d[0])
    timeslots_by_day = [ts for day_index, _ in weekday_order for ts in sorted([t for t in timeslots if t["day_index"] == day_index], key=lambda t: t["sort_order"])]

    for slot in timeslots_by_day:
        slot_items = payload["cells"].get(str(slot["id"]), {})
        overlay_rows_content: List[List[Dict[str, Any]]] = []
        for group in groups:
            items = _overlay_items(slot_items.get(str(group["id"]), []))
            deduped: List[Dict[str, Any]] = []
            for item in items:
                if not any(_same_overlay(item, d) for d in deduped):
                    deduped.append(item)
            overlay_rows_content.append(deduped)

        unique_overlays: List[Dict[str, Any]] = []
        for overlays in overlay_rows_content:
            for item in overlays:
                found = next((uo for uo in unique_overlays if _same_overlay_connectable(item, uo)), None)
                if found:
                    found["program_codes"] = sorted(set(found.get("program_codes", []) + item.get("program_codes", [])))
                    found["group_codes"] = sorted(set(found.get("group_codes", []) + item.get("group_codes", [])))
                    found["all_group"] = found.get("all_group", False) or item.get("all_group", False)
                elif not any(_same_overlay(item, uo) for uo in unique_overlays):
                    unique_overlays.append(
                        {
                            **item,
                            "program_codes": list(item.get("program_codes", [])),
                            "group_codes": list(item.get("group_codes", [])),
                            "all_group": item.get("all_group", False),
                        }
                    )

        kind_order = {"required": 0, "program": 1, "elective": 2}
        unique_overlays.sort(
            key=lambda item: (
                kind_order.get(str(item.get("kind") or ""), 3),
                item.get("course_name", ""),
                item.get("teacher_name", ""),
                item.get("room_name", ""),
            )
        )
        _assign_program_colors_for_slot(unique_overlays, program_color_map)

    return program_color_map


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
    cell.fill = PatternFill("solid", fgColor=_get_fill_color(item))
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.font = Font(bold=True, size=15)
    for c in range(start_col, end_col + 1):
        ws.cell(row=row_idx, column=c).border = border


def _write_group_timetable_sheet(
    ws: Worksheet,
    payload: Dict[str, Any],
    group: Dict[str, Any],
    blank_fill: PatternFill,
    border: Border,
    program_color_map: Dict[str, str],
) -> None:
    timeslots = sorted(payload["timeslots"], key=lambda t: t["sort_order"])
    group_id = group["id"]
    program_codes = [p["code"] for p in group.get("programs", []) if p.get("code")]
    title = f"Group {group['code']}"
    if program_codes:
        title += f" ({', '.join(program_codes)})"
    ws.title = _sanitize_sheet_title(title)

    time_labels: List[str] = []
    for timeslot in timeslots:
        if timeslot["label"] not in time_labels:
            time_labels.append(timeslot["label"])

    days = sorted({(t["day_index"], t["weekday"]) for t in timeslots}, key=lambda d: d[0])

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=1 + len(days))
    title_cell = _cell(ws, 1, 1, title)
    title_cell.font = Font(bold=True, size=15)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    header_cell = ws.cell(row=2, column=1, value="Time")
    header_cell.font = Font(bold=True, size=11)
    header_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    header_cell.border = border
    ws.column_dimensions["A"].width = float(18)

    for idx, (_day_index, weekday) in enumerate(days, start=2):
        cell = ws.cell(row=2, column=idx, value=weekday)
        cell.font = Font(bold=True, size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
        ws.column_dimensions[get_column_letter(idx)].width = float(26)

    elective_items: List[Dict[str, Any]] = []
    row = 3
    for label in time_labels:
        day_cells: Dict[int, List[Dict[str, Any]]] = {}
        for day_index, weekday in days:
            day_slots = [ts for ts in timeslots if ts["day_index"] == day_index and ts["label"] == label]
            if not day_slots:
                day_cells[day_index] = []
                continue
            timeslot = day_slots[0]
            slot_items = payload["cells"].get(str(timeslot["id"]), {}).get(str(group_id), [])
            expanded_items: List[Dict[str, Any]] = []
            for item in slot_items:
                if item.get("kind") == "elective":
                    elective_items.append({
                        "day": weekday,
                        "time": label,
                        "item": item,
                    })
                    continue
                expanded_items.append(item)
            day_cells[day_index] = expanded_items

        rows_for_label = max(max(len(items), 1) for items in day_cells.values())
        if rows_for_label > 1:
            ws.merge_cells(start_row=row, start_column=1, end_row=row + rows_for_label - 1, end_column=1)
        time_cell = _cell(ws, row, 1, label)
        time_cell.font = Font(bold=True)
        time_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        time_cell.border = border

        for row_offset in range(rows_for_label):
            current_row = row + row_offset
            if row_offset > 0:
                merged_time_cell = _cell(ws, current_row, 1, None)
                merged_time_cell.border = border
            row_height = _OVERLAY_MIN_HEIGHT
            for col_idx, (day_index, weekday) in enumerate(days, start=2):
                cell = _cell(ws, current_row, col_idx)
                cell.border = border
                items = day_cells.get(day_index, [])
                if row_offset >= len(items):
                    cell.fill = blank_fill
                    continue

                item = items[row_offset]
                if item.get("kind") == "program":
                    program_key = "|".join(sorted(item.get("program_codes", [])))
                    if program_key in program_color_map:
                        item["fill_color"] = program_color_map[program_key]
                text = _format_item(item)
                fill_color = _get_fill_color(item)
                cell.value = text
                cell.fill = PatternFill("solid", fgColor=fill_color)
                cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
                cell.font = Font(bold=True, size=12)
                needed_height = _row_height_for_text(text, width_cols=1, min_height=_OVERLAY_MIN_HEIGHT)
                row_height = max(row_height, needed_height)

            row_dimension = ws.row_dimensions[current_row]
            current_height = float(getattr(row_dimension, "height", 0) or 0)
            row_dimension.height = float(max(current_height, row_height))

        row += rows_for_label

    if elective_items:
        row += 1
        header_row = row
        ws.merge_cells(start_row=header_row, start_column=1, end_row=header_row, end_column=1 + len(days))
        header_cell = _cell(ws, header_row, 1, "Elective classes")
        header_cell.font = Font(bold=True, size=12)
        header_cell.alignment = Alignment(horizontal="left", vertical="center")
        row += 1

        ws.cell(row=row, column=1, value="Day").font = Font(bold=True)
        ws.cell(row=row, column=2, value="Time").font = Font(bold=True)
        ws.cell(row=row, column=3, value="Class details").font = Font(bold=True)
        ws.row_dimensions[row].height = 24
        row += 1

        for elective in elective_items:
            ws.cell(row=row, column=1, value=elective["day"]) .border = border
            ws.cell(row=row, column=2, value=elective["time"]) .border = border
            detail = _format_item(elective["item"])
            detail_cell = _cell(ws, row, 3, detail)
            detail_cell.alignment = Alignment(wrap_text=True, vertical="top")
            detail_cell.border = border
            detail_cell.font = Font(bold=True, size=12)
            ws.row_dimensions[row].height = _row_height_for_text(detail, width_cols=3, min_height=_OVERLAY_MIN_HEIGHT)
            row += 1


def _build_teacher_schedule_rows(
    db: Session,
    timetable_id: Optional[int],
    teacher_id: int,
    group_ids: Optional[List[int]] = None,
    study_program_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    query = select(ScheduledClass).options(
        joinedload(ScheduledClass.group),
        joinedload(ScheduledClass.timeslot),
        joinedload(ScheduledClass.room),
        joinedload(ScheduledClass.course),
        joinedload(ScheduledClass.study_program),
    ).where(
        ScheduledClass.deploy.is_(True),
        ScheduledClass.teacher_id == teacher_id,
    )
    if timetable_id is not None:
        query = query.join(Group).where(Group.timetable_id == timetable_id)
    if group_ids is not None:
        query = query.where(ScheduledClass.group_id.in_(group_ids))
    classes = db.execute(query).unique().scalars().all()

    grouped: Dict[Tuple[str, int, int, str, str, str], Dict[str, Set[str]]] = {}
    for cls in classes:
        if not cls.timeslot:
            continue
        key: Tuple[str, int, int, str, str, str] = (
            cls.timeslot.weekday,
            cls.timeslot.day_index,
            cls.timeslot.sort_order,
            cls.timeslot.label,
            cls.room.code if cls.room else "",
            cls.course.name if cls.course else "",
        )
        entry = grouped.setdefault(
            key,
            {
                "group_codes": set(),
                "program_codes": set(),
            },
        )
        if cls.group and cls.group.code:
            entry["group_codes"].add(cls.group.code)
        if cls.study_program and cls.study_program.code:
            entry["program_codes"].add(cls.study_program.code)

    rows: List[Dict[str, Any]] = []
    for key in sorted(grouped.keys(), key=lambda k: (k[1], k[2], k[3], k[0])):
        weekday, day_index, sort_order, timeslot_label, room_name, course_name = key
        entry = grouped[key]
        rows.append(
            {
                "weekday": weekday,
                "day_index": day_index,
                "sort_order": sort_order,
                "timeslot": timeslot_label,
                "group_code": ", ".join(sorted(entry["group_codes"])),
                "program_code": ", ".join(sorted(entry["program_codes"])),
                "room_name": room_name,
                "course_name": course_name,
            }
        )
    return rows


def _write_teacher_schedule_sheet(
    ws: Worksheet,
    teacher_name: str,
    rows: List[Dict[str, Any]],
    border: Border,
) -> None:
    ws.title = _sanitize_sheet_title(teacher_name)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    title_cell = _cell(ws, 1, 1, f"Teacher: {teacher_name}")
    title_cell.font = Font(bold=True, size=15)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    headers = ["Day", "Timeslot", "Group", "Program", "Room", "Course"]
    for idx, label in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=idx, value=label)
        cell.font = Font(bold=True, size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    ws.column_dimensions["A"].width = float(12)
    ws.column_dimensions["B"].width = float(18)
    ws.column_dimensions["C"].width = float(18)
    ws.column_dimensions["D"].width = float(18)
    ws.column_dimensions["E"].width = float(12)
    ws.column_dimensions["F"].width = float(26)

    if not rows:
        cell = _cell(ws, 3, 1, "No scheduled classes for this teacher.")
        cell.font = Font(italic=True)
        return

    for idx, row_info in enumerate(rows, start=3):
        ws.cell(row=idx, column=1, value=row_info["weekday"]).border = border
        ws.cell(row=idx, column=2, value=row_info["timeslot"]).border = border
        ws.cell(row=idx, column=3, value=row_info["group_code"]).border = border
        ws.cell(row=idx, column=4, value=row_info["program_code"]).border = border
        ws.cell(row=idx, column=5, value=row_info["room_name"]).border = border
        course_cell = ws.cell(row=idx, column=6, value=row_info["course_name"])
        course_cell.border = border
        course_cell.alignment = Alignment(wrap_text=True, horizontal="left", vertical="center")
        ws.row_dimensions[idx].height = 24


def _sanitize_sheet_title(title: str, max_length: int = 31) -> str:
    clean = re.sub(r"[\[\]\*:/\\\?']", "", title).strip()
    if not clean:
        return "Sheet"
    return clean[:max_length]


def _logo_path() -> Path:
    return Path(__file__).resolve().parent / "static" / "VGU-Logo.png"


def _insert_logo(ws: Worksheet) -> None:
    logo_file = _logo_path()
    if not logo_file.exists():
        return
    try:
        image = OpenpyxlImage(str(logo_file))
    except ImportError:
        return
    image.width = 120
    image.height = 40
    image.anchor = "A1"
    ws.add_image(image)


def _unique_sheet_titles(names: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    result: List[str] = []
    for name in names:
        title = _sanitize_sheet_title(name)
        if not title:
            title = "Sheet"
        candidate = title
        index = 1
        while candidate in seen:
            index += 1
            candidate = _sanitize_sheet_title(f"{title}-{index}")
            if len(candidate) > 31:
                candidate = candidate[:31]
        seen[candidate] = 1
        result.append(candidate)
    return result


def _write_timetable_sheet(
    db: Session,
    ws: Worksheet,
    payload: Dict[str, Any],
    timetable_id: Optional[int],
    study_program_ids: Optional[List[int]],
    group_ids: Optional[List[int]],
    teacher_ids: Optional[List[int]],
    selected_program_codes: List[str],
    title_fill: PatternFill,
    header_fill: PatternFill,
    lunch_fill: PatternFill,
    blank_fill: PatternFill,
    border: Border,
) -> None:
    ws.freeze_panes = "C5"
    ws.sheet_view.showGridLines = False

    groups = payload["groups"]
    timeslots = payload["timeslots"]
    cell_map = payload["cells"]
    program_color_map: Dict[str, str] = {}

    total_cols = 2 + len(groups)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    title_text = payload.get('cycle_name') or "Foundation Year 2025/26: Semester 2 - Phase 4"
    if selected_program_codes:
        title_text += f" - {', '.join(selected_program_codes)}"
    title_cell = _cell(ws, 1, 1, title_text)
    # title_cell.fill = title_fill
    title_cell.font = Font(bold=True, size=24)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
    subtitle_text = ""
    if selected_program_codes:
        subtitle_text += f" (Study programs: {', '.join(selected_program_codes)})"
    subtitle_cell = _cell(ws, 2, 1, subtitle_text)
    subtitle_cell.alignment = Alignment(horizontal="center")
    subtitle_cell.font = Font(italic=True)

    ws["A4"] = "Day"
    ws["B4"] = "Time"
    for cell in [ws["A4"], ws["B4"]]:
        cell.fill = header_fill
        cell.font = Font(bold=True, size=15)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for idx, group in enumerate(groups, start=3):
        program_codes = ", ".join([p["code"] for p in group.get("programs", [])])
        group_label = group["code"]
        if program_codes:
            group_label += f" ({program_codes})"
        cell = ws.cell(row=4, column=idx, value=group_label)
        cell.fill = header_fill
        cell.font = Font(bold=True, size=15)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
        ws.column_dimensions[get_column_letter(idx)].width = float(24)
    ws.row_dimensions[4].height = 72

    row = 5
    weekday_names = {1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY", 4: "THURSDAY", 5: "FRIDAY"}
    day_to_slots: Dict[str, List[Dict[str, Any]]] = {}
    for ts in timeslots:
        day_to_slots.setdefault(ts["weekday"], []).append(ts)

    for day_idx in range(1, 6):
        weekday = weekday_names[day_idx]
        day_slots: List[Dict[str, Any]] = sorted(day_to_slots.get(weekday, []), key=lambda item: item["sort_order"])
        day_start_row = row

        if day_slots and day_idx != 1:
            group_header_row = row
            for idx, group in enumerate(groups, start=3):
                program_codes = ", ".join([p["code"] for p in group.get("programs", [])])
                group_label = group["code"]
                if program_codes:
                    group_label += f" ({program_codes})"
                cell = ws.cell(row=group_header_row, column=idx, value=group_label)
                cell.fill = header_fill
                cell.font = Font(bold=True, size=15)
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = border
            ws.cell(row=group_header_row, column=2).border = border
            ws.row_dimensions[group_header_row].height = 72
            row += 1

        for slot in day_slots:
            slot_items = cell_map.get(str(slot["id"]), {})
            is_german_slot = str(slot.get("label", "")).startswith("German")
            if is_german_slot:
                slot_start_row = row
                required_row = row
                slot_end_row = row
                ws.merge_cells(start_row=slot_start_row, start_column=2, end_row=slot_end_row, end_column=2)
                time_cell = ws.cell(row=slot_start_row, column=2, value=slot["label"])
                time_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                time_cell.border = border

                row_height = _OVERLAY_MIN_HEIGHT
                for col_idx2, group in enumerate(groups, start=3):
                    items = slot_items.get(str(group["id"]), [])
                    cell = _cell(ws, required_row, col_idx2)
                    if not items:
                        cell.fill = blank_fill
                        cell.border = border
                        continue
                    text = "\n".join(_format_item(item) for item in items)
                    first_item = items[0]
                    cell.value = text
                    cell.fill = PatternFill("solid", fgColor=_get_fill_color(first_item))
                    cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
                    cell.font = Font(bold=True, size=15)
                    cell.border = border
                    needed_height = _row_height_for_text(text, width_cols=1, min_height=_OVERLAY_MIN_HEIGHT)
                    row_height = max(row_height, needed_height)
                ws.row_dimensions[required_row].height = row_height
                row += 1
                continue

            overlay_rows_content: List[List[Dict[str, Any]]] = []
            for group in groups:
                items = _overlay_items(slot_items.get(str(group["id"]), []))
                deduped: List[Dict[str, Any]] = []
                for item in items:
                    if not any(_same_overlay(item, d) for d in deduped):
                        deduped.append(item)
                overlay_rows_content.append(deduped)

            unique_overlays: List[Dict[str, Any]] = []
            for overlays in overlay_rows_content:
                for item in overlays:
                    found = next((uo for uo in unique_overlays if _same_overlay_connectable(item, uo)), None)
                    if found:
                        found["program_codes"] = sorted(set(found.get("program_codes", []) + item.get("program_codes", [])))
                        found["group_codes"] = sorted(set(found.get("group_codes", []) + item.get("group_codes", [])))
                        found["all_group"] = found.get("all_group", False) or item.get("all_group", False)
                    elif not any(_same_overlay(item, uo) for uo in unique_overlays):
                        unique_overlays.append(
                            {
                                **item,
                                "program_codes": list(item.get("program_codes", [])),
                                "group_codes": list(item.get("group_codes", [])),
                                "all_group": item.get("all_group", False),
                            }
                        )

            kind_order = {"required": 0, "program": 1, "elective": 2}
            unique_overlays.sort(
                key=lambda item: (
                    kind_order.get(str(item.get("kind") or ""), 3),
                    item.get("course_name", ""),
                    item.get("teacher_name", ""),
                    item.get("room_name", ""),
                )
            )
            _assign_program_colors_for_slot(unique_overlays, program_color_map)
            overlay_depth = len(unique_overlays)
            slot_start_row = row
            required_row = row
            overlay_rows = [required_row + i + 1 for i in range(overlay_depth)]
            slot_end_row = required_row + overlay_depth

            ws.merge_cells(start_row=slot_start_row, start_column=2, end_row=slot_end_row, end_column=2)
            time_cell = ws.cell(row=slot_start_row, column=2, value=slot["label"])
            time_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            time_cell.border = border

            required_row_height = REQUIRED_ROW_HEIGHT
            ws.row_dimensions[required_row].height = required_row_height

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
                    req_height = _row_height_for_text(
                        _format_item(req),
                        width_cols=end_col - col_idx + 1,
                        min_height=REQUIRED_ROW_HEIGHT,
                    )
                    required_row_height = max(required_row_height, req_height)
                    col_idx = end_col + 1
                else:
                    req_cell = _cell(ws, required_row, col_idx)
                    req_cell.value = _format_item(req)
                    req_cell.fill = PatternFill("solid", fgColor=FILL_MAP.get(req["color_key"], "D9D2E9"))
                    req_cell.border = border
                    req_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    req_cell.font = Font(bold=True, size=15)
                    req_height = _row_height_for_text(
                        _format_item(req),
                        width_cols=1,
                        min_height=REQUIRED_ROW_HEIGHT,
                    )
                    required_row_height = max(required_row_height, req_height)
                    col_idx += 1
            ws.row_dimensions[required_row].height = required_row_height

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
                    cell.font = Font(bold=True, size=15)

            for overlay_idx, overlay_item in enumerate(unique_overlays):
                overlay_row = required_row + 1 + overlay_idx
                row_has_overlay = [any(_same_overlay(item, overlay_item) for item in group_items) for group_items in overlay_rows_content]
                present_cols = [3 + idx for idx, has in enumerate(row_has_overlay) if has]
                # Compute height based on each contiguous merged segment, not on total present columns.
                needed_height = _OVERLAY_MIN_HEIGHT
                segment_width = 0
                for has in row_has_overlay + [False]:
                    if has:
                        segment_width += 1
                        continue
                    if segment_width:
                        segment_height = _row_height_for_text(
                            _format_item(overlay_item),
                            width_cols=segment_width,
                            min_height=_OVERLAY_MIN_HEIGHT,
                        )
                        needed_height = max(needed_height, segment_height)
                        segment_width = 0
                row_dimension: RowDimension = ws.row_dimensions[overlay_row]
                current_height = float(getattr(row_dimension, "height", 0) or 0)
                setattr(row_dimension, "height", float(max(current_height, needed_height)))
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

            for overlay_idx, overlay_item in enumerate(unique_overlays):
                overlay_row = required_row + 1 + overlay_idx
                for col_idx2, group in enumerate(groups, start=3):
                    group_items = overlay_rows_content[col_idx2 - 3]
                    if not any(_same_overlay(item, overlay_item) for item in group_items):
                        cell = _cell(ws, overlay_row, col_idx2)
                        cell.fill = blank_fill
                        cell.border = border

            for rr in range(slot_start_row, slot_end_row + 1):
                ws.cell(row=rr, column=2).border = border

            row = slot_end_row + 1

            if slot.get("end") == "12.00":
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
        day_separator_border = Border(
            left=Side(style="thin", color="000000"),
            right=Side(style="thin", color="000000"),
            top=Side(style="thin", color="000000"),
            bottom=Side(style="medium", color="000000"),
        )
        for c in range(1, total_cols + 1):
            cell = _cell(ws, day_end_row, c)
            cell.border = day_separator_border
        ws.merge_cells(start_row=day_start_row, start_column=1, end_row=day_end_row, end_column=1)
        dcell = ws.cell(row=day_start_row, column=1, value=weekday)
        dcell.alignment = Alignment(horizontal="center", vertical="center", text_rotation=90)
        dcell.font = Font(bold=True)
        dcell.fill = PatternFill("solid", fgColor="E2EFDA")
        dcell.border = border
        for rr in range(day_start_row, day_end_row + 1):
            ws.cell(row=rr, column=1).border = border

    timetable_end_row = row - 1
    last_group_col = 2 + len(groups)
    max_col = ws.max_column
    white_fill = PatternFill("solid", fgColor="FFFFFF")
    for r in range(5, timetable_end_row + 1):
        for c in range(last_group_col + 1, max_col + 1):
            cell = _cell(ws, r, c)
            cell.value = None
            cell.fill = white_fill
            cell.border = Border()

    start_teacher = row + 2
    ws.cell(row=start_teacher, column=1, value="Teacher load summary").font = Font(bold=True, size=12)
    ws.cell(row=start_teacher + 1, column=1, value="Teacher").font = Font(bold=True)
    ws.cell(row=start_teacher + 1, column=2, value="Taught timeslots").font = Font(bold=True)
    for idx, item in enumerate(teacher_load_rows(db, timetable_id, study_program_ids, group_ids=group_ids, teacher_ids=teacher_ids), start=start_teacher + 2):
        ws.cell(row=idx, column=1, value=item["teacher"])
        ws.cell(row=idx, column=2, value=item["timeslot_count"])

    ws.column_dimensions["A"].width = float(10)
    ws.column_dimensions["B"].width = float(16)


def export_timetable_xlsx(
    db: Session,
    output_path: str | Path,
    timetable_id: Optional[int] = None,
    study_program_ids: Optional[List[int]] = None,
    group_ids: Optional[List[int]] = None,
    teacher_ids: Optional[List[int]] = None,
) -> Path:
    output_path = Path(output_path)
    title_fill = PatternFill("solid", fgColor="1F4E78")
    header_fill = PatternFill("solid", fgColor="D9E2F3")
    lunch_fill = PatternFill("solid", fgColor="F2F2F2")
    blank_fill = PatternFill("solid", fgColor=BLANK_FILL)
    thin_gray = Side(style="thin", color="444444")
    border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)

    selected_program_codes: List[str] = []
    if study_program_ids is not None:
        selected_program_codes = [str(prog.code) for prog in db.scalars(select(StudyProgram).where(StudyProgram.id.in_(study_program_ids))).all()]

    wb = Workbook()
    ws = cast(Worksheet, wb.active)
    payload = build_timetable_payload(
        db,
        timetable_id,
        study_program_ids=study_program_ids,
        group_ids=group_ids,
        teacher_ids=teacher_ids,
    )

    if teacher_ids is not None:
        from .models import Teacher
        teacher_query = select(Teacher).where(Teacher.id.in_(teacher_ids)).order_by(Teacher.name)
        if timetable_id is not None:
            teacher_query = (
                teacher_query.join(ScheduledClass, ScheduledClass.teacher_id == Teacher.id)
                .join(Group, Group.id == ScheduledClass.group_id)
                .where(ScheduledClass.deploy.is_(True), Group.timetable_id == timetable_id)
                .distinct()
            )
        teacher_sheets = list(db.scalars(teacher_query).all())
        sheet_titles = _unique_sheet_titles([str(t.name or t.id) for t in teacher_sheets])
        for idx, (teacher, sheet_title) in enumerate(zip(teacher_sheets, sheet_titles)):
            if idx == 0:
                ws.title = sheet_title
            else:
                ws = wb.create_sheet(title=sheet_title)
            rows = _build_teacher_schedule_rows(db, timetable_id, cast(int, getattr(teacher, 'id')))
            _write_teacher_schedule_sheet(ws, str(teacher.name), rows, border)
            _insert_logo(ws)
        wb.save(output_path)
        return output_path

    if group_ids is not None:
        group_sheets = payload["groups"]
        program_color_map = _build_program_color_map(payload)
        sheet_titles = _unique_sheet_titles([str(group["code"]) for group in group_sheets])
        for idx, (group, sheet_title) in enumerate(zip(group_sheets, sheet_titles)):
            if idx == 0:
                ws.title = sheet_title
            else:
                ws = wb.create_sheet(title=sheet_title)
            _write_group_timetable_sheet(ws, payload, group, blank_fill, border, program_color_map)
            _insert_logo(ws)
        wb.save(output_path)
        return output_path

    ws.title = "Phase4 Timetable"
    _write_timetable_sheet(
        db,
        ws,
        payload,
        timetable_id,
        study_program_ids,
        group_ids,
        teacher_ids,
        selected_program_codes,
        title_fill,
        header_fill,
        lunch_fill,
        blank_fill,
        border,
    )
    _insert_logo(ws)

    filtered_export = study_program_ids is not None or group_ids is not None or teacher_ids is not None
    program_sheets: List[StudyProgram] = []
    if not filtered_export:
        program_sheets = list(
            db.scalars(
                select(StudyProgram)
                .join(GroupStudyProgram)
                .join(Group)
                .where(Group.timetable_id == timetable_id)
                .distinct()
            ).all()
        ) if timetable_id is not None else list(db.scalars(select(StudyProgram)).all())

    if program_sheets:
        sheet_titles = _unique_sheet_titles([str(prog.code) for prog in program_sheets])
        for prog, sheet_title in zip(program_sheets, sheet_titles):
            if sheet_title == ws.title:
                sheet_title = _sanitize_sheet_title(f"{sheet_title}-1")
            program_ws = wb.create_sheet(title=sheet_title)
            prog_id = cast(int, prog.id)
            prog_payload = build_timetable_payload(db, timetable_id, study_program_ids=[prog_id])
            _write_timetable_sheet(
                db,
                program_ws,
                prog_payload,
                timetable_id,
                [prog_id],
                None,
                None,
                [str(prog.code)],
                title_fill,
                header_fill,
                lunch_fill,
                blank_fill,
                border,
            )
            _insert_logo(program_ws)

    wb.save(output_path)
    return output_path