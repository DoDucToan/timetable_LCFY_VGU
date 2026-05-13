from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, DB_PATH, SessionLocal, engine
from .models import (
    Course,
    CourseForGroupTag,
    CourseTag,
    Cycle,
    Group,
    GroupStudyProgram,
    GroupTag,
    Room,
    ScheduledClass,
    StudyProgram,
    StudyProgramCourse,
    Teacher,
    TeacherCourseTag,
    Timeslot,
    Timetable,
)

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "FY2025_Timetable_Phase_4_complete.json"
PROGRAM_CODES = {"ARC", "BBA", "BCE", "BFA", "BSE", "CSE", "ECE", "SME", "SPE", "MEN", "MEC", "BIS", "MBA", "GPEM", "MSST", "SUD", "COMPENG"}


def _migrate_course_for_group_table() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='course_for_group_only'")
    new_exists = cur.fetchone() is not None
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='course_for_group'")
    old_exists = cur.fetchone() is not None

    if old_exists and not new_exists:
        cur.execute('ALTER TABLE course_for_group RENAME TO course_for_group_only')
        conn.commit()
    elif old_exists and new_exists:
        cur.execute(
            """
            INSERT INTO course_for_group_only (group_id, course_id, sessions_required)
            SELECT old.group_id, old.course_id, old.sessions_required
            FROM course_for_group AS old
            WHERE NOT EXISTS (
                SELECT 1
                FROM course_for_group_only AS new
                WHERE new.group_id = old.group_id
                  AND new.course_id = old.course_id
            )
            """
        )
        conn.commit()
        cur.execute('DROP TABLE IF EXISTS course_for_group')
        conn.commit()
    conn.close()


def _is_index_matching_columns(conn: sqlite3.Connection, table: str, expected_columns: list[str]) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA index_list(%s)" % repr(table))
    for _, name, _, unique, _ in cur.fetchall():
        if unique != 1:
            continue
        cur.execute("PRAGMA index_info(%s)" % repr(name))
        columns = [row[2] for row in cur.fetchall()]
        if columns == expected_columns:
            return True
    return False


def _rebuild_table_with_unique_constraint(conn: sqlite3.Connection, table_name: str, create_sql: str) -> None:
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys=OFF')
    conn.commit()
    cur.execute(f'ALTER TABLE {table_name} RENAME TO {table_name}_old')
    conn.commit()
    cur.execute(create_sql)
    conn.commit()
    cur.execute(
        f'INSERT INTO {table_name} SELECT * FROM {table_name}_old'
    )
    conn.commit()
    cur.execute(f'DROP TABLE {table_name}_old')
    conn.commit()
    cur.execute('PRAGMA foreign_keys=ON')
    conn.commit()


def _ensure_requirement_unique_constraints() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        if not _is_index_matching_columns(conn, 'course_for_group_tag', ['group_tag_id', 'course_id', 'timetable_id']):
            _rebuild_table_with_unique_constraint(
                conn,
                'course_for_group_tag',
                '''CREATE TABLE course_for_group_tag (
                    id INTEGER NOT NULL PRIMARY KEY,
                    group_tag_id INTEGER NOT NULL,
                    course_id INTEGER NOT NULL,
                    timetable_id INTEGER NOT NULL,
                    sessions_required INTEGER NOT NULL,
                    FOREIGN KEY(group_tag_id) REFERENCES group_tag (id),
                    FOREIGN KEY(course_id) REFERENCES course (id),
                    FOREIGN KEY(timetable_id) REFERENCES timetable (id),
                    UNIQUE(group_tag_id, course_id, timetable_id)
                )''',
            )
        if not _is_index_matching_columns(conn, 'study_program_has_course', ['study_program_id', 'course_id', 'timetable_id']):
            _rebuild_table_with_unique_constraint(
                conn,
                'study_program_has_course',
                '''CREATE TABLE study_program_has_course (
                    id INTEGER NOT NULL PRIMARY KEY,
                    study_program_id INTEGER NOT NULL,
                    course_id INTEGER NOT NULL,
                    timetable_id INTEGER NOT NULL,
                    sessions_required INTEGER NOT NULL,
                    FOREIGN KEY(study_program_id) REFERENCES study_program (id),
                    FOREIGN KEY(course_id) REFERENCES course (id),
                    FOREIGN KEY(timetable_id) REFERENCES timetable (id),
                    UNIQUE(study_program_id, course_id, timetable_id)
                )''',
            )
    finally:
        conn.close()


