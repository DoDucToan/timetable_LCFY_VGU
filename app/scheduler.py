from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .models import Course, Group, GroupStudyProgram, ScheduledClass, StudyProgram, Timeslot


MODE_REQUIRED = "required_all"
MODE_PROGRAM = "program"
MODE_ELECTIVE = "elective"


def estimate_program_size(group: Group, selected_program_count: int) -> int:
    total_programs = max(len(group.study_program_links), 1)
    selected_program_count = max(selected_program_count, 1)
    return max(1, round(group.size_num * selected_program_count / total_programs))


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
    allow_teacher_conflict: bool = False,
) -> List[str]:
    errors: List[str] = []
    groups = db.execute(
        select(Group)
        .where(Group.id.in_(target_group_ids))
        .options(joinedload(Group.study_program_links).joinedload(GroupStudyProgram.study_program))
    ).unique().scalars().all()
    group_map = {g.id: g for g in groups}

    if len(groups) != len(set(target_group_ids)):
        errors.append("One or more selected groups do not exist.")
        return errors


    if teacher_id:
        if not allow_teacher_conflict:
            teacher_clash = db.scalar(
                select(ScheduledClass.id).where(
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.timeslot_id == timeslot_id,
                    ScheduledClass.teacher_id == teacher_id,
                ).limit(1)
            )
            if teacher_clash:
                errors.append("Teacher is already assigned in this timeslot.")
        else:
            # For study program class, allow teacher conflict only if all rooms are the same
            assigned_rooms = db.execute(
                select(ScheduledClass.room_id)
                .where(
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.timeslot_id == timeslot_id,
                    ScheduledClass.teacher_id == teacher_id,
                )
            ).scalars().all()
            # Only consider non-null rooms
            assigned_rooms = [rid for rid in assigned_rooms if rid is not None]
            if assigned_rooms:
                # If any assigned room is different from the current room, error
                if any(rid != room_id for rid in assigned_rooms):
                    errors.append("Teacher cannot teach in multiple rooms at the same time.")

    if room_id and not allow_teacher_conflict:
        room_clash = db.scalar(
            select(ScheduledClass.id).where(
                ScheduledClass.deploy.is_(True),
                ScheduledClass.timeslot_id == timeslot_id,
                ScheduledClass.room_id == room_id,
            ).limit(1)
        )
        if room_clash:
            errors.append("Room is already occupied in this timeslot.")

    if room_id:
        from .models import Room
        room = db.get(Room, room_id)
        if room:
            if expected_size and room.capacity_num < expected_size:
                errors.append(f"Room capacity ({room.capacity_num}) is smaller than expected class size ({expected_size}).")
            elif expected_size is None:
                if mode == MODE_REQUIRED:
                    needed = sum(group_map[g].size_num for g in target_group_ids if g in group_map)
                else:
                    needed = sum(estimate_program_size(group_map[g], max(len(study_program_ids), 1)) for g in target_group_ids if g in group_map)
                if room.capacity_num < needed:
                    errors.append(f"Room capacity ({room.capacity_num}) is smaller than estimated needed size ({needed}).")

    if mode == MODE_PROGRAM and not study_program_ids:
        errors.append("At least one study program must be selected for a study-program class.")

    if mode == MODE_REQUIRED and len(target_group_ids) > 1:
        errors.append("Require-all-students classes must be added to one group at a time.")

    # student/group clashes
    for group_id in target_group_ids:
        group = group_map[group_id]
        group_program_ids = {link.study_program_id for link in group.study_program_links}
        existing = db.scalars(
            select(ScheduledClass)
            .where(
                ScheduledClass.deploy.is_(True),
                ScheduledClass.group_id == group_id,
                ScheduledClass.timeslot_id == timeslot_id,
            )
        ).all()

        if mode == MODE_ELECTIVE:
            continue

        if mode == MODE_REQUIRED:
            blocking = [cls for cls in existing if not cls.course.elective]
            if blocking:
                errors.append(f"Group {group.code} already has a non-elective class in this timeslot.")
                continue

        if mode == MODE_PROGRAM:
            missing = [pid for pid in study_program_ids if pid not in group_program_ids]
            if missing:
                errors.append(f"Group {group.code} does not contain all selected study programs.")
                continue

            if any((cls.study_program_id is None and not cls.course.elective) for cls in existing):
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
        allow_teacher_conflict=allow_teacher_conflict,
    )
    if errors:
        return [], errors

    shared_key = str(uuid4()) if len(target_group_ids) > 1 or len(study_program_ids) > 1 else None
    created: List[ScheduledClass] = []

    if mode == MODE_REQUIRED:
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
    elif mode == MODE_PROGRAM:
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
    "Elective": "elective",
    "Business": "core",
    "Science": "shared",
    "CSE": "other",
    "ARC": "shared",
    "Other": "other",
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
    group_map = {g.id: g for g in groups}
    timeslots = db.scalars(select(Timeslot).order_by(Timeslot.sort_order)).all()
    class_ids_filter: Optional[List[int]] = None
    if study_program_ids is not None:
        class_ids_filter = [group.id for group in groups]

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
        class_query = class_query.join(Course, ScheduledClass.course).where(
            ScheduledClass.group_id.in_(class_ids_filter),
            or_(
                Course.require_all_student_in_group.is_(True),
                Course.elective.is_(True),
                ScheduledClass.study_program_id.in_(study_program_ids),
            ),
        )
    classes = db.execute(class_query).unique().scalars().all()

    cell_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    grouped: Dict[Tuple[int, int, int | None, str | None], List[ScheduledClass]] = defaultdict(list)
    for cls in classes:
        if cls.shared_key:
            key = (
                cls.timeslot_id,
                cls.group_id,
                cls.course_id,
                cls.shared_key,
            )
        else:
            kind = "elective" if cls.course.elective else ("required" if cls.course.require_all_student_in_group else "program")
            key = (
                cls.timeslot_id,
                cls.group_id,
                cls.course_id,
                kind,
                cls.teacher_id,
                cls.room_id,
                cls.notes or "",
            )
        grouped[key].append(cls)

    for key, bundle in grouped.items():
        group_id = key[1]
        first = bundle[0]
        programs = sorted({cls.study_program.code for cls in bundle if cls.study_program})
        kind = "elective" if first.course.elective else ("required" if first.course.require_all_student_in_group else "program")
        color_key = COLOR_MAP.get(first.course.course_tag.name, "other")
        fill_color = FILL_MAP.get(first.course.course_tag.name, "D9D2E9")
        if kind == "program":
            program_key = "|".join(programs) if programs else first.course.course_tag.name
            fill_color = PROGRAM_FILL_VARIANTS[abs(hash(program_key)) % len(PROGRAM_FILL_VARIANTS)]
        item = {
            "id": min(cls.id for cls in bundle),
            "course_name": first.course.name,
            "teacher_name": first.teacher.name if first.teacher else "",
            "room_name": first.room.code if first.room else "",
            "program_codes": programs,
            "group_codes": [group_map[group_id].code] if group_id in group_map else [],
            "notes": first.notes or "",
            "kind": kind,
            "color_key": color_key,
            "fill_color": fill_color,
            "shared": bool(first.shared_key),
            "expected_size": first.expected_size,
        }
        cell_map[str(first.timeslot_id)][str(group_id)].append(item)

    # sort display order within each cell
    sort_rank = {"required": 0, "program": 1, "elective": 2}
    for tmap in cell_map.values():
        for gid, items in tmap.items():
            items.sort(key=lambda item: (sort_rank[item["kind"]], item["course_name"]))

    return {
        "groups": [
            {
                "id": g.id,
                "code": g.code,
                "name": g.name,
                "capacity": g.size_num,
                "group_tag": {"id": g.group_tag.id, "code": g.group_tag.code, "name": g.group_tag.name},
                "programs": [
                    {"id": link.study_program.id, "code": link.study_program.code, "name": link.study_program.name}
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
        query = query.join(GroupStudyProgram, GroupStudyProgram.group_id == ScheduledClass.group_id).where(
            GroupStudyProgram.study_program_id.in_(study_program_ids),
            or_(
                ScheduledClass.study_program_id.is_(None),
                ScheduledClass.study_program_id.in_(study_program_ids),
            ),
        )
    rows = db.execute(query.group_by(ScheduledClass.teacher_id).order_by(func.count(func.distinct(ScheduledClass.timeslot_id)).desc())).all()
    result = []
    from .models import Teacher
    for teacher_id, count in rows:
        teacher = db.get(Teacher, teacher_id)
        result.append({"teacher": teacher.name if teacher else str(teacher_id), "timeslot_count": int(count)})
    return result
