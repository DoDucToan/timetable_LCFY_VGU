from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, cast
from uuid import uuid4
import re

from sqlalchemy import func, or_, select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.orm import Session, joinedload

from .models import Cycle, Course, Group, GroupStudyProgram, ScheduledClass, StudyProgram, Timetable, Timeslot


MODE_REQUIRED = "required_all"
MODE_PROGRAM = "program"
MODE_ELECTIVE = "elective"


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    replacements = {
        'â€”': '—',
        'â€“': '–',
        'â€œ': '“',
        'â€�': '”',
        'â€™': '’',
        'Ã©': 'é',
        'Ã ': 'à',
        'Ã¨': 'è',
        'Ãª': 'ê',
        'Ã§': 'ç',
        'Ã±': 'ñ',
        'Ã´': 'ô',
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    if any(seq in text for seq in replacements.keys()):
        try:
            text = text.encode('latin1').decode('utf-8')
        except Exception:
            pass
    return text


def estimate_program_size(group: Group, selected_program_count: int) -> int:
    total_programs = max(len(group.study_program_links), 1)
    selected_program_count = max(selected_program_count, 1)
    size_num = int(cast(int, group.size_num) or 0)
    return max(1, round(size_num * selected_program_count / total_programs))


def _normalize_hex_color(color: str) -> Optional[str]:
    color_text = str(color).strip()
    if color_text.startswith('#'):
        color_text = color_text[1:]
    if len(color_text) == 3:
        color_text = ''.join(ch * 2 for ch in color_text)
    color_text = color_text.upper()
    if re.fullmatch(r'[0-9A-F]{6}', color_text):
        return f'#{color_text}'
    return None


def _stable_hash(value: str) -> int:
    hash_value = 2166136261
    for ch in value:
        hash_value ^= ord(ch)
        hash_value *= 16777619
        hash_value &= 0xFFFFFFFF
    return hash_value


def _blend_hex_colors(colors: List[str]) -> str:
    normalized: List[str] = []
    for color in colors:
        hex_color = _normalize_hex_color(color)
        if hex_color:
            normalized.append(hex_color[1:])
    if not normalized:
        return PROGRAM_FILL_VARIANTS[0]
    rgb_totals = [0, 0, 0]
    for hex_color in normalized:
        rgb_totals[0] += int(hex_color[0:2], 16)
        rgb_totals[1] += int(hex_color[2:4], 16)
        rgb_totals[2] += int(hex_color[4:6], 16)
    count = len(normalized)
    blended = ''.join(f'{round(rgb_totals[i] / count):02X}' for i in range(3))
    return f'#{blended}'


def validate_new_class(
    db: Session,
    *,
    target_group_ids: List[int],
    timeslot_id: int,
    course: Course,
    teacher_id: Optional[int],
    room_id: Optional[int],
    mode: str,
    study_program_ids: List[int],
    expected_size: Optional[int],
    self_study: bool = False,
    allow_teacher_conflict: bool = False,
) -> List[str]:
    errors: List[str] = []
    groups = db.execute(
        select(Group)
        .where(Group.id.in_(target_group_ids))
        .options(joinedload(Group.study_program_links).joinedload(GroupStudyProgram.study_program))
    ).unique().scalars().all()
    group_map: Dict[int, Group] = {cast(int, g.id): g for g in groups}
    current_timetable_id = cast(int, groups[0].timetable_id) if groups else None

    if len(groups) != len(set(target_group_ids)):
        errors.append("One or more selected groups do not exist.")
        return errors

    if mode == MODE_REQUIRED and len(target_group_ids) > 1:
        errors.append("Require-all-students classes must be added to one group at a time.")

    effective_mode = MODE_ELECTIVE if mode == MODE_REQUIRED and self_study else mode

    if mode == MODE_REQUIRED and allow_teacher_conflict:
        errors.append("Teacher conflict is not allowed for require-all classes.")

    if teacher_id is not None:
        if not allow_teacher_conflict:
            teacher_clash = db.scalar(
                select(ScheduledClass.id)
                .join(Group, Group.id == ScheduledClass.group_id)
                .where(
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.timeslot_id == timeslot_id,
                    ScheduledClass.teacher_id == teacher_id,
                    Group.timetable_id == current_timetable_id,
                )
                .limit(1)
            )
            if teacher_clash is not None:
                errors.append("Teacher is already assigned in this timeslot.")
        else:
            # For study program class, allow teacher conflict only if all rooms are the same
            assigned_rooms_result = db.execute(
                select(ScheduledClass.room_id)
                .join(Group, Group.id == ScheduledClass.group_id)
                .where(
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.timeslot_id == timeslot_id,
                    ScheduledClass.teacher_id == teacher_id,
                    Group.timetable_id == current_timetable_id,
                )
            )
            assigned_rooms: List[Optional[int]] = cast(List[Optional[int]], cast(ScalarResult[Optional[int]], assigned_rooms_result.scalars()).all())
            # Only consider non-null rooms
            assigned_rooms = [rid for rid in assigned_rooms if rid is not None]
            if assigned_rooms:
                # If any assigned room is different from the current room, error
                if any(rid != room_id for rid in assigned_rooms):
                    errors.append("Teacher cannot teach in multiple rooms at the same time.")

    if room_id is not None:
        room_clash = db.scalar(
            select(ScheduledClass.id)
            .join(Group, Group.id == ScheduledClass.group_id)
            .where(
                ScheduledClass.deploy.is_(True),
                ScheduledClass.timeslot_id == timeslot_id,
                ScheduledClass.room_id == room_id,
                Group.timetable_id == current_timetable_id,
            )
            .limit(1)
        )
        if room_clash is not None:
            errors.append("Room is already occupied in this timeslot.")

    if room_id is not None:
        from .models import Room
        room = db.get(Room, room_id)
        if room:
            room_capacity = int(cast(int, room.capacity_num) or 0)
            if expected_size is not None and room_capacity < expected_size:
                errors.append(f"Room capacity ({room.capacity_num}) is smaller than expected class size ({expected_size}).")
            elif expected_size is None:
                if mode == MODE_REQUIRED:
                    needed = sum(int(cast(int, group_map[g].size_num) or 0) for g in target_group_ids if g in group_map)
                else:
                    needed = sum(estimate_program_size(group_map[g], max(len(study_program_ids), 1)) for g in target_group_ids if g in group_map)
                if room_capacity < needed:
                    errors.append(f"Room capacity ({room.capacity_num}) is smaller than estimated needed size ({needed}).")

    if effective_mode == MODE_PROGRAM and not study_program_ids:
        errors.append("At least one study program must be selected for a study-program class.")

    if effective_mode == MODE_REQUIRED and len(target_group_ids) > 1:
        errors.append("Require-all-students classes must be added to one group at a time.")

    # student/group clashes
    for group_id in target_group_ids:
        group = group_map[group_id]
        group_program_ids: set[Optional[int]] = {
            cast(Optional[int], link.study_program_id)
            for link in group.study_program_links
        }

        if mode == MODE_ELECTIVE:
            continue

        existing: List[ScheduledClass] = list(db.scalars(
            select(ScheduledClass)
            .where(
                ScheduledClass.deploy.is_(True),
                ScheduledClass.group_id == group_id,
                ScheduledClass.timeslot_id == timeslot_id,
            )
        ).all())

        if effective_mode == MODE_REQUIRED:
            blocking = [cls for cls in existing if not cls.course.elective]
            if blocking:
                errors.append(f"Group {group.code} already has a non-elective class in this timeslot.")
                continue

        if effective_mode == MODE_PROGRAM:
            if not any(pid in group_program_ids for pid in study_program_ids):
                errors.append(f"Group {group.code} does not contain any selected study programs.")
                continue

            if any((cast(Optional[int], cls.study_program_id) is None and not cast(bool, cls.course.elective)) for cls in existing):
                errors.append(f"Group {group.code} already has a require-all-students class in this timeslot.")
                continue

            if not allow_teacher_conflict:
                for pid in study_program_ids:
                    if any(cls.study_program_id == pid and not cls.course.elective for cls in existing):
                        program = db.get(StudyProgram, pid)
                        code = program.code if program else str(pid)
                        errors.append(f"Program {code} in group {group.code} already has a class in this timeslot.")

    return errors


def create_classes(
    db: Session,
    *,
    target_group_ids: List[int],
    timeslot_id: int,
    course: Course,
    teacher_id: Optional[int],
    room_id: Optional[int],
    mode: str,
    study_program_ids: List[int],
    expected_size: Optional[int],
    self_study: bool = False,
    notes: Optional[str],
    source: str = "ui",
    allow_teacher_conflict: bool = False,
) -> Tuple[List[ScheduledClass], List[str]]:
    errors = validate_new_class(
        db,
        target_group_ids=target_group_ids,
        timeslot_id=timeslot_id,
        course=course,
        teacher_id=teacher_id,
        room_id=room_id,
        mode=mode,
        study_program_ids=study_program_ids,
        expected_size=expected_size,
        self_study=self_study,
        allow_teacher_conflict=allow_teacher_conflict,
    )
    if errors:
        return [], errors

    effective_mode = MODE_ELECTIVE if mode == MODE_REQUIRED and self_study else mode
    shared_key = str(uuid4()) if len(target_group_ids) > 1 or len(study_program_ids) > 1 else None
    created: List[ScheduledClass] = []

    if effective_mode == MODE_REQUIRED:
        for group_id in target_group_ids:
            created.append(
                ScheduledClass(
                    group_id=group_id,
                    timeslot_id=timeslot_id,
                    room_id=room_id,
                    teacher_id=teacher_id,
                    course_id=course.id,
                    study_program_id=None,
                    deploy=True,
                    shared_key=shared_key,
                    expected_size=expected_size,
                    notes=notes,
                    source=source,
                )
            )
    elif effective_mode == MODE_PROGRAM:
        for group_id in target_group_ids:
            for study_program_id in study_program_ids:
                created.append(
                    ScheduledClass(
                        group_id=group_id,
                        timeslot_id=timeslot_id,
                        room_id=room_id,
                        teacher_id=teacher_id,
                        course_id=course.id,
                        study_program_id=study_program_id,
                        deploy=True,
                        shared_key=shared_key,
                        expected_size=expected_size,
                        notes=notes,
                        source=source,
                    )
                )
    else:  # elective
        for group_id in target_group_ids:
            created.append(
                ScheduledClass(
                    group_id=group_id,
                    timeslot_id=timeslot_id,
                    room_id=room_id,
                    teacher_id=teacher_id,
                    course_id=course.id,
                    study_program_id=None,
                    deploy=True,
                    shared_key=shared_key,
                    expected_size=expected_size,
                    notes=notes,
                    source=source,
                )
            )

    db.add_all(created)
    db.flush()
    return created, []


FILL_MAP = {
    "ielts": "9FC5E8",
    "german": "F9CB9C",
    "ae": "EAD1DC",
    "core": "F4B183",
    "shared": "D99A9A",
    "elective": "C49A00",
    "other": "D9D2E9",
}

COLOR_MAP = {
    "IELTS": "ielts",
    "German": "german",
    "AE": "ae",
    "EAP": "ae",
    "Elective": "elective",
    "Business": "core",
    "Science": "shared",
    "CSE": "other",
    "ARC": "shared",
    "Other": "other",
}

PROGRAM_FILL_VARIANTS = [
    "FFF2CC",
    "E8F0D9",
    "D9E8F8",
    "F9E2E6",
    "EDE7F5",
    "F7EED9",
    "E8F2E8",
    "F8E7F2",
    "DFF0EB",
    "FAE9D3",
    "E9E8F3",
    "F3F0E8",
    "DDE8F0",
    "F8ECEA",
    "E9F1EF",
    "F8F2DA",
    "EDE9EC",
    "DDE9E4",
    "FDF3D8",
    "E8E8F0",
]


def build_timetable_payload(
    db: Session,
    timetable_id: Optional[int] = None,
    study_program_ids: Optional[List[int]] = None,
    group_ids: Optional[List[int]] = None,
    teacher_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    group_query = select(Group).options(
        joinedload(Group.group_tag),
        joinedload(Group.study_program_links).joinedload(GroupStudyProgram.study_program),
    )
    if timetable_id is not None:
        group_query = group_query.where(Group.timetable_id == timetable_id)
    if group_ids is not None:
        group_query = group_query.where(Group.id.in_(group_ids))
    elif teacher_ids is not None and timetable_id is not None:
        group_ids = [
            int(gid)
            for gid in db.scalars(
                select(Group.id)
                .join(ScheduledClass, ScheduledClass.group_id == Group.id)
                .where(
                    Group.timetable_id == timetable_id,
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.teacher_id.in_(teacher_ids),
                )
                .distinct()
            ).all()
        ]
        if group_ids:
            group_query = group_query.where(Group.id.in_(group_ids))
    if study_program_ids is not None:
        group_query = group_query.join(GroupStudyProgram).where(GroupStudyProgram.study_program_id.in_(study_program_ids)).distinct()
    groups = db.execute(group_query.order_by(Group.sort_order)).unique().scalars().all()
    group_map: Dict[int, Group] = {cast(int, g.id): g for g in groups}
    timetable = None
    cycle = None
    if timetable_id is not None:
        timetable = db.get(Timetable, timetable_id)
        german_cycle = False
        if timetable is not None:
            cycle = getattr(timetable, 'cycle', None) or db.get(Cycle, timetable.cycle_id)
            german_cycle = bool(getattr(cycle, 'german_timeslots', False))
        if german_cycle:
            timeslots = db.scalars(select(Timeslot).where(Timeslot.label.like('German%')).order_by(Timeslot.sort_order)).all()
        else:
            timeslots = db.scalars(select(Timeslot).where(~Timeslot.label.like('German%')).order_by(Timeslot.sort_order)).all()
    else:
        timeslots = db.scalars(select(Timeslot).order_by(Timeslot.sort_order)).all()
    class_ids_filter: Optional[List[int]] = None
    if study_program_ids is not None:
        class_ids_filter = [cast(int, group.id) for group in groups]

    class_query = select(ScheduledClass).options(
        joinedload(ScheduledClass.course).joinedload(Course.course_tag),
        joinedload(ScheduledClass.group),
        joinedload(ScheduledClass.teacher),
        joinedload(ScheduledClass.room),
        joinedload(ScheduledClass.study_program),
        joinedload(ScheduledClass.timeslot),
    ).where(ScheduledClass.deploy.is_(True))
    if timetable_id is not None:
        class_query = class_query.join(Group).where(Group.timetable_id == timetable_id)
    if teacher_ids is not None:
        class_query = class_query.where(ScheduledClass.teacher_id.in_(teacher_ids))
    if class_ids_filter is not None:
        study_program_ids_list: List[int] = cast(List[int], study_program_ids)
        class_query = class_query.join(Course, ScheduledClass.course).where(
            ScheduledClass.group_id.in_(class_ids_filter),
            or_(
                Course.require_all_student_in_group.is_(True),
                Course.elective.is_(True),
                ScheduledClass.study_program_id.in_(study_program_ids_list),
            ),
        )
    classes: List[ScheduledClass] = cast(List[ScheduledClass], db.execute(class_query).unique().scalars().all())

    cell_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    grouped: Dict[tuple[int | str | None, ...], List[ScheduledClass]] = defaultdict(list)
    for cls in classes:
        shared_key = cast(Optional[str], cls.shared_key)
        if shared_key is not None:
            key = (
                cast(int, cls.timeslot_id),
                cast(int, cls.group_id),
                cast(int, cls.course_id),
                shared_key,
            )
        else:
            kind = "elective" if cast(bool, cls.course.elective) else ("required" if cast(bool, cls.course.require_all_student_in_group) else "program")
            notes_value = getattr(cls, "notes")
            notes = str(notes_value) if notes_value is not None else ""
            teacher_id_value = getattr(cls, "teacher_id")
            room_id_value = getattr(cls, "room_id")
            key = (
                cast(int, cls.timeslot_id),
                cast(int, cls.group_id),
                cast(int, cls.course_id),
                kind,
                int(teacher_id_value) if teacher_id_value is not None else None,
                int(room_id_value) if room_id_value is not None else None,
                notes,
            )
        grouped[key].append(cls)

    for key, bundle in grouped.items():
        group_id = cast(int, key[1])
        first = bundle[0]
        programs = sorted({cls.study_program.code for cls in bundle if cls.study_program})
        kind = "elective" if first.course.elective else ("required" if first.course.require_all_student_in_group else "program")
        if kind == "elective":
            color_key = "elective"
            fill_color = FILL_MAP["elective"]
        else:
            color_key = COLOR_MAP.get(first.course.course_tag.name, "other")
            fill_color = FILL_MAP.get(color_key, "D9D2E9")
            if first.course.course_tag and getattr(first.course.course_tag, 'fill_color', None):
                fill_color = first.course.course_tag.fill_color
        if kind == "program":
            program_key = "|".join(programs) if programs else first.course.course_tag.name
            if programs:
                program_colors: List[str] = []
                has_custom_program_color = False
                for program_code in programs:
                    program_color = next(
                        (
                            cls.study_program.fill_color
                            for cls in bundle
                            if cls.study_program
                            and _sanitize_text(cls.study_program.code) == program_code
                            and getattr(cls.study_program, 'fill_color', None)
                        ),
                        None,
                    )
                    if program_color:
                        has_custom_program_color = True
                    else:
                        program_color = PROGRAM_FILL_VARIANTS[_stable_hash(program_code) % len(PROGRAM_FILL_VARIANTS)]
                    program_colors.append(program_color)
                if has_custom_program_color:
                    fill_color = _blend_hex_colors(program_colors) if len(program_colors) > 1 else program_colors[0]
                elif first.course.course_tag and getattr(first.course.course_tag, 'fill_color', None):
                    fill_color = first.course.course_tag.fill_color
                else:
                    fill_color = PROGRAM_FILL_VARIANTS[_stable_hash(program_key) % len(PROGRAM_FILL_VARIANTS)]
            else:
                if first.course.course_tag and getattr(first.course.course_tag, 'fill_color', None):
                    fill_color = first.course.course_tag.fill_color
                else:
                    fill_color = PROGRAM_FILL_VARIANTS[_stable_hash(program_key) % len(PROGRAM_FILL_VARIANTS)]
        group_codes = [_sanitize_text(group_map[group_id].code)] if group_id in group_map else []
        all_group = False
        if kind == "program" and group_codes and programs:
            group_codes_set = set(group_codes)
            all_group = True
            for program_code in programs:
                normalized_code = _sanitize_text(program_code)
                groups_for_program = {
                    _sanitize_text(link.study_program.code)
                    for g in groups
                    for link in g.study_program_links
                    if _sanitize_text(link.study_program.code) == normalized_code
                }
                if groups_for_program and not groups_for_program.issubset(group_codes_set):
                    all_group = False
                    break
        group_tag_code = ""
        if group_id in group_map and group_map[group_id].group_tag:
            group_tag_code = _sanitize_text(group_map[group_id].group_tag.code)
        item: Dict[str, Any] = {
            "id": min(cls.id for cls in bundle),
            "course_code": _sanitize_text(first.course.code),
            "course_name": _sanitize_text(first.course.name),
            "teacher_name": _sanitize_text(first.teacher.name if first.teacher else ""),
            "room_name": _sanitize_text(first.room.code if first.room else ""),
            "program_codes": [_sanitize_text(code) for code in programs],
            "group_codes": group_codes,
            "group_tag_code": group_tag_code,
            "all_group": all_group,
            "notes": _sanitize_text(first.notes or ""),
            "kind": kind,
            "color_key": color_key,
            "fill_color": fill_color,
            "shared": bool(first.shared_key),
            "expected_size": first.expected_size,
        }
        cell_map[str(cast(int, first.timeslot_id))][str(group_id)].append(item)

    # sort display order within each cell
    sort_rank = {"required": 0, "program": 1, "elective": 2}
    for tmap in cell_map.values():
        for items in tmap.values():
            items.sort(key=lambda item: (sort_rank[item["kind"]], item["course_name"]))

    return {
        "cycle_name": getattr(cycle, 'name', '') if timetable_id is not None and timetable is not None and cycle is not None else '',
        "groups": [
            {
                "id": g.id,
                "code": _sanitize_text(g.code),
                "name": _sanitize_text(g.name),
                "capacity": g.size_num,
                "group_tag": {
                    "id": g.group_tag.id,
                    "code": _sanitize_text(g.group_tag.code),
                    "name": _sanitize_text(g.group_tag.name),
                },
                "programs": [
                    {
                        "id": link.study_program.id,
                        "code": _sanitize_text(link.study_program.code),
                        "name": _sanitize_text(link.study_program.name),
                    }
                    for link in sorted(g.study_program_links, key=lambda x: x.study_program.code)
                ],
            }
            for g in groups
        ],
        "timeslots": [
            {
                "id": t.id,
                "weekday": t.weekday,
                "label": t.label,
                "sort_order": t.sort_order,
                "day_index": t.day_index,
                "start": t.start_time,
                "end": t.end_time,
            }
            for t in timeslots
        ],
        "cells": cell_map,
    }


def teacher_load_rows(
    db: Session,
    timetable_id: Optional[int] = None,
    study_program_ids: Optional[List[int]] = None,
    group_ids: Optional[List[int]] = None,
    teacher_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    query = select(
        ScheduledClass.teacher_id,
        func.count(func.distinct(ScheduledClass.timeslot_id)).label("timeslot_count"),
    ).where(
        ScheduledClass.deploy.is_(True),
        ScheduledClass.teacher_id.is_not(None),
    )
    if timetable_id is not None:
        query = query.join(Group).where(Group.timetable_id == timetable_id)
    if group_ids is not None:
        query = query.where(ScheduledClass.group_id.in_(group_ids))
    if teacher_ids is not None:
        query = query.where(ScheduledClass.teacher_id.in_(teacher_ids))
    if study_program_ids is not None:
        study_program_ids_list: List[int] = study_program_ids
        query = query.join(GroupStudyProgram, GroupStudyProgram.group_id == ScheduledClass.group_id).where(
            GroupStudyProgram.study_program_id.in_(study_program_ids_list),
            or_(
                ScheduledClass.study_program_id.is_(None),
                ScheduledClass.study_program_id.in_(study_program_ids_list),
            ),
        )
    raw_rows = db.execute(query.group_by(ScheduledClass.teacher_id).order_by(func.count(func.distinct(ScheduledClass.timeslot_id)).desc())).all()
    rows: List[tuple[int, int]] = [(int(row[0]), int(row[1])) for row in raw_rows]
    result: List[Dict[str, Any]] = []
    from .models import Teacher
    for teacher_id, count in rows:
        teacher = db.get(Teacher, teacher_id)
        result.append({"teacher": teacher.name if teacher else str(teacher_id), "timeslot_count": int(count)})
    return result