def _ensure_group_sort_order_column() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='group_tbl'")
    if cur.fetchone() is None:
        conn.close()
        return

    cur.execute("PRAGMA table_info(group_tbl)")
    columns = [row[1] for row in cur.fetchall()]
    if 'sort_order' not in columns:
        cur.execute('ALTER TABLE group_tbl ADD COLUMN sort_order INTEGER DEFAULT 0')
        conn.commit()
        cur.execute('UPDATE group_tbl SET sort_order = id WHERE sort_order IS NULL OR sort_order = 0')
        conn.commit()
    conn.close()


def _ensure_cycle_german_column() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cycle'")
        if cur.fetchone() is None:
            return
        cur.execute("PRAGMA table_info(cycle)")
        columns = [row[1] for row in cur.fetchall()]
        if 'german_timeslots' not in columns:
            cur.execute('ALTER TABLE cycle ADD COLUMN german_timeslots BOOLEAN NOT NULL DEFAULT 0')
            conn.commit()
    finally:
        conn.close()


def ensure_database() -> None:
    _migrate_course_for_group_table()
    _ensure_group_sort_order_column()
    _ensure_requirement_unique_constraints()
    _ensure_cycle_german_column()
    Base.metadata.create_all(bind=engine)


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return text or "item"


def get_or_create(db: Session, model, defaults=None, **kwargs):
    instance = db.scalar(select(model).filter_by(**kwargs))
    if instance:
        return instance
    params = dict(kwargs)
    if defaults:
        params.update(defaults)
    instance = model(**params)
    db.add(instance)
    db.flush()
    return instance


def clean_group_tag(group_code: str) -> Tuple[str, str]:
    if group_code.startswith("PRE"):
        return ("PRE", "Pre-Foundation")
    m = re.match(r"([A-Z]+)", group_code)
    code = m.group(1) if m else "MISC"
    name_map = {
        "A": "A groups",
        "B": "B groups",
        "C": "C groups",
        "D": "D groups",
        "PRE": "Pre-Foundation",
        "STAFF": "Staff",
        "MISC": "Miscellaneous",
    }
    return code, name_map.get(code, f"{code} groups")


def clean_room(raw: Optional[str]) -> Tuple[Optional[str], Optional[str], int]:
    if not raw:
        return None, None, 999
    text = raw.replace("Room:", "").strip()
    if not text:
        return None, None, 999
    seats = None
    seat_match = re.search(r"(\d+)\s*seats?", text, re.IGNORECASE)
    if seat_match:
        seats = int(seat_match.group(1))
    text = re.sub(r"\(.*?seats?.*?\)", "", text, flags=re.IGNORECASE).strip(" _-")
    code = text.replace(" ", "")
    return code, text, seats or 80


def infer_course_name(activity: Dict[str, str]) -> str:
    hay = " ".join([activity.get("title") or "", activity.get("raw_text") or "", activity.get("notes") or ""])
    rules = [
        (r"Introduction to German Culture", "Introduction to German Culture"),
        (r"Leadership Skills", "AE8 - Leadership Skills"),
        (r"English for Information and Communication Technology 2", "English for Information and Communication Technology 2"),
        (r"Architectural Representation\s*&\s*Fabrication", "Architectural Representation & Fabrication"),
        (r"Architecture Foundation", "Architecture Foundation"),
        (r"Sculpture for Architecture", "Sculpture for Architecture"),
        (r"General Physics", "General Physics"),
        (r"Basic Laboratory Practice", "Basic Laboratory Practice"),
        (r"Calculus 1", "Calculus 1"),
        (r"Business administration", "Business Administration"),
        (r"Business IT 2", "Business IT 2"),
        (r"Introduction to Business Decision Making", "Introduction to Business Decision Making"),
        (r"Business English 3", "Business English 3"),
        (r"IELTS\s*4", "IELTS 4"),
        (r"IELTS\s*3", "IELTS 3"),
        (r"German\s*4", "German 4"),
        (r"German\s*3", "German 3"),
        (r"German\s*2", "German 2"),
        (r"German\s*1", "German 1"),
        (r"AE\s*8", "AE8"),
        (r"AE\s*7", "AE7"),
        (r"AE\s*6", "AE6"),
        (r"AE\s*5", "AE5"),
        (r"AE\s*4", "AE4"),
        (r"AE\s*2", "AE2"),
        (r"AE\s*1", "AE1"),
        (r"Self[ -]?study", "Self-study"),
    ]
    for pattern, name in rules:
        if re.search(pattern, hay, re.IGNORECASE):
            return name
    title = activity.get("title") or activity.get("raw_text") or "Untitled"
    return re.sub(r"[_|]+", " ", title).strip()


