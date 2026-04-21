from __future__ import annotations

from collections import defaultdict
import time
from pathlib import Path
from typing import Any, Iterable, cast, Dict, List, Optional
from fastapi import Body, Depends, FastAPI, HTTPException, Query
from contextlib import asynccontextmanager
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from contextlib import asynccontextmanager
from .database import SessionLocal, get_db
from .excel_exporter import export_timetable_xlsx
from .models import (
    Course,
    CourseForGroup,
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
from .scheduler import MODE_ELECTIVE, MODE_PROGRAM, MODE_REQUIRED, create_classes, validate_new_class
from .schemas import (
    ClassCreateIn,
    CourseIn,
    CourseTagIn,
    CycleIn,
    GroupCreateIn,
    GroupOrderIn,
    GroupTagIn,
    RoomIn,
    StudyProgramIn,
    TeacherIn,
    TimetableIn,
)
from .seed import ensure_database

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
EXPORT_DIR: Path = ROOT_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _ensure_default_timeslots() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(Timeslot.id).limit(1)):
            return
        rows = [
            ("MONDAY", 1, "8.45", "12.00", "8.45 - 12.00", 1),
            ("MONDAY", 1, "13.00", "16.15", "13.00 - 16.15", 2),
            ("TUESDAY", 2, "8.45", "12.00", "8.45 - 12.00", 3),
            ("TUESDAY", 2, "13.00", "16.15", "13.00 - 16.15", 4),
            ("WEDNESDAY", 3, "8.45", "12.00", "8.45 - 12.00", 5),
            ("WEDNESDAY", 3, "13.00", "16.15", "13.00 - 16.15", 6),
            ("THURSDAY", 4, "8.45", "12.00", "8.45 - 12.00", 7),
            ("THURSDAY", 4, "13.00", "16.15", "13.00 - 16.15", 8),
            ("FRIDAY", 5, "8.45", "12.00", "8.45 - 12.00", 9),
            ("FRIDAY", 5, "13.00", "16.15", "13.00 - 16.15", 10),
        ]
        for weekday, day_index, start_time, end_time, label, sort_order in rows:
            db.add(
                Timeslot(
                    weekday=weekday,
                    day_index=day_index,
                    start_time=start_time,
                    end_time=end_time,
                    label=label,
                    sort_order=sort_order,
                )
            )
        db.commit()
    finally:
        db.close()



@asynccontextmanager
async def lifespan(app: FastAPI):  # Added type annotation
    ensure_database()
    _ensure_default_timeslots()
    yield

app = FastAPI(title="Timetable Builder", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"version": int(time.time())},
    )


def _selected_timetable(db: Session, timetable_id: Optional[int]) -> Optional[Timetable]:
    if timetable_id:
        timetable = db.get(Timetable, timetable_id)
        if timetable:
            return timetable
    timetable = db.scalar(select(Timetable).where(Timetable.in_action.is_(True)).order_by(Timetable.id))
    if timetable:
        return timetable
    return db.scalar(select(Timetable).order_by(Timetable.id))


def _current_timetable_id(db: Session, timetable_id: Optional[int] = None) -> Optional[int]:
    if timetable_id is not None:
        return timetable_id
    timetable = _selected_timetable(db, None)
    return getattr(timetable, 'id', None)


def _serialize_group_requirements(group_tag_id: int, db: Session, timetable_id: Optional[int] = None) -> List[Dict[str, Any]]:
    query = select(CourseForGroupTag).options(joinedload(CourseForGroupTag.course)).where(CourseForGroupTag.group_tag_id == group_tag_id)
    if timetable_id is not None:
        query = query.where(CourseForGroupTag.timetable_id == timetable_id)
    rows = db.scalars(query).all()
    rows = list(rows)
    rows.sort(key=lambda row: row.course.name if row.course else "")
    return [
        {
            "id": row.id,
            "course_id": row.course_id,
            "course_name": row.course.name if row.course else str(row.course_id),
            "sessions_required": row.sessions_required,
        }
        for row in rows
    ]