def infer_course_tag(course_name: str, activity: Dict[str, str]) -> str:
    if course_name.startswith("IELTS"):
        return "IELTS"
    if course_name.startswith("German") or course_name == "Introduction to German Culture":
        return "German"
    if course_name.startswith("AE"):
        return "AE" if "Leadership" not in course_name else "Elective"
    if course_name in {"Business English 3", "Business IT 2", "Introduction to Business Decision Making", "Business Administration"}:
        return "Business"
    if course_name in {"General Physics", "Basic Laboratory Practice", "Calculus 1"}:
        return "Science"
    if course_name == "English for Information and Communication Technology 2":
        return "CSE"
    if course_name in {"Architectural Representation & Fabrication", "Architecture Foundation", "Sculpture for Architecture"}:
        return "ARC"
    if "elective" in (activity.get("raw_text") or "").lower():
        return "Elective"
    return "Other"


def infer_program_codes(activity: Dict[str, str], group_programs: Dict[str, Set[str]], group_code: str, course_name: str, require_all: bool, elective: bool) -> List[str]:
    if require_all or elective:
        return []
    text = " ".join([activity.get("title") or "", activity.get("raw_text") or "", activity.get("notes") or ""])
    found = []
    for code in sorted(PROGRAM_CODES, key=len, reverse=True):
        pattern = rf"(?<![A-Z]){re.escape(code)}(?![A-Z])"
        if re.search(pattern, text.replace("CompEng", "COMPENG"), re.IGNORECASE):
            found.append(code)
    gp = group_programs.get(group_code, set())
    result = [code for code in found if code in gp]
    if result:
        return sorted(set(result))
    if len(gp) == 1:
        return sorted(gp)
    if course_name.startswith("Business"):
        return sorted(gp.intersection({"BBA", "BFA", "BSE"}))
    if course_name in {"General Physics", "Basic Laboratory Practice"}:
        return sorted(gp.intersection({"BCE", "SME", "SPE"}))
    if course_name == "Calculus 1":
        return sorted(gp.intersection({"SME"}))
    if course_name == "English for Information and Communication Technology 2":
        return sorted(gp.intersection({"CSE"}))
    if course_name in {"Architectural Representation & Fabrication", "Architecture Foundation", "Sculpture for Architecture"}:
        return sorted(gp.intersection({"ARC"}))
    return []