def _serialize_program_requirements(program_ids: List[int], db: Session, timetable_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if not program_ids:
        return []
    query = select(StudyProgramCourse).options(joinedload(StudyProgramCourse.course)).where(StudyProgramCourse.study_program_id.in_(program_ids))
    if timetable_id is not None:
        query = query.where(StudyProgramCourse.timetable_id == timetable_id)
    rows = db.scalars(query).all()
    rows = list(rows)
    rows.sort(key=lambda row: row.course.name if row.course else "")
    return [
        {
            "id": row.id,
            "course_id": row.course_id,
            "course_name": row.course.name if row.course else str(row.course_id),
            "sessions_required": getattr(row, "sessions_required", 1),
        }
        for row in rows
    ]


def _parse_int_list(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        try:
            return [int(value)]
        except ValueError:
            return []
    if isinstance(value, Iterable):
        ids: List[int] = []
        iterable_value = cast(Iterable[Any], value)
        for item in iterable_value:
            if item is None:
                continue
            if isinstance(item, int):
                ids.append(item)
                continue
            if isinstance(item, str):
                try:
                    ids.append(int(item))
                except ValueError:
                    continue
                continue
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                continue
        return ids
    return []

def _teacher_ids_by_tag(db: Session) -> Dict[int, List[int]]:
    result: Dict[int, List[int]] = {}
    for link in db.scalars(select(TeacherCourseTag)).all():
        result.setdefault(link.course_tag_id if isinstance(link.course_tag_id, int) else link.course_tag.id, []).append(link.teacher_id if isinstance(link.teacher_id, int) else link.teacher.id)
    return result


def teacher_load_rows_for_timetable(db: Session, timetable_id: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        select(
            ScheduledClass.teacher_id,
            func.count(func.distinct(ScheduledClass.timeslot_id)).label("timeslot_count"),
        )
        .join(Group, Group.id == ScheduledClass.group_id)
        .where(
            ScheduledClass.deploy.is_(True),
            ScheduledClass.teacher_id.is_not(None),
            Group.timetable_id == timetable_id,
        )
        .group_by(ScheduledClass.teacher_id)
        .order_by(func.count(func.distinct(ScheduledClass.timeslot_id)).desc())
    ).all()
    result: List[Dict[str, Any]] = []
    for teacher_id, count in rows:
        teacher = db.get(Teacher, teacher_id)
        result.append({"teacher": teacher.name if teacher else str(teacher_id), "timeslot_count": int(count)})
    return result


def _build_timetable_payload(db: Session, timetable_id: Optional[int]) -> Dict[str, Any]:
    timetable = _selected_timetable(db, timetable_id)
    timeslots = db.scalars(select(Timeslot).order_by(Timeslot.sort_order)).all()

    payload: Dict[str, Any] = {
        "selected_timetable_id": timetable.id if timetable else None,
        "selected_cycle_id": timetable.cycle_id if timetable else None,
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
        "groups": [],
        "cells": {},
        "teacher_load": [],
    }

    if not timetable:
        return payload

    groups = db.execute(
        select(Group)
        .where(Group.timetable_id == timetable.id)
        .options(
            joinedload(Group.group_tag),
            joinedload(Group.study_program_links).joinedload(GroupStudyProgram.study_program),
        )
        .order_by(Group.sort_order)
    ).unique().scalars().all()

    group_ids = [cast(int, getattr(g, 'id')) for g in groups] if groups else []
    group_specific_reqs = list(db.execute(
        select(CourseForGroup)
        .options(joinedload(CourseForGroup.course))
        .where(CourseForGroup.group_id.in_(group_ids))
    ).unique().scalars().all()) if groups else []

    group_specific_by_group: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for req in group_specific_reqs:
        group_id = int(getattr(req, 'group_id'))
        course_id = int(getattr(req, 'course_id'))
        group_specific_by_group[group_id].append({
            'id': int(getattr(req, 'id')),
            'course_id': course_id,
            'course_name': req.course.name if getattr(req, 'course', None) and getattr(req.course, 'name', None) else str(course_id),
            'sessions_required': int(getattr(req, 'sessions_required', 0)),
        })
    for values in group_specific_by_group.values():
        values.sort(key=lambda item: item['course_name'])

    classes = db.execute(
        select(ScheduledClass)
        .join(Group, Group.id == ScheduledClass.group_id)
        .where(
            ScheduledClass.deploy.is_(True),
            Group.timetable_id == timetable.id,
        )
        .options(
            joinedload(ScheduledClass.course).joinedload(Course.course_tag),
            joinedload(ScheduledClass.group),
            joinedload(ScheduledClass.teacher),
            joinedload(ScheduledClass.room),
            joinedload(ScheduledClass.study_program),
            joinedload(ScheduledClass.timeslot),
        )
    ).unique().scalars().all()

    color_map = {
        "IELTS": "ielts",
        "German": "german",
        "AE": "ae",
        "Elective": "elective",
        "Business": "core",
        "Science": "shared",
        "Architecture": "shared",
    }

    cell_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    grouped: Dict[tuple[int, int, int, str], List[ScheduledClass]] = defaultdict(list)

    for cls in classes:
        key = (
            cls.timeslot_id if isinstance(cls.timeslot_id, int) else cls.timeslot.id,
            cls.group_id if isinstance(cls.group_id, int) else cls.group.id,
            cls.course_id if isinstance(cls.course_id, int) else cls.course.id,
            cls.shared_key if isinstance(cls.shared_key, str) else (f"solo-{cls.id}" if hasattr(cls, "id") else "")
        )
        grouped[key].append(cls)

    sort_rank = {"required": 0, "program": 1, "elective": 2}
    for (_timeslot_id, group_id, _course_id, _shared), bundle in grouped.items():
        first = bundle[0]
        programs = sorted({cls.study_program.code for cls in bundle if cls.study_program})
        kind = "elective" if bool(first.course.elective) else ("required" if bool(first.course.require_all_student_in_group) else "program")
        cell_map[str(first.timeslot_id)][str(group_id)].append(
            {
                "id": min(cls.id for cls in bundle),
                "class_ids": [cls.id for cls in bundle],
                "course_name": first.course.name,
                "teacher_name": first.teacher.name if first.teacher else "",
                "room_name": first.room.code if first.room else "",
                "program_codes": programs,
                "notes": first.notes or "",
                "kind": kind,
                "color_key": color_map.get(first.course.course_tag.name, "other"),
                "shared": bool(first.shared_key),
                "expected_size": first.expected_size,
            }
        )

    for tmap in cell_map.values():
        for items in tmap.values():
            items.sort(key=lambda item: (sort_rank[item["kind"]], item["course_name"]))

    payload["groups"] = [
        {
            "id": g.id,
            "code": g.code,
            "name": g.name,
            "capacity": g.size_num,
            "group_tag": {
                "id": getattr(g.group_tag, "id", None),
                "code": getattr(g.group_tag, "code", None),
                "name": getattr(g.group_tag, "name", None),
            },
            "programs": [
                {
                    "id": getattr(link.study_program, "id", None),
                    "code": getattr(link.study_program, "code", None),
                    "name": getattr(link.study_program, "name", None),
                }
                for link in sorted(g.study_program_links, key=lambda x: getattr(x.study_program, "code", ""))
            ],
            "group_requirements": group_specific_by_group.get(cast(int, getattr(g, 'id')), []),
            "requirements": [
                *(_serialize_group_requirements(
                    g.group_tag.id,
                    db,
                    getattr(timetable, "id", None) if timetable else None,
                ) if g.group_tag and g.group_tag.id is not None else []),
                *(_serialize_program_requirements(
                    [link.study_program_id for link in g.study_program_links],
                    db,
                    getattr(timetable, "id", None) if timetable else None,
                ) if g.study_program_links else []),
                *group_specific_by_group.get(cast(int, getattr(g, 'id')), []),
            ],
        }
        for g in groups
    ]
    payload["cells"] = cell_map
    payload["teacher_load"] = teacher_load_rows_for_timetable(
    db, getattr(timetable, "id", 0) if timetable else 0)
    return payload


def _entity_payload(db: Session, timetable_id: Optional[int] = None) -> Dict[str, Any]:
    cycles = db.scalars(select(Cycle).order_by(Cycle.year_starting.desc(), Cycle.name)).all()
    timetables = db.scalars(select(Timetable).order_by(Timetable.id)).all()
    group_tags = db.scalars(select(GroupTag).order_by(GroupTag.code)).all()
    course_tags = db.scalars(select(CourseTag).order_by(CourseTag.name)).all()
    programs = db.scalars(select(StudyProgram).order_by(StudyProgram.code)).all()

    # Use the requested timetable_id if provided; otherwise fall back to active or latest.
    if timetable_id is None and len(timetables) > 0:
        in_action = [t for t in timetables if getattr(t, 'in_action', False)]
        if in_action:
            timetable_id = cast(int, in_action[0].id)
        else:
            timetable_id = cast(int, timetables[-1].id)
    group_tag_requirement: Dict[int, List[Dict[str, Any]]] = {}
    for gt in group_tags:
        query = db.query(CourseForGroupTag).filter(CourseForGroupTag.group_tag_id == gt.id)
        if timetable_id is not None:
            query = query.filter(CourseForGroupTag.timetable_id == timetable_id)
        reqs = query.all()
        group_tag_requirement[cast(int, gt.id)] = [
            {
                "course_id": r.course_id,
                "course_name": r.course.name if r.course else str(r.course_id),
                "sessions_required": r.sessions_required,
            }
            for r in reqs
        ]
    program_requirements: Dict[int, List[Dict[str, Any]]] = {}
    for prog in programs:
        query = db.query(StudyProgramCourse).filter(StudyProgramCourse.study_program_id == prog.id)
        if timetable_id is not None:
            query = query.filter(StudyProgramCourse.timetable_id == timetable_id)
        reqs = query.all()
        program_requirements[cast(int, prog.id)] = [
            {
                "course_id": r.course_id,
                "course_name": r.course.name if r.course else str(r.course_id),
                "sessions_required": getattr(r, "sessions_required", 1),
            }
            for r in reqs
        ]
    rooms = db.scalars(select(Room).order_by(Room.code)).all()
    teachers = db.execute(select(Teacher).options(joinedload(Teacher.course_tag_links)).order_by(Teacher.name)).unique().scalars().all()
    courses = db.execute(
        select(Course)
        .options(
            joinedload(Course.course_tag),
            joinedload(Course.study_program_links).joinedload(StudyProgramCourse.study_program),
        )
        .order_by(Course.name)
    ).unique().scalars().all()


    return {
        "cycles": [{"id": c.id, "name": c.name, "year_starting": c.year_starting} for c in cycles],
        "timetables": [{"id": t.id, "cycle_id": t.cycle_id, "in_action": t.in_action} for t in timetables],
        "group_tags": [
            {
                "id": gt.id,
                "code": gt.code,
                "name": gt.name,
                "requirements": group_tag_requirement.get(cast(int, gt.id), [])
            }
            for gt in group_tags
        ],
        "course_tags": [{"id": ct.id, "name": ct.name} for ct in course_tags],
        "programs": [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "requirements": program_requirements.get(cast(int, p.id), [])
            }
            for p in programs
        ],
        "rooms": [{"id": r.id, "code": r.code, "name": r.name, "capacity": r.capacity_num} for r in rooms],
        "teachers": [{"id": t.id, "name": t.name, "course_tag_ids": sorted(link.course_tag_id for link in t.course_tag_links)} for t in teachers],
        "courses": [
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "course_tag_id": c.course_tag_id,
                "course_tag_name": c.course_tag.name if c.course_tag else None,
                "require_all": c.require_all_student_in_group,
                "elective": c.elective,
                "study_program_ids": sorted(link.study_program_id for link in c.study_program_links),
            }
            for c in courses
        ],
        "teacher_ids_by_tag": _teacher_ids_by_tag(db),
        #load all requirements for all group tags and programs to avoid loading them separately when user clicks on a group - this is a tradeoff to reduce number of queries and simplify frontend code, at the cost of loading some unused data on the main screen load
       #based  on def above, try to get timetable_id from the latest timetable (in_action or max id) and pass it to the requirement loading functions to load only requirements relevant for the currently selected timetable
        "group_tag_requirements": group_tag_requirement,
        "program_requirements": program_requirements,
    }