def seed_phase4(force_reset: bool = False) -> None:
    ensure_database()
    db = SessionLocal()
    try:
        if force_reset:
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)

        existing = db.scalar(select(Cycle.id).limit(1))
        if existing:
            return

        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))

        cycle = Cycle(name="FY2025/26", year_starting=2025)
        db.add(cycle)
        db.flush()

        timetable = Timetable(cycle_id=cycle.id, in_action=True)
        db.add(timetable)
        db.flush()

        # timeslots
        slot_map: Dict[str, Timeslot] = {}
        weekday_index = {"MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3, "THURSDAY": 4, "FRIDAY": 5}
        for slot in data["slots"]:
            start, end = [part.strip() for part in slot["label"].split("-")]
            ts = Timeslot(
                weekday=slot["day"],
                day_index=weekday_index.get(slot["day"], 99),
                start_time=start,
                end_time=end,
                label=slot["label"],
                sort_order=slot["order"],
            )
            db.add(ts)
            db.flush()
            slot_map[slot["id"]] = ts

        # study programs
        program_map: Dict[str, StudyProgram] = {}
        for group in data["groups"]:
            for code in group.get("programs", []):
                code = code.upper().replace("COMPENG", "COMPENG")
                if code not in program_map:
                    program_map[code] = get_or_create(db, StudyProgram, code=code, name=code)

        # group tags + groups
        group_map: Dict[str, Group] = {}
        group_programs: Dict[str, Set[str]] = {g["id"]: set(code.upper() for code in g.get("programs", [])) for g in data["groups"]}
        default_sizes = {"PRE": 40, "A": 42, "B": 40, "C": 38, "D": 36}
        for group_data in data["groups"]:
            tag_code, tag_name = clean_group_tag(group_data["id"])
            group_tag = get_or_create(db, GroupTag, code=tag_code, name=tag_name)
            size = default_sizes.get(tag_code, 40)
            group = Group(
                timetable_id=timetable.id,
                group_tag_id=group_tag.id,
                code=group_data["id"],
                name=group_data.get("label") or group_data["id"],
                size_num=size,
            )
            db.add(group)
            db.flush()
            group_map[group.code] = group
            for prog_code in group_data.get("programs", []):
                db.add(GroupStudyProgram(group_id=group.id, study_program_id=program_map[prog_code.upper()].id))

        # teachers / rooms / course tags / courses
        teacher_map: Dict[str, Teacher] = {}
        room_map: Dict[str, Room] = {}
        course_tag_map: Dict[str, CourseTag] = {}
        course_map: Dict[str, Course] = {}

        def get_course_tag(name: str) -> CourseTag:
            if name not in course_tag_map:
                course_tag_map[name] = get_or_create(db, CourseTag, name=name)
            return course_tag_map[name]

        for activity in data["activities"]:
            if activity.get("teacher_display"):
                teacher_name = activity["teacher_display"].strip()
                if teacher_name not in teacher_map:
                    teacher_map[teacher_name] = get_or_create(db, Teacher, name=teacher_name)
            room_code, room_name, capacity = clean_room(activity.get("room_display"))
            if room_code:
                if room_code not in room_map:
                    room_map[room_code] = get_or_create(db, Room, code=room_code, name=room_name or room_code, capacity_num=capacity)
            course_name = infer_course_name(activity)
            elective = "elective" in (activity.get("raw_text") or "").lower() or course_name == "AE8 - Leadership Skills" or course_name == "Introduction to German Culture"
            require_all = not elective and (course_name.startswith("IELTS") or course_name.startswith("German") or course_name.startswith("AE") or course_name == "Self-study")
            course_tag = get_course_tag(infer_course_tag(course_name, activity))
            course_code = slugify(course_name)
            if course_code not in course_map:
                course = Course(
                    code=course_code,
                    name=course_name,
                    require_all_student_in_group=require_all,
                    elective=elective,
                    course_tag_id=course_tag.id,
                )
                db.add(course)
                db.flush()
                course_map[course_code] = course
            else:
                course = course_map[course_code]

        db.flush()

        # teacher-course-tag links + study-program-course links + classes
        requirement_counter: Counter[Tuple[int, int]] = Counter()
        for activity in data["activities"]:
            course_name = infer_course_name(activity)
            course = course_map[slugify(course_name)]
            slot = slot_map[activity["fixed_slot_id"]]
            teacher = teacher_map.get((activity.get("teacher_display") or "").strip())
            room_code, _room_name, _capacity = clean_room(activity.get("room_display"))
            room = room_map.get(room_code) if room_code else None
            if teacher:
                get_or_create(db, TeacherCourseTag, teacher_id=teacher.id, course_tag_id=course.course_tag_id)

            shared_key = str(uuid4()) if len(activity.get("display_groups", [])) > 1 else None
            for group_code in activity.get("display_groups", []):
                group = group_map.get(group_code)
                if not group:
                    continue
                requirement_counter[(group.group_tag_id, course.id)] += 1
                programs = infer_program_codes(
                    activity,
                    group_programs=group_programs,
                    group_code=group_code,
                    course_name=course_name,
                    require_all=course.require_all_student_in_group,
                    elective=course.elective,
                )
                if programs:
                    for prog_code in programs:
                        prog = program_map[prog_code]
                        get_or_create(db, StudyProgramCourse, study_program_id=prog.id, course_id=course.id)
                        db.add(
                            ScheduledClass(
                                group_id=group.id,
                                timeslot_id=slot.id,
                                room_id=room.id if room else None,
                                teacher_id=teacher.id if teacher else None,
                                course_id=course.id,
                                study_program_id=prog.id,
                                deploy=True,
                                shared_key=shared_key,
                                expected_size=max(1, round(group.size_num / max(len(group_programs[group_code]), 1))),
                                notes=activity.get("notes"),
                                source="phase4_seed",
                            )
                        )
                else:
                    db.add(
                        ScheduledClass(
                            group_id=group.id,
                            timeslot_id=slot.id,
                            room_id=room.id if room else None,
                            teacher_id=teacher.id if teacher else None,
                            course_id=course.id,
                            study_program_id=None,
                            deploy=True,
                            shared_key=shared_key,
                            expected_size=group.size_num if course.require_all_student_in_group else None,
                            notes=activity.get("notes"),
                            source="phase4_seed",
                        )
                    )

        # group-tag requirements from observed timetable frequencies
        for (group_tag_id, course_id), count in requirement_counter.items():
            get_or_create(
                db,
                CourseForGroupTag,
                group_tag_id=group_tag_id,
                course_id=course_id,
                defaults={"sessions_required": count},
            )

        db.commit()
    finally:
        db.close()