def bootstrap_payload(db: Session, timetable_id: Optional[int] = None) -> Dict[str, Any]:
    return {**_build_timetable_payload(db, timetable_id), **_entity_payload(db, timetable_id)}


@app.get("/api/bootstrap")
def api_bootstrap(timetable_id: Optional[int] = Query(default=None), db: Session = Depends(get_db)):
    return JSONResponse(bootstrap_payload(db, timetable_id))


def _apply_group_payload(group: Group, payload: GroupCreateIn, db: Session) -> None:
    if not db.get(GroupTag, payload.group_tag_id):
        raise HTTPException(status_code=404, detail="Group tag not found.")
    # Assign to ORM instance attributes, not Column objects
    setattr(group, "code", payload.code.upper())
    setattr(group, "name", payload.name or payload.code.upper())
    setattr(group, "group_tag_id", payload.group_tag_id)
    setattr(group, "size_num", payload.capacity)
    if getattr(payload, 'sort_order', None) is not None:
        setattr(group, 'sort_order', payload.sort_order)

    group.study_program_links.clear()
    db.flush()
    for program_id in payload.study_program_ids:
        if not db.get(StudyProgram, program_id):
            raise HTTPException(status_code=404, detail=f"Study program {program_id} not found.")
        group.study_program_links.append(GroupStudyProgram(group_id=group.id, study_program_id=program_id))

    existing = db.scalars(select(CourseForGroup).where(CourseForGroup.group_id == group.id)).all()
    existing_by_course = {getattr(item, "course_id", None): item for item in existing}
    incoming: set[int] = set()
    group_reqs = payload.group_requirements if getattr(payload, 'group_requirements', None) is not None else payload.requirements
    for req in group_reqs:
        cid = req.course_id
        incoming.add(cid)
        if not db.get(Course, cid):
            raise HTTPException(status_code=404, detail=f"Course {cid} not found.")
        link = existing_by_course.get(cid)
        if link:
            setattr(link, "sessions_required", req.sessions_required)
        else:
            db.add(CourseForGroup(group_id=group.id, course_id=cid, sessions_required=req.sessions_required))
    for link in existing:
        if getattr(link, "course_id", None) not in incoming:
            db.delete(link)


@app.post("/api/cycles")
def create_cycle(payload: CycleIn, db: Session = Depends(get_db)):
    row = Cycle(name=payload.name.strip(), year_starting=payload.year_starting)
    db.add(row)
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/cycles/{cycle_id}")
def update_cycle(cycle_id: int, payload: CycleIn, db: Session = Depends(get_db)):
    row = db.get(Cycle, cycle_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cycle not found.")
    row.name = payload.name.strip()  # type: ignore
    row.year_starting = payload.year_starting  # type: ignore
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/cycles/{cycle_id}")
def delete_cycle(cycle_id: int, db: Session = Depends(get_db)):
    row = db.get(Cycle, cycle_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cycle not found.")
    if db.scalar(select(Timetable.id).where(Timetable.cycle_id == cycle_id).limit(1)):
        raise HTTPException(status_code=400, detail="Delete timetables in this cycle first.")
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/timetables")
def create_timetable(payload: TimetableIn, db: Session = Depends(get_db)):
    if not db.get(Cycle, payload.cycle_id):
        raise HTTPException(status_code=404, detail="Cycle not found.")
    if payload.in_action:
        db.query(Timetable).update({Timetable.in_action: False})
    row = Timetable(cycle_id=payload.cycle_id, in_action=payload.in_action)
    db.add(row)
    db.commit()
    db.refresh(row)  # Ensure row.id is populated with the actual int value
    # row.id should be an int after db.refresh(row)
    timetable_id = getattr(row, 'id', None)
    if timetable_id is None or not isinstance(timetable_id, int):
        db.refresh(row)
        timetable_id = getattr(row, 'id', None)
    return bootstrap_payload(db, int(timetable_id) if timetable_id is not None else None)


@app.put("/api/timetables/{timetable_id}")
def update_timetable(timetable_id: int, payload: TimetableIn, db: Session = Depends(get_db)):
    row = db.get(Timetable, timetable_id)
    if not row:
        raise HTTPException(status_code=404, detail="Timetable not found.")
    if not db.get(Cycle, payload.cycle_id):
        raise HTTPException(status_code=404, detail="Cycle not found.")
    if payload.in_action:
        db.query(Timetable).update({Timetable.in_action: False})
    row.cycle_id = payload.cycle_id  # type: ignore
    row.in_action = payload.in_action  # type: ignore
    db.commit()
    db.refresh(row)  # Ensure row.id is an int, not a Column
    tid = getattr(row, 'id', None)
    if tid is None or not isinstance(tid, int):
        db.refresh(row)
        tid = getattr(row, 'id', None)
    return bootstrap_payload(db, int(tid) if tid is not None else None)


@app.post("/api/timetables/{timetable_id}/deploy")
def deploy_timetable(timetable_id: int, db: Session = Depends(get_db)):
    row = db.get(Timetable, timetable_id)
    if not row:
        raise HTTPException(status_code=404, detail="Timetable not found.")
    db.query(Timetable).update({Timetable.in_action: False})
    row.in_action = True  # type: ignore
    db.commit()
    db.refresh(row)
    tid = getattr(row, 'id', None)
    return bootstrap_payload(db, int(tid) if tid is not None else None)


@app.delete("/api/timetables/{timetable_id}")
def delete_timetable(timetable_id: int, db: Session = Depends(get_db)):
    row = db.get(Timetable, timetable_id)
    if not row:
        raise HTTPException(status_code=404, detail="Timetable not found.")
    group_ids = db.scalars(select(Group.id).where(Group.timetable_id == timetable_id)).all()
    if group_ids:
        db.query(ScheduledClass).filter(ScheduledClass.group_id.in_(group_ids)).delete(synchronize_session=False)
        db.query(GroupStudyProgram).filter(GroupStudyProgram.group_id.in_(group_ids)).delete(synchronize_session=False)
        db.query(Group).filter(Group.id.in_(group_ids)).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/group-tags")
def create_group_tag(payload: GroupTagIn, db: Session = Depends(get_db)):
    row = GroupTag(code=payload.code.strip().upper(), name=payload.name.strip())
    db.add(row)
    db.flush()
    timetable_id = _current_timetable_id(db)
    if timetable_id is None and payload.requirements:
        raise HTTPException(status_code=400, detail="No timetable selected for group tag requirements.")
    for req in payload.requirements:
        db.add(CourseForGroupTag(
            group_tag_id=row.id,
            course_id=req.course_id,
            sessions_required=req.sessions_required,
            timetable_id=timetable_id,
        ))
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/group-tags/{group_tag_id}")
def update_group_tag(group_tag_id: int, payload: GroupTagIn, db: Session = Depends(get_db)):
    row = db.get(GroupTag, group_tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Group tag not found.")
    row.code = payload.code.strip().upper()  # type: ignore
    row.name = payload.name.strip()  # type: ignore
    timetable_id = _current_timetable_id(db)
    existing = db.scalars(
        select(CourseForGroupTag)
        .where(
            CourseForGroupTag.group_tag_id == group_tag_id,
            CourseForGroupTag.timetable_id == timetable_id,
        )
    ).all()
    if timetable_id is None and payload.requirements:
        raise HTTPException(status_code=400, detail="No timetable selected for group tag requirements.")
    def get_int(val: Any) -> int:
        if isinstance(val, int):
            return val
        if hasattr(val, 'value'):
            return int(val.value)
        return int(str(val))
    existing_by_course = {get_int(x.course_id): x for x in existing}
    seen: set[int] = set()
    for req in payload.requirements:
        cid = get_int(req.course_id)
        if not db.get(Course, cid):
            seen.add(cid)
            link = existing_by_course.get(cid)
            if link:
                link.sessions_required = req.sessions_required  # type: ignore
            else:
                db.add(CourseForGroupTag(
                    group_tag_id=group_tag_id,
                    course_id=cid,
                    sessions_required=req.sessions_required,
                    timetable_id=timetable_id,
                ))
    for link in existing:
        cid = get_int(link.course_id)
        if cid not in seen:
            db.delete(link)
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/group-tags/{group_tag_id}")
def delete_group_tag(group_tag_id: int, db: Session = Depends(get_db)):
    row = db.get(GroupTag, group_tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Group tag not found.")
    if db.scalar(select(Group.id).where(Group.group_tag_id == group_tag_id).limit(1)):
        raise HTTPException(status_code=400, detail="Group tag is used by one or more groups.")
    db.query(CourseForGroupTag).filter(CourseForGroupTag.group_tag_id == group_tag_id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/course-tags")
def create_course_tag(payload: CourseTagIn, db: Session = Depends(get_db)):
    db.add(CourseTag(name=payload.name.strip()))
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/course-tags/{course_tag_id}")
def update_course_tag(course_tag_id: int, payload: CourseTagIn, db: Session = Depends(get_db)):
    row = db.get(CourseTag, course_tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course tag not found.")
    row.name = payload.name.strip()  # type: ignore
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/course-tags/{course_tag_id}")
def delete_course_tag(course_tag_id: int, db: Session = Depends(get_db)):
    row = db.get(CourseTag, course_tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course tag not found.")
    if db.scalar(select(Course.id).where(Course.course_tag_id == course_tag_id).limit(1)) or db.scalar(select(TeacherCourseTag.id).where(TeacherCourseTag.course_tag_id == course_tag_id).limit(1)):
        raise HTTPException(status_code=400, detail="Course tag is in use by courses or teachers.")
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/study-programs")
def create_program(payload: StudyProgramIn, db: Session = Depends(get_db)):
    db.add(StudyProgram(code=payload.code.strip().upper(), name=payload.name.strip()))
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/study-programs/{program_id}")
def update_program(program_id: int, payload: StudyProgramIn, db: Session = Depends(get_db)):
    row = db.get(StudyProgram, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Study program not found.")
    row.code = payload.code.strip().upper()  # type: ignore
    row.name = payload.name.strip()  # type: ignore
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/study-programs/{program_id}")
def delete_program(program_id: int, db: Session = Depends(get_db)):
    row = db.get(StudyProgram, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Study program not found.")
    if db.scalar(select(GroupStudyProgram.id).where(GroupStudyProgram.study_program_id == program_id).limit(1)) or db.scalar(select(StudyProgramCourse.id).where(StudyProgramCourse.study_program_id == program_id).limit(1)) or db.scalar(select(ScheduledClass.id).where(ScheduledClass.study_program_id == program_id).limit(1)):
        raise HTTPException(status_code=400, detail="Study program is in use.")
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/rooms")
def create_room(payload: RoomIn, db: Session = Depends(get_db)):
    db.add(Room(code=payload.code.strip().upper(), name=payload.name.strip(), capacity_num=payload.capacity))
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/rooms/{room_id}")
def update_room(room_id: int, payload: RoomIn, db: Session = Depends(get_db)):
    row = db.get(Room, room_id)
    if not row:
        raise HTTPException(status_code=404, detail="Room not found.")
    row.code = payload.code.strip().upper()  # type: ignore
    row.name = payload.name.strip()  # type: ignore
    row.capacity_num = payload.capacity  # type: ignore
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db)):
    row = db.get(Room, room_id)
    if not row:
        raise HTTPException(status_code=404, detail="Room not found.")
    if db.scalar(select(ScheduledClass.id).where(ScheduledClass.room_id == room_id).limit(1)):
        raise HTTPException(status_code=400, detail="Room is used by one or more scheduled classes.")
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/teachers")
def create_teacher(payload: TeacherIn, db: Session = Depends(get_db)):
    row = Teacher(name=payload.name.strip())
    db.add(row)
    db.flush()
    for tag_id in payload.course_tag_ids:
        db.add(TeacherCourseTag(teacher_id=row.id, course_tag_id=tag_id))
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/teachers/{teacher_id}")
def update_teacher(teacher_id: int, payload: TeacherIn, db: Session = Depends(get_db)):
    row = db.get(Teacher, teacher_id)
    if not row:
        raise HTTPException(status_code=404, detail="Teacher not found.")
    row.name = payload.name.strip()  # type: ignore
    db.query(TeacherCourseTag).filter(TeacherCourseTag.teacher_id == teacher_id).delete(synchronize_session=False)
    for tag_id in payload.course_tag_ids:
        db.add(TeacherCourseTag(teacher_id=teacher_id, course_tag_id=tag_id))
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/teachers/{teacher_id}")
def delete_teacher(teacher_id: int, db: Session = Depends(get_db)):
    row = db.get(Teacher, teacher_id)
    if not row:
        raise HTTPException(status_code=404, detail="Teacher not found.")
    if db.scalar(select(ScheduledClass.id).where(ScheduledClass.teacher_id == teacher_id).limit(1)):
        raise HTTPException(status_code=400, detail="Teacher is used by one or more scheduled classes.")
    db.query(TeacherCourseTag).filter(TeacherCourseTag.teacher_id == teacher_id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/courses")
def create_course(payload: CourseIn, db: Session = Depends(get_db)):
    if payload.require_all and payload.elective:
        raise HTTPException(status_code=400, detail="Course cannot be both require-all and elective.")
    row = Course(
        code=payload.code.strip().upper(),
        name=payload.name.strip(),
        course_tag_id=payload.course_tag_id,
        require_all_student_in_group=payload.require_all,
        elective=payload.elective,
    )
    db.add(row)
    db.flush()
    for pid in payload.study_program_ids:
        db.add(StudyProgramCourse(study_program_id=pid, course_id=row.id))
    db.commit()
    return bootstrap_payload(db)


@app.put("/api/courses/{course_id}")
def update_course(course_id: int, payload: CourseIn, db: Session = Depends(get_db)):
    if payload.require_all and payload.elective:
        raise HTTPException(status_code=400, detail="Course cannot be both require-all and elective.")
    row = db.get(Course, course_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course not found.")
    row.code = payload.code.strip().upper()  # type: ignore
    row.name = payload.name.strip()  # type: ignore
    row.course_tag_id = payload.course_tag_id  # type: ignore
    row.require_all_student_in_group = payload.require_all  # type: ignore
    row.elective = payload.elective  # type: ignore
    db.query(StudyProgramCourse).filter(StudyProgramCourse.course_id == course_id).delete(synchronize_session=False)
    for pid in payload.study_program_ids:
        db.add(StudyProgramCourse(study_program_id=pid, course_id=course_id))
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db)):
    row = db.get(Course, course_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course not found.")
    if db.scalar(select(ScheduledClass.id).where(ScheduledClass.course_id == course_id).limit(1)) or db.scalar(select(CourseForGroupTag.id).where(CourseForGroupTag.course_id == course_id).limit(1)):
        raise HTTPException(status_code=400, detail="Course is used by classes or requirements.")
    db.query(StudyProgramCourse).filter(StudyProgramCourse.course_id == course_id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/groups")
def create_group(payload: GroupCreateIn, db: Session = Depends(get_db)):
    if not db.get(Timetable, payload.timetable_id):
        raise HTTPException(status_code=404, detail="Timetable not found.")
    if db.scalar(select(Group.id).where(Group.timetable_id == payload.timetable_id, Group.code == payload.code.upper()).limit(1)):
        raise HTTPException(status_code=400, detail="Group code already exists in this timetable.")
    sort_order = payload.sort_order
    if sort_order is None:
        max_order = db.scalar(select(func.max(Group.sort_order)).where(Group.timetable_id == payload.timetable_id))
        sort_order = int(max_order or 0) + 1
    row = Group(
        timetable_id=payload.timetable_id,
        group_tag_id=payload.group_tag_id,
        code=payload.code.upper(),
        name=payload.name or payload.code.upper(),
        size_num=payload.capacity,
        sort_order=sort_order,
    )
    db.add(row)
    db.flush()
    _apply_group_payload(row, payload, db)
    db.commit()
    return bootstrap_payload(db, payload.timetable_id)


@app.put("/api/groups/{group_id}")
def update_group(group_id: int, payload: GroupCreateIn, db: Session = Depends(get_db)):
    row = db.get(Group, group_id)
    if not row:
        raise HTTPException(status_code=404, detail="Group not found.")
    if not db.get(Timetable, payload.timetable_id):
        raise HTTPException(status_code=404, detail="Timetable not found.")
    if db.scalar(select(Group.id).where(Group.timetable_id == payload.timetable_id, Group.code == payload.code.upper(), Group.id != group_id).limit(1)):
        raise HTTPException(status_code=400, detail="Group code already exists in this timetable.")
    row.timetable_id = payload.timetable_id  # type: ignore
    _apply_group_payload(row, payload, db)
    db.commit()
    return bootstrap_payload(db, payload.timetable_id)


@app.post("/api/groups/reorder")
def reorder_groups(payload: GroupOrderIn, db: Session = Depends(get_db)):
    if not payload.group_ids:
        return bootstrap_payload(db)
    groups = db.scalars(select(Group).where(Group.id.in_(payload.group_ids))).all()
    groups_by_id: dict[int, Group] = {int(group.id): group for group in groups}  # type: ignore[assignment]
    for index, group_id in enumerate(payload.group_ids):
        group = groups_by_id.get(group_id)
        if group is not None:
            group.sort_order = index  # type: ignore[assignment]
    db.commit()
    timetable_id = groups[0].timetable_id if groups else None  # type: ignore[assignment]
    return bootstrap_payload(db, timetable_id)  # type: ignore[arg-type]


@app.delete("/api/groups/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db)):
    row = db.get(Group, group_id)
    if not row:
        raise HTTPException(status_code=404, detail="Group not found.")
    def get_int(val: object) -> int:
        if isinstance(val, int):
            return val
        if hasattr(val, 'value'):
            return int(getattr(val, 'value'))
        return int(str(val))
    timetable_id = get_int(row.timetable_id)
    db.query(ScheduledClass).filter(ScheduledClass.group_id == row.id).delete(synchronize_session=False)
    db.query(GroupStudyProgram).filter(GroupStudyProgram.group_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return bootstrap_payload(db, timetable_id)


@app.post("/api/classes")
def add_class(payload: ClassCreateIn, db: Session = Depends(get_db)) -> dict[str, object]:
    course = db.get(Course, payload.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    if not db.get(Timeslot, payload.timeslot_id):
        raise HTTPException(status_code=404, detail="Timeslot not found.")

    mode = payload.mode
    if mode not in {MODE_REQUIRED, MODE_PROGRAM, MODE_ELECTIVE}:
        raise HTTPException(status_code=400, detail="Invalid mode.")
    if mode == MODE_REQUIRED and not bool(course.require_all_student_in_group):
        raise HTTPException(status_code=400, detail="Selected course is not marked as require-all-students.")
    if mode == MODE_PROGRAM and (bool(course.require_all_student_in_group) or bool(course.elective)):
        raise HTTPException(status_code=400, detail="Selected course is not a study-program course.")
    if mode == MODE_ELECTIVE and not bool(course.elective):
        raise HTTPException(status_code=400, detail="Selected course is not an elective.")

    created, errors = create_classes(
        db,
        target_group_ids=payload.target_group_ids,
        timeslot_id=payload.timeslot_id,
        course=course,
        teacher_id=payload.teacher_id,
        room_id=payload.room_id,
        mode=mode,
        study_program_ids=payload.study_program_ids,
        expected_size=payload.expected_size,
        notes=payload.notes,
        source="ui",
        allow_teacher_conflict=getattr(payload, 'allow_teacher_conflict', False),
    )
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    db.commit()
    def get_int(val: object) -> int:
        if isinstance(val, int):
            return val
        if hasattr(val, 'value'):
            return int(getattr(val, 'value'))
        return int(str(val))
    timetable_id: int = get_int(db.scalar(select(Group.timetable_id).where(Group.id == payload.target_group_ids[0])))
    return {"ok": True, "created_count": len(created), "bootstrap": bootstrap_payload(db, timetable_id)}


@app.get("/api/classes/{class_id}")
def get_class(class_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    row = db.get(ScheduledClass, class_id)
    if not row:
        raise HTTPException(status_code=404, detail="Class not found.")
    study_program_id = getattr(row, 'study_program_id', None)
    return {
        "id": row.id,
        "group_id": row.group_id,
        "group_code": getattr(row.group, 'code', ''),
        "timeslot_id": row.timeslot_id,
        "timeslot_label": getattr(row.timeslot, 'label', ''),
        "course_id": row.course_id,
        "teacher_id": row.teacher_id,
        "room_id": row.room_id,
        "mode": MODE_ELECTIVE if bool(row.course.elective) else (MODE_REQUIRED if bool(row.course.require_all_student_in_group) else MODE_PROGRAM),
        "study_program_ids": [study_program_id] if study_program_id is not None else [],
        "expected_size": row.expected_size,
        "notes": row.notes,
    }


@app.put("/api/classes/{class_id}")
def update_class(class_id: int, payload: ClassCreateIn, db: Session = Depends(get_db)) -> Dict[str, Any]:
    row = db.get(ScheduledClass, class_id)
    if not row:
        raise HTTPException(status_code=404, detail="Class not found.")
    course = db.get(Course, payload.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    if not db.get(Timeslot, payload.timeslot_id):
        raise HTTPException(status_code=404, detail="Timeslot not found.")

    mode = payload.mode
    if mode not in {MODE_REQUIRED, MODE_PROGRAM, MODE_ELECTIVE}:
        raise HTTPException(status_code=400, detail="Invalid mode.")
    if mode == MODE_REQUIRED and not bool(course.require_all_student_in_group):
        raise HTTPException(status_code=400, detail="Selected course is not marked as require-all-students.")
    if mode == MODE_PROGRAM and (bool(course.require_all_student_in_group) or bool(course.elective)):
        raise HTTPException(status_code=400, detail="Selected course is not a study-program course.")
    if mode == MODE_ELECTIVE and not bool(course.elective):
        raise HTTPException(status_code=400, detail="Selected course is not an elective.")
    if mode == MODE_PROGRAM and len(payload.study_program_ids) != 1:
        raise HTTPException(status_code=400, detail="Editing a program class must select exactly one study program.")

    candidate_rows = [row]
    if getattr(row, 'study_program_id', None) is not None:
        candidate_rows = db.query(ScheduledClass).join(Group).filter(
            ScheduledClass.timeslot_id == row.timeslot_id,
            ScheduledClass.course_id == row.course_id,
            Group.timetable_id == row.group.timetable_id,
            ScheduledClass.deploy.is_(True),
            ScheduledClass.study_program_id.isnot(None),
        ).all()

    target_group_ids = [cast(int, row.group_id)]
    rows = [row]
    is_program_edit = mode == MODE_PROGRAM and getattr(row, 'study_program_id', None) is not None
    old_teacher_id = row.teacher_id
    old_room_id = row.room_id
    changing_teacher = payload.teacher_id is not None and payload.teacher_id != old_teacher_id
    changing_room = payload.room_id is not None and payload.room_id != old_room_id

    if mode == MODE_REQUIRED and len(target_group_ids) > 1:
        raise HTTPException(status_code=400, detail="Require-all-students classes must be edited one group at a time.")

    if is_program_edit and changing_teacher and changing_room:
        raise HTTPException(
            status_code=400,
            detail="For program classes, change only teacher or room in one edit command, not both."
        )

    custom_bulk_update = False
    if is_program_edit and len(candidate_rows) > 1 and (changing_teacher or changing_room):
        if changing_teacher:
            if any(r.room_id != old_room_id for r in candidate_rows):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot bulk update teacher because other same-course program classes use a different room in this timeslot. Change only the teacher or update individually."
                )
        if changing_room:
            if any(r.teacher_id != old_teacher_id for r in candidate_rows):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot bulk update room because other same-course program classes use a different teacher in this timeslot. Change only the room or update individually."
                )

        rows = candidate_rows
        target_group_ids = [cast(int, r.group_id) for r in rows]
        custom_bulk_update = True

    for r in rows:
        setattr(r, 'deploy', False)
    db.flush()

    try:
        if custom_bulk_update:
            errors: List[str] = []
            if changing_teacher:
                existing_conflict = db.scalar(
                    select(func.count())
                    .where(
                        ScheduledClass.deploy.is_(True),
                        ScheduledClass.timeslot_id == payload.timeslot_id,
                        ScheduledClass.teacher_id == payload.teacher_id,
                        ScheduledClass.id.notin_([r.id for r in rows]),
                    )
                )
                if existing_conflict:
                    errors.append('Teacher conflict prevents bulk teacher update for this timeslot.')
            if changing_room:
                existing_conflict = db.scalar(
                    select(func.count())
                    .where(
                        ScheduledClass.deploy.is_(True),
                        ScheduledClass.timeslot_id == payload.timeslot_id,
                        ScheduledClass.room_id == payload.room_id,
                        ScheduledClass.id.notin_([r.id for r in rows]),
                    )
                )
                if existing_conflict:
                    errors.append('Room is already occupied in this timeslot; cannot bulk update room.')
        else:
            errors = validate_new_class(
                db,
                target_group_ids=target_group_ids,
                timeslot_id=payload.timeslot_id,
                course=course,
                teacher_id=payload.teacher_id,
                room_id=payload.room_id,
                mode=mode,
                study_program_ids=payload.study_program_ids,
                expected_size=payload.expected_size,
                allow_teacher_conflict=getattr(payload, 'allow_teacher_conflict', False),
            )
    finally:
        for r in rows:
            setattr(r, 'deploy', True)
        db.flush()

    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    for r in rows:
        r.timeslot_id = payload.timeslot_id  # type: ignore
        if custom_bulk_update:
            if changing_teacher:
                r.teacher_id = payload.teacher_id  # type: ignore
            if changing_room:
                r.room_id = payload.room_id  # type: ignore
        else:
            r.course_id = payload.course_id  # type: ignore
            r.teacher_id = payload.teacher_id  # type: ignore
            r.room_id = payload.room_id  # type: ignore
            r.study_program_id = payload.study_program_ids[0] if payload.study_program_ids else None  # type: ignore
        r.expected_size = payload.expected_size  # type: ignore
        r.notes = payload.notes  # type: ignore
    db.commit()

    def get_int(val: object) -> int:
        if isinstance(val, int):
            return val
        if hasattr(val, 'value'):
            return int(getattr(val, 'value'))
        return int(str(val))
    timetable_id = get_int(row.group.timetable_id)
    return {"ok": True, "bootstrap": bootstrap_payload(db, timetable_id)}


@app.delete("/api/classes/{class_id}")
def delete_class(class_id: int, db: Session = Depends(get_db)):
    row = db.get(ScheduledClass, class_id)
    if not row:
        raise HTTPException(status_code=404, detail="Class not found.")
    def get_int(val: object) -> int:
        if isinstance(val, int):
            return val
        if hasattr(val, 'value'):
            return int(getattr(val, 'value'))
        return int(str(val))
    timetable_id = get_int(row.group.timetable_id)
    from typing import cast
    shared_key = cast(Optional[str], row.shared_key)
    if shared_key is not None:
        db.query(ScheduledClass).filter(ScheduledClass.shared_key == shared_key).delete(synchronize_session=False)
    else:
        db.delete(row)
    db.commit()
    return bootstrap_payload(db, timetable_id)


@app.post("/api/group-only-requirements")
def add_group_only_requirement(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    group_ids = _parse_int_list(payload.get("group_ids") or payload.get("group_id"))
    course_id_value = payload.get("course_id")
    if course_id_value is None:
        raise HTTPException(status_code=400, detail="Group(s) and course are required.")
    try:
        course_id = int(course_id_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid course id.")
    sessions_required = int(payload.get("sessions_required", 1))
    if not group_ids:
        raise HTTPException(status_code=400, detail="Group(s) and course are required.")
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    timetable_id = None
    for group_id in group_ids:
        group = db.get(Group, group_id)
        if not group:
            raise HTTPException(status_code=404, detail=f"Group {group_id} not found.")
        existing = db.scalar(
            select(CourseForGroup)
            .where(CourseForGroup.group_id == group_id, CourseForGroup.course_id == course_id)
            .limit(1)
        )
        if existing:
            existing.sessions_required = sessions_required  # type: ignore
        else:
            db.add(CourseForGroup(group_id=group_id, course_id=course_id, sessions_required=sessions_required))
        timetable_id = getattr(group, 'timetable_id', timetable_id)
    db.commit()
    return bootstrap_payload(db, int(timetable_id) if timetable_id is not None else None)


@app.patch("/api/group-only-requirements/{requirement_id}")
def update_group_only_requirement(requirement_id: int, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    row = db.get(CourseForGroup, requirement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Group-only requirement not found.")
    sessions_required = payload.get("sessions_required")
    if sessions_required is not None:
        row.sessions_required = sessions_required
    db.commit()
    timetable_id = getattr(row.group, 'timetable_id', None)
    return bootstrap_payload(db, int(timetable_id) if timetable_id is not None else None)


@app.delete("/api/group-only-requirements/{requirement_id}")
def delete_group_only_requirement(requirement_id: int, db: Session = Depends(get_db)):
    row = db.get(CourseForGroup, requirement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Group-only requirement not found.")
    timetable_id = getattr(row.group, 'timetable_id', None)
    db.delete(row)
    db.commit()
    return bootstrap_payload(db, int(timetable_id) if timetable_id is not None else None)


@app.get("/export.xlsx")
def export_file(
    timetable_id: Optional[int] = Query(default=None),
    program_id: Optional[int] = Query(default=None),
    program_ids: Optional[List[int]] = Query(default=None),
    db: Session = Depends(get_db),
):
    timetable = _selected_timetable(db, timetable_id)
    if not timetable:
        raise HTTPException(status_code=404, detail="No timetable found.")

    selected_group_ids: Optional[List[int]] = None
    selected_program = None
    selected_programs: Optional[List[StudyProgram]] = None
    if program_ids is not None:
        selected_programs = list(db.scalars(select(StudyProgram).where(StudyProgram.id.in_(program_ids))).all())
        if not selected_programs:
            raise HTTPException(status_code=404, detail="Selected study programs not found.")
        selected_group_ids = [int(gid) for gid in db.scalars(
            select(Group.id)
            .join(GroupStudyProgram)
            .where(Group.timetable_id == timetable.id, GroupStudyProgram.study_program_id.in_(program_ids))
            .distinct()
        ).all()]
        if not selected_group_ids:
            raise HTTPException(status_code=404, detail="No groups found for the selected study programs in this timetable.")
    elif program_id is not None:
        selected_program = db.get(StudyProgram, program_id)
        if not selected_program:
            raise HTTPException(status_code=404, detail="Study program not found.")
        selected_group_ids = [int(gid) for gid in db.scalars(
            select(Group.id)
            .join(GroupStudyProgram)
            .where(Group.timetable_id == timetable.id, GroupStudyProgram.study_program_id == program_id)
        ).all()]
        if not selected_group_ids:
            raise HTTPException(status_code=404, detail="No groups found for the selected study program in this timetable.")

    # Check requirements are fully deployed for exported groups
    groups = db.execute(
        select(Group)
        .where(Group.timetable_id == timetable.id)
        .options(joinedload(Group.group_tag))
    ).unique().scalars().all()
    if selected_group_ids is not None:
        groups = [group for group in groups if group.id in selected_group_ids]

    for group in groups:
        requirements = db.scalars(
            select(CourseForGroupTag).where(
                CourseForGroupTag.group_tag_id == group.group_tag_id,
                CourseForGroupTag.timetable_id == timetable.id,
            )
        ).all()
        for req in requirements:
            deployed_count = db.scalar(
                select(func.count()).select_from(ScheduledClass)
                .where(
                    ScheduledClass.group_id == group.id,
                    ScheduledClass.course_id == req.course_id,
                    ScheduledClass.deploy.is_(True),
                )
            )
            sessions_required = int(getattr(req, "sessions_required", 0))
            if deployed_count is None or deployed_count < sessions_required:
                course = db.get(Course, req.course_id)
                raise HTTPException(
                    status_code=400,
                    detail=f"Group {group.code} is missing deployed class(es) for required course {course.name if course else req.course_id} (has {deployed_count}, needs {sessions_required})"
                )
        group_specific_requirements = db.scalars(
            select(CourseForGroup).where(CourseForGroup.group_id == group.id)
        ).all()
        for req in group_specific_requirements:
            deployed_count = db.scalar(
                select(func.count()).select_from(ScheduledClass)
                .where(
                    ScheduledClass.group_id == group.id,
                    ScheduledClass.course_id == req.course_id,
                    ScheduledClass.deploy.is_(True),
                )
            )
            sessions_required = int(getattr(req, "sessions_required", 0))
            if deployed_count is None or deployed_count < sessions_required:
                course = db.get(Course, req.course_id)
                raise HTTPException(
                    status_code=400,
                    detail=f"Group {group.code} is missing deployed class(es) for individual required course {course.name if course else req.course_id} (has {deployed_count}, needs {sessions_required})"
                )

    programs = []
    if program_ids is not None:
        programs = selected_programs or []
    elif selected_program is not None:
        programs = [selected_program]
    else:
        programs = db.scalars(select(StudyProgram)).all()
    for program in programs:
        reqs = db.query(StudyProgramCourse).filter(
            StudyProgramCourse.study_program_id == program.id,
            StudyProgramCourse.timetable_id == timetable.id
        ).all()
        if not reqs:
            continue
        if program_ids is not None:
            group_ids = [int(gid) for gid in db.scalars(
                select(GroupStudyProgram.group_id).join(Group).where(
                    GroupStudyProgram.study_program_id == program.id,
                    Group.timetable_id == timetable.id
                )
            ).all()]
        else:
            group_ids = selected_group_ids if selected_group_ids is not None else [int(gid) for gid in db.scalars(
                select(GroupStudyProgram.group_id).join(Group).where(
                    GroupStudyProgram.study_program_id == program.id,
                    Group.timetable_id == timetable.id
                )
            ).all()]
        for req in reqs:
            for group_id in group_ids:
                deployed_count = db.scalar(
                    select(func.count()).select_from(ScheduledClass)
                    .where(
                        ScheduledClass.group_id == group_id,
                        ScheduledClass.course_id == req.course_id,
                        ScheduledClass.study_program_id == program.id,
                        ScheduledClass.deploy.is_(True),
                    )
                )
                sessions_required = int(getattr(req, "sessions_required", 1))
                if deployed_count is None or deployed_count < sessions_required:
                    course = db.get(Course, req.course_id)
                    group = db.get(Group, group_id)
                    raise HTTPException(
                        status_code=400,
                        detail=f"Study program {program.code} group {group.code if group else group_id} missing deployed class for required course {course.name if course else req.course_id}"
                    )

    # Get cycle info for filename
    cycle = timetable.cycle if hasattr(timetable, 'cycle') else db.get(Cycle, timetable.cycle_id)
    # Sanitize cycle name for filename (remove / and other invalid chars)
    import re
    def sanitize_filename(s: str) -> str:
        return re.sub(r'[^\w\-_\. ]', '_', s)
    cycle_name = sanitize_filename(str(getattr(cycle, 'name', f"cycle{timetable.cycle_id}")))
    cycle_year = str(getattr(cycle, 'year_starting', timetable.cycle_id))
    timetable_id = getattr(timetable, 'id', None)
    if timetable_id is None:
        raise HTTPException(status_code=500, detail="Timetable id is unavailable.")
    if program_ids is not None and selected_programs:
        suffix_codes = '_'.join(sanitize_filename(str(prog.code)) for prog in selected_programs)
        program_suffix = f"_programs-{suffix_codes}"
    elif selected_program is not None:
        program_suffix = f"_program-{sanitize_filename(str(getattr(selected_program, 'code', '')))}"
    else:
        program_suffix = "_all-programs"
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    filename = f"timetable_{cycle_name}_{cycle_year}_timetable{timetable_id}{program_suffix}_{timestamp}.xlsx"
    out_path: Path = EXPORT_DIR / filename
    selected_program_ids = (
        list(program_ids)
        if program_ids is not None
        else ([cast(int, getattr(selected_program, 'id'))] if selected_program is not None else None)
    )
    export_timetable_xlsx(db, out_path, timetable_id=timetable_id, study_program_ids=selected_program_ids)
    return FileResponse(
        out_path,
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{out_path.name}"', "X-Download-Filename": out_path.name},
    )
@app.delete("/api/group-tags/{group_tag_id}/requirements/{course_id}")
def delete_group_tag_requirement(group_tag_id: int, course_id: int, db: Session = Depends(get_db)):
    timetable_id = _current_timetable_id(db)
    row = db.query(CourseForGroupTag).filter(
        CourseForGroupTag.group_tag_id == group_tag_id,
        CourseForGroupTag.course_id == course_id,
        CourseForGroupTag.timetable_id == timetable_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)

@app.delete("/api/study-programs/{program_id}/requirements/{course_id}")
def delete_study_program_requirement(program_id: int, course_id: int, db: Session = Depends(get_db)):
    timetable_id = _current_timetable_id(db)
    row = db.query(StudyProgramCourse).filter(
        StudyProgramCourse.study_program_id == program_id,
        StudyProgramCourse.course_id == course_id,
        StudyProgramCourse.timetable_id == timetable_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    db.delete(row)
    db.commit()
    return bootstrap_payload(db)

@app.post("/api/group-tags/{group_tag_id}/requirements")
def add_group_tag_requirement(group_tag_id: int, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    course_id_value = payload.get("course_id")
    if course_id_value is None:
        raise HTTPException(status_code=400, detail="Course is required.")
    try:
        course_id = int(course_id_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid course id.")
    sessions_required = int(payload.get("sessions_required", 1))
    timetable_id = payload.get("timetable_id")
    if timetable_id is None:
        timetable = db.scalar(select(Timetable).where(Timetable.in_action.is_(True)).order_by(Timetable.id).limit(1))
        if timetable:
            timetable_id = getattr(timetable, 'id', None)
    if timetable_id is None:
        timetable_id = db.scalar(select(Timetable.id).order_by(Timetable.id.desc()).limit(1))
    if timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    if not db.get(GroupTag, group_tag_id):
        raise HTTPException(status_code=404, detail="Group tag not found.")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found.")
    req = db.query(CourseForGroupTag).filter(
        CourseForGroupTag.group_tag_id == group_tag_id,
        CourseForGroupTag.course_id == course_id,
        CourseForGroupTag.timetable_id == timetable_id
    ).first()
    if req:
        req.sessions_required = sessions_required
    else:
        db.add(CourseForGroupTag(group_tag_id=group_tag_id, course_id=course_id, sessions_required=sessions_required, timetable_id=timetable_id))
    db.commit()
    return bootstrap_payload(db)

@app.post("/api/group-tags/requirements")
def add_group_tag_requirements(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    group_tag_ids = _parse_int_list(payload.get("group_tag_ids"))
    course_id_value = payload.get("course_id")
    if course_id_value is None:
        raise HTTPException(status_code=400, detail="Group tag(s) and course are required.")
    try:
        course_id = int(course_id_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid course id.")
    sessions_required = int(payload.get("sessions_required", 1))
    timetable_id = payload.get("timetable_id")
    if timetable_id is None:
        timetable = db.scalar(select(Timetable).where(Timetable.in_action.is_(True)).order_by(Timetable.id).limit(1))
        if timetable:
            timetable_id = getattr(timetable, 'id', None)
    if timetable_id is None:
        timetable_id = db.scalar(select(Timetable.id).order_by(Timetable.id.desc()).limit(1))
    if timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    if not group_tag_ids:
        raise HTTPException(status_code=400, detail="Group tag(s) and course are required.")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found.")
    for group_tag_id in group_tag_ids:
        if not db.get(GroupTag, group_tag_id):
            raise HTTPException(status_code=404, detail=f"Group tag {group_tag_id} not found.")
        req = db.query(CourseForGroupTag).filter(
            CourseForGroupTag.group_tag_id == group_tag_id,
            CourseForGroupTag.course_id == course_id,
            CourseForGroupTag.timetable_id == timetable_id
        ).first()
        if req:
            req.sessions_required = sessions_required
        else:
            db.add(CourseForGroupTag(group_tag_id=group_tag_id, course_id=course_id, sessions_required=sessions_required, timetable_id=timetable_id))
    db.commit()
    return bootstrap_payload(db)

@app.post("/api/study-programs/{program_id}/requirements")
def add_study_program_requirement(program_id: int, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    course_id_value = payload.get("course_id")
    if course_id_value is None:
        raise HTTPException(status_code=400, detail="Course is required.")
    try:
        course_id = int(course_id_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid course id.")
    sessions_required = int(payload.get("sessions_required", 1))
    timetable_id = payload.get("timetable_id")
    if timetable_id is None:
        timetable = db.scalar(select(Timetable).where(Timetable.in_action.is_(True)).order_by(Timetable.id).limit(1))
        if timetable:
            timetable_id = getattr(timetable, 'id', None)
    if timetable_id is None:
        timetable_id = db.scalar(select(Timetable.id).order_by(Timetable.id.desc()).limit(1))
    if timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    if not db.get(StudyProgram, program_id):
        raise HTTPException(status_code=404, detail="Study program not found.")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found.")
    req = db.query(StudyProgramCourse).filter(
        StudyProgramCourse.study_program_id == program_id,
        StudyProgramCourse.course_id == course_id,
        StudyProgramCourse.timetable_id == timetable_id
    ).first()
    if req:
        req.sessions_required = sessions_required
    else:
        db.add(StudyProgramCourse(
            study_program_id=program_id,
            course_id=course_id,
            timetable_id=timetable_id,
            sessions_required=sessions_required,
        ))
    db.commit()
    return bootstrap_payload(db)

@app.post("/api/study-programs/requirements")
def add_study_program_requirements(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    study_program_ids = _parse_int_list(payload.get("study_program_ids"))
    course_id_value = payload.get("course_id")
    if course_id_value is None:
        raise HTTPException(status_code=400, detail="Study program(s) and course are required.")
    try:
        course_id = int(course_id_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid course id.")
    timetable_id = payload.get("timetable_id")
    if timetable_id is None:
        timetable = db.scalar(select(Timetable).where(Timetable.in_action.is_(True)).order_by(Timetable.id).limit(1))
        if timetable:
            timetable_id = getattr(timetable, 'id', None)
    if timetable_id is None:
        timetable_id = db.scalar(select(Timetable.id).order_by(Timetable.id.desc()).limit(1))
    if timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    sessions_required = int(payload.get("sessions_required", 1))
    if not study_program_ids or not course_id:
        raise HTTPException(status_code=400, detail="Study program(s) and course are required.")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found.")
    for study_program_id in study_program_ids:
        if not db.get(StudyProgram, study_program_id):
            raise HTTPException(status_code=404, detail=f"Study program {study_program_id} not found.")
        req = db.query(StudyProgramCourse).filter(
            StudyProgramCourse.study_program_id == study_program_id,
            StudyProgramCourse.course_id == course_id,
            StudyProgramCourse.timetable_id == timetable_id
        ).first()
        if req:
            req.sessions_required = sessions_required
        else:
            db.add(StudyProgramCourse(
                study_program_id=study_program_id,
                course_id=course_id,
                timetable_id=timetable_id,
                sessions_required=sessions_required,
            ))
    db.commit()
    return bootstrap_payload(db)