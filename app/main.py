from __future__ import annotations

from collections import defaultdict
import time
from pathlib import Path
from typing import Any, Iterable, cast, Dict, List, Optional
from fastapi import Body, Depends, FastAPI, HTTPException, Query, UploadFile, File
from contextlib import asynccontextmanager
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from contextlib import asynccontextmanager
from .database import SessionLocal, get_db
from .excel_exporter import export_timetable_xlsx
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet
import io
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



def _ensure_german_timeslots(db: Session) -> None:
    german_rows = [
        ("MONDAY", 1, "8.45", "10.15", "German 8.45 - 10.15", 11),
        ("MONDAY", 1, "10.30", "12.00", "German 10.30 - 12.00", 12),
        ("MONDAY", 1, "13.00", "14.30", "German 13.00 - 14.30", 13),
        ("MONDAY", 1, "14.45", "16.15", "German 14.45 - 16.15", 14),
        ("TUESDAY", 2, "8.45", "10.15", "German 8.45 - 10.15", 15),
        ("TUESDAY", 2, "10.30", "12.00", "German 10.30 - 12.00", 16),
        ("TUESDAY", 2, "13.00", "14.30", "German 13.00 - 14.30", 17),
        ("TUESDAY", 2, "14.45", "16.15", "German 14.45 - 16.15", 18),
        ("WEDNESDAY", 3, "8.45", "10.15", "German 8.45 - 10.15", 19),
        ("WEDNESDAY", 3, "10.30", "12.00", "German 10.30 - 12.00", 20),
        ("WEDNESDAY", 3, "13.00", "14.30", "German 13.00 - 14.30", 21),
        ("WEDNESDAY", 3, "14.45", "16.15", "German 14.45 - 16.15", 22),
        ("THURSDAY", 4, "8.45", "10.15", "German 8.45 - 10.15", 23),
        ("THURSDAY", 4, "10.30", "12.00", "German 10.30 - 12.00", 24),
        ("THURSDAY", 4, "13.00", "14.30", "German 13.00 - 14.30", 25),
        ("THURSDAY", 4, "14.45", "16.15", "German 14.45 - 16.15", 26),
        ("FRIDAY", 5, "8.45", "10.15", "German 8.45 - 10.15", 27),
        ("FRIDAY", 5, "10.30", "12.00", "German 10.30 - 12.00", 28),
        ("FRIDAY", 5, "13.00", "14.30", "German 13.00 - 14.30", 29),
        ("FRIDAY", 5, "14.45", "16.15", "German 14.45 - 16.15", 30),
    ]
    existing_sort_orders = set(db.scalars(select(Timeslot.sort_order).where(Timeslot.sort_order.in_([row[5] for row in german_rows]))).all())
    for weekday, day_index, start_time, end_time, label, sort_order in german_rows:
        if sort_order in existing_sort_orders:
            continue
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
    if len(existing_sort_orders) < len(german_rows):
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):  # Added type annotation
    ensure_database()
    _ensure_default_timeslots()
    yield

app = FastAPI(title="Timetable Builder", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.exception_handler(IntegrityError)
def integrity_error_handler(request: Request, exc: IntegrityError):
    detail = str(exc.orig) if getattr(exc, 'orig', None) else str(exc)
    return JSONResponse(status_code=400, content={"detail": detail})


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    cycles = db.scalars(select(Cycle).order_by(Cycle.year_starting.desc(), Cycle.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"cycles": cycles, "version": int(time.time())},
        media_type="text/html; charset=utf-8",
    )


@app.get("/cycle/{cycle_id}", response_class=HTMLResponse)
def cycle_page(cycle_id: int, request: Request, db: Session = Depends(get_db)):
    if not db.get(Cycle, cycle_id):
        raise HTTPException(status_code=404, detail="Cycle not found.")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"version": int(time.time()), "selected_cycle_id": cycle_id},
        media_type="text/html; charset=utf-8",
    )


def render_entity_page(request: Request, section: str, open_new: bool = False, cycle_id: Optional[int] = None) -> HTMLResponse:
    template_name = {
        "teachers": "teachers.html",
        "rooms": "rooms.html",
        "courses": "courses.html",
        "study-programs": "study-programs.html",
        "course-tags": "course-tags.html",
        "group-tags": "group-tags.html",
        "upload": "upload.html",
        "data-sync": "data_sync.html",
    }.get(section, "entity.html")
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"version": int(time.time()), "selected_cycle_id": cycle_id, "active_section": section, "open_new": open_new, "template_name": template_name},
        media_type="text/html; charset=utf-8",
    )


@app.get("/teachers", response_class=HTMLResponse)
def teachers_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "teachers", False, cycle_id)


@app.get("/teachers/new", response_class=HTMLResponse)
def teachers_new_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "teachers", True, cycle_id)


@app.get("/rooms", response_class=HTMLResponse)
def rooms_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "rooms", False, cycle_id)


@app.get("/rooms/new", response_class=HTMLResponse)
def rooms_new_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "rooms", True, cycle_id)


@app.get("/courses", response_class=HTMLResponse)
def courses_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "courses", False, cycle_id)


@app.get("/courses/new", response_class=HTMLResponse)
def courses_new_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "courses", True, cycle_id)


@app.get("/study-programs", response_class=HTMLResponse)
def programs_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "study-programs", False, cycle_id)


@app.get("/study-programs/new", response_class=HTMLResponse)
def programs_new_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "study-programs", True, cycle_id)


@app.get("/course-tags", response_class=HTMLResponse)
def course_tags_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "course-tags", False, cycle_id)


@app.get("/course-tags/new", response_class=HTMLResponse)
def course_tags_new_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "course-tags", True, cycle_id)


@app.get("/group-tags", response_class=HTMLResponse)
def group_tags_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "group-tags", False, cycle_id)


@app.get("/group-tags/new", response_class=HTMLResponse)
def group_tags_new_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "group-tags", True, cycle_id)


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "upload", False, cycle_id)

@app.get("/data-sync", response_class=HTMLResponse)
def data_sync_page(request: Request, cycle_id: Optional[int] = Query(default=None)):
    return render_entity_page(request, "data-sync", False, cycle_id)


def _selected_timetable(db: Session, timetable_id: Optional[int], cycle_id: Optional[int] = None) -> Optional[Timetable]:
    if timetable_id:
        timetable = db.get(Timetable, timetable_id)
        if timetable:
            return timetable
    if cycle_id is not None:
        return db.scalar(select(Timetable).where(Timetable.cycle_id == cycle_id).order_by(Timetable.id.desc()))
    return db.scalar(select(Timetable).order_by(Timetable.id.desc()))


def _current_timetable_id(db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> Optional[int]:
    if timetable_id is not None:
        return timetable_id
    timetable = _selected_timetable(db, None, cycle_id)
    return getattr(timetable, 'id', None)


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    if any(seq in text for seq in ['â€”', 'â€“', 'â€œ', 'â€�', 'â€™', 'Ã©', 'Ã ', 'Ã¨', 'Ãª', 'Ã§', 'Ã±', 'Ã´']):
        try:
            fixed = text.encode('latin1').decode('utf-8')
            return fixed
        except Exception:
            pass
    replacements = {
        'â€”': '—',
        'â€“': '–',
        'â€œ': '“',
        'â€�': '”',
        'â€™': '’',
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def _normalize_str(value: Any) -> str:
    if value is None:
        return ''
    return _sanitize_text(value)


def _split_codes(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(',') if part.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in cast(Iterable[Any], value) if item is not None and str(item).strip()]
    return [str(value).strip()]


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {'1', 'true', 'yes', 'y', 'on'}


def _parse_int(value: Any) -> Optional[int]:
    if value is None or str(value).strip() == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_template_workbook(entity: str) -> Workbook:
    workbook = Workbook()
    ws: Worksheet = cast(Worksheet, workbook.active)
    title = entity.replace('-', ' ').title()
    ws.title = title[:31]
    if entity == 'teachers':
        ws.append(['Name', 'Course Tag Names (comma-separated)'])
    elif entity == 'study-programs':
        ws.append(['Code', 'Name'])
    elif entity == 'courses':
        ws.append(['Code', 'Name', 'Course Tag Name', 'Require All (True/False)', 'Elective (True/False)', 'Study Program Codes (comma-separated)'])
    elif entity == 'course-tags':
        ws.append(['Name'])
    elif entity == 'rooms':
        ws.append(['Code', 'Name', 'Capacity'])
    elif entity == 'group-tags':
        ws.append(['Code', 'Name'])
    elif entity == 'groups':
        ws.append(['Code', 'Name', 'Group Tag Code', 'Study Program Codes (comma-separated)', 'Capacity', 'Sort Order (optional)'])
    elif entity == 'requirements':
        ws.append(['Requirement Type (group_tag, program, or group_only)', 'Target Code', 'Course Code', 'Sessions Required'])
    else:
        raise HTTPException(status_code=404, detail='Template not found.')
    return workbook


def _build_current_data_workbook(entity: str, db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> Workbook:
    workbook = Workbook()
    ws: Worksheet = cast(Worksheet, workbook.active)
    title = entity.replace('-', ' ').title()
    ws.title = title[:31]
    tt_id = None
    if entity in {'courses', 'groups', 'requirements'}:
        tt_id = _current_timetable_id(db, timetable_id, cycle_id)
    if entity == 'teachers':
        ws.append(['Id', 'Name', 'Course Tag Names (comma-separated)'])
        teachers = db.scalars(select(Teacher).order_by(Teacher.id)).all()
        for teacher in teachers:
            tags = [link.course_tag.name for link in teacher.course_tag_links if link.course_tag]
            ws.append([teacher.id, teacher.name, ', '.join(tags)])
    elif entity == 'study-programs':
        ws.append(['Id', 'Code', 'Name'])
        programs = db.scalars(select(StudyProgram).order_by(StudyProgram.id)).all()
        for program in programs:
            ws.append([program.id, program.code, program.name])
    elif entity == 'courses':
        ws.append(['Id', 'Code', 'Name', 'Course Tag Name', 'Require All (True/False)', 'Elective (True/False)', 'Study Program Codes (comma-separated)'])
        query = select(Course).order_by(Course.id)
        if tt_id is not None:
            query = query.options(joinedload(Course.study_program_links).joinedload(StudyProgramCourse.study_program))
        courses = db.scalars(query).unique().all()
        for course in courses:
            if tt_id is not None:
                programs = [link.study_program.code for link in course.study_program_links if link.study_program and getattr(link, 'timetable_id', None) == tt_id]
            else:
                programs = [link.study_program.code for link in course.study_program_links if link.study_program]
            ws.append([course.id, course.code, course.name, course.course_tag.name if course.course_tag else '', course.require_all_student_in_group, course.elective, ', '.join(programs)])
    elif entity == 'course-tags':
        ws.append(['Id', 'Name'])
        tags = db.scalars(select(CourseTag).order_by(CourseTag.id)).all()
        for tag in tags:
            ws.append([tag.id, tag.name])
    elif entity == 'rooms':
        ws.append(['Id', 'Code', 'Name', 'Capacity'])
        rooms = db.scalars(select(Room).order_by(Room.id)).all()
        for room in rooms:
            ws.append([room.id, room.code, room.name, room.capacity_num])
    elif entity == 'group-tags':
        ws.append(['Id', 'Code', 'Name'])
        tags = db.scalars(select(GroupTag).order_by(GroupTag.id)).all()
        for tag in tags:
            ws.append([tag.id, tag.code, tag.name])
    elif entity == 'groups':
        ws.append(['Id', 'Timetable Id', 'Code', 'Name', 'Group Tag Code', 'Study Program Codes (comma-separated)', 'Capacity', 'Sort Order'])
        query = select(Group).order_by(Group.id).options(joinedload(Group.study_program_links).joinedload(GroupStudyProgram.study_program), joinedload(Group.group_tag))
        if tt_id is not None:
            query = query.where(Group.timetable_id == tt_id)
        groups = db.scalars(query).unique().all()
        for group in groups:
            programs = [link.study_program.code for link in group.study_program_links if link.study_program]
            ws.append([group.id, group.timetable_id, group.code, group.name, group.group_tag.code if group.group_tag else '', ', '.join(programs), group.size_num, group.sort_order])
    elif entity == 'requirements':
        ws.append(['Id', 'Requirement Type (group_tag, program, or group_only)', 'Timetable Id', 'Target Code', 'Course Code', 'Sessions Required'])
        group_requirements = cast(List[CourseForGroupTag], db.scalars(select(CourseForGroupTag).options(joinedload(CourseForGroupTag.group_tag), joinedload(CourseForGroupTag.course)).order_by(CourseForGroupTag.id)).all())
        if tt_id is not None:
            group_requirements = [req for req in group_requirements if cast(Optional[int], getattr(req, 'timetable_id', None)) == tt_id]
        for req in group_requirements:
            ws.append([req.id, 'group_tag', req.timetable_id, req.group_tag.code if req.group_tag else '', req.course.code if req.course else '', req.sessions_required])
        program_requirements = cast(List[StudyProgramCourse], db.scalars(select(StudyProgramCourse).options(joinedload(StudyProgramCourse.study_program), joinedload(StudyProgramCourse.course)).order_by(StudyProgramCourse.id)).all())
        if tt_id is not None:
            program_requirements = [req for req in program_requirements if cast(Optional[int], getattr(req, 'timetable_id', None)) == tt_id]
        for req in program_requirements:
            ws.append([req.id, 'program', req.timetable_id, req.study_program.code if req.study_program else '', req.course.code if req.course else '', req.sessions_required])
        group_only_requirements = cast(List[CourseForGroup], db.scalars(select(CourseForGroup).options(joinedload(CourseForGroup.group), joinedload(CourseForGroup.course)).order_by(CourseForGroup.id)).all())
        if tt_id is not None:
            group_only_requirements = [req for req in group_only_requirements if req.group and req.group.timetable_id == tt_id]
        for req in group_only_requirements:
            ws.append([req.id, 'group_only', req.group.timetable_id if req.group else '', req.group.code if req.group else '', req.course.code if req.course else '', req.sessions_required])
    else:
        raise HTTPException(status_code=404, detail='Export entity not found.')
    return workbook


def _template_response(workbook: Workbook, filename: str) -> StreamingResponse:
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
    )


def _current_data_response(workbook: Workbook, filename: str) -> StreamingResponse:
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
    )


def _read_excel_rows(upload_file: UploadFile) -> List[Dict[str, Any]]:
    try:
        upload_file.file.seek(0)
        workbook = load_workbook(upload_file.file, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid Excel file.')
    sheet: Worksheet = cast(Worksheet, workbook.active)
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(cell).strip() if cell is not None else '' for cell in rows[0]]
    if not any(headers):
        raise HTTPException(status_code=400, detail='Excel template is missing header row.')
    result: List[Dict[str, Any]] = []
    for row in rows[1:]:
        if all(cell is None or str(cell).strip() == '' for cell in row):
            continue
        record: Dict[str, Any] = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            record[header] = row[idx] if idx < len(row) else None
        result.append(record)
    return result


def _find_course_tag_id(db: Session, name: str) -> int:
    code = _normalize_str(name)
    tag = db.scalar(select(CourseTag).where(CourseTag.name == code).limit(1))
    if not tag:
        raise HTTPException(status_code=404, detail=f'Course tag not found: {code}')
    return int(getattr(tag, 'id'))


def _find_study_program_id(db: Session, code: str) -> int:
    lookup = _normalize_str(code)
    prog = db.scalar(select(StudyProgram).where(StudyProgram.code == lookup).limit(1))
    if not prog:
        raise HTTPException(status_code=404, detail=f'Study program not found: {lookup}')
    return int(getattr(prog, 'id'))


def _find_group_tag_id(db: Session, code: str) -> int:
    lookup = _normalize_str(code)
    tag = db.scalar(select(GroupTag).where(GroupTag.code == lookup).limit(1))
    if not tag:
        raise HTTPException(status_code=404, detail=f'Group tag not found: {lookup}')
    return int(getattr(tag, 'id'))


def _find_course_id_by_code(db: Session, code: str) -> int:
    lookup = _normalize_str(code)
    course = db.scalar(select(Course).where(Course.code == lookup).limit(1))
    if not course:
        raise HTTPException(status_code=404, detail=f'Course not found: {lookup}')
    return int(getattr(course, 'id'))


def _import_teachers(file: UploadFile, db: Session) -> None:
    rows = _read_excel_rows(file)
    for row in rows:
        teacher_id = _parse_int(row.get('Id'))
        name = _normalize_str(row.get('Name'))
        codes = _split_codes(row.get('Course Tag Names (comma-separated)'))
        teacher = None
        if teacher_id is not None:
            teacher = db.get(Teacher, teacher_id)
            if not teacher:
                raise HTTPException(status_code=404, detail=f'Teacher not found: {teacher_id}')
        if teacher is None and name:
            teacher = cast(Teacher, db.scalar(select(Teacher).where(Teacher.name == name).limit(1)))
        if teacher is None:
            if not name:
                continue
            teacher = Teacher(name=name)
            db.add(teacher)
            db.flush()
        else:
            teacher_name = getattr(teacher, 'name', None)
            if name and teacher_name != name:
                setattr(teacher, 'name', name)
        # update teacher course tags
        existing_tags = {link.course_tag.name for link in teacher.course_tag_links if link.course_tag}
        requested_tags = {code for code in codes if code}
        if existing_tags != requested_tags:
            for link in list(teacher.course_tag_links):
                db.delete(link)
            for code in requested_tags:
                tag_id = _find_course_tag_id(db, code)
                db.add(TeacherCourseTag(teacher_id=teacher.id, course_tag_id=tag_id))
    db.commit()


def _import_study_programs(file: UploadFile, db: Session) -> None:
    rows = _read_excel_rows(file)
    for row in rows:
        program_id = _parse_int(row.get('Id'))
        code = _normalize_str(row.get('Code')).upper()
        name = _normalize_str(row.get('Name'))
        program = None
        if program_id is not None:
            program = db.get(StudyProgram, program_id)
            if not program:
                raise HTTPException(status_code=404, detail=f'Study program not found: {program_id}')
        if program is None and code:
            program = cast(StudyProgram, db.scalar(select(StudyProgram).where(StudyProgram.code == code).limit(1)))
        if program is None:
            if not code or not name:
                continue
            db.add(StudyProgram(code=code, name=name))
        else:
            if code and getattr(program, 'code', None) != code:
                setattr(program, 'code', code)
            if name and getattr(program, 'name', None) != name:
                setattr(program, 'name', name)
    db.commit()


def _import_courses(file: UploadFile, db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> None:
    timetable_id = _current_timetable_id(db, timetable_id, cycle_id)
    if timetable_id is None:
        raise HTTPException(status_code=400, detail='No active timetable found for course import.')
    rows = _read_excel_rows(file)
    for row in rows:
        course_id = _parse_int(row.get('Id'))
        code = _normalize_str(row.get('Code')).upper()
        name = _normalize_str(row.get('Name'))
        course_tag_name = _normalize_str(row.get('Course Tag Name'))
        if not code or not name or not course_tag_name:
            continue
        course = None
        if course_id is not None:
            course = db.get(Course, course_id)
            if not course:
                raise HTTPException(status_code=404, detail=f'Course not found: {course_id}')
        if course is None:
            course = db.scalar(select(Course).where(Course.code == code).limit(1))
        course_tag_id = _find_course_tag_id(db, course_tag_name)
        require_all = _parse_bool(row.get('Require All (True/False)'))
        elective = _parse_bool(row.get('Elective (True/False)'))
        if course is None:
            course = Course(
                code=code,
                name=name,
                course_tag_id=course_tag_id,
                require_all_student_in_group=require_all,
                elective=elective,
            )
            db.add(course)
            db.flush()
        else:
            setattr(course, 'code', code)
            setattr(course, 'name', name)
            setattr(course, 'course_tag_id', course_tag_id)
            setattr(course, 'require_all_student_in_group', require_all)
            setattr(course, 'elective', elective)
        program_codes = list(dict.fromkeys(_split_codes(row.get('Study Program Codes (comma-separated)'))))
        db.query(StudyProgramCourse).filter(StudyProgramCourse.course_id == course.id, StudyProgramCourse.timetable_id == timetable_id).delete()
        for program_code in program_codes:
            if not program_code:
                continue
            program_id = _find_study_program_id(db, program_code)
            db.add(StudyProgramCourse(study_program_id=program_id, course_id=course.id, timetable_id=timetable_id))
    db.commit()


def _import_course_tags(file: UploadFile, db: Session) -> None:
    rows = _read_excel_rows(file)
    for row in rows:
        tag_id = _parse_int(row.get('Id'))
        name = _normalize_str(row.get('Name'))
        course_tag = None
        if tag_id is not None:
            course_tag = db.get(CourseTag, tag_id)
            if not course_tag:
                raise HTTPException(status_code=404, detail=f'Course tag not found: {tag_id}')
        if course_tag is None and name:
            course_tag = cast(CourseTag, db.scalar(select(CourseTag).where(CourseTag.name == name).limit(1)))
        if course_tag is None:
            if not name:
                continue
            db.add(CourseTag(name=name))
        else:
            if name and getattr(course_tag, 'name', None) != name:
                setattr(course_tag, 'name', name)
    db.commit()


def _import_rooms(file: UploadFile, db: Session) -> None:
    rows = _read_excel_rows(file)
    for row in rows:
        room_id = _parse_int(row.get('Id'))
        code = _normalize_str(row.get('Code')).upper()
        name = _normalize_str(row.get('Name'))
        capacity = int(row.get('Capacity') or 0)
        if not code or not name or capacity <= 0:
            continue
        room = None
        if room_id is not None:
            room = db.get(Room, room_id)
            if not room:
                raise HTTPException(status_code=404, detail=f'Room not found: {room_id}')
        if room is None:
            room = db.scalar(select(Room).where(Room.code == code).limit(1))
        if room is None:
            db.add(Room(code=code, name=name, capacity_num=capacity))
        else:
            setattr(room, 'code', code)
            setattr(room, 'name', name)
            setattr(room, 'capacity_num', capacity)
    db.commit()


def _import_group_tags(file: UploadFile, db: Session) -> None:
    rows = _read_excel_rows(file)
    for row in rows:
        group_tag_id = _parse_int(row.get('Id'))
        code = _normalize_str(row.get('Code')).upper()
        name = _normalize_str(row.get('Name'))
        group_tag = None
        if group_tag_id is not None:
            group_tag = db.get(GroupTag, group_tag_id)
            if not group_tag:
                raise HTTPException(status_code=404, detail=f'Group tag not found: {group_tag_id}')
        if group_tag is None and code:
            group_tag = db.scalar(select(GroupTag).where(GroupTag.code == code).limit(1))
        if group_tag is None:
            if not code or not name:
                continue
            db.add(GroupTag(code=code, name=name))
        else:
            if code and getattr(group_tag, 'code', None) != code:
                setattr(group_tag, 'code', code)
            if name and getattr(group_tag, 'name', None) != name:
                setattr(group_tag, 'name', name)
    db.commit()


def _import_groups(file: UploadFile, db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> None:
    rows = _read_excel_rows(file)
    default_timetable_id = _current_timetable_id(db, timetable_id, cycle_id)
    if default_timetable_id is None:
        raise HTTPException(status_code=400, detail='No active timetable found for groups import.')
    for row in rows:
        timetable_id = default_timetable_id
        timetable_value = row.get('Timetable Id (optional)')
        if timetable_value is not None and str(timetable_value).strip() != '':
            try:
                timetable_id = int(timetable_value)
            except (TypeError, ValueError):
                timetable_id = default_timetable_id
        group_id = _parse_int(row.get('Id'))
        code = _normalize_str(row.get('Code')).upper()
        name = _normalize_str(row.get('Name')) or code
        group_tag_code = _normalize_str(row.get('Group Tag Code')).upper()
        if not code or not group_tag_code:
            continue
        group_tag_id = _find_group_tag_id(db, group_tag_code)
        capacity = int(row.get('Capacity') or 1)
        sort_order = None
        sort_value = row.get('Sort Order (optional)')
        if sort_value is not None and str(sort_value).strip() != '':
            try:
                sort_order = int(sort_value)
            except (TypeError, ValueError):
                sort_order = None
        group = None
        if group_id is not None:
            existing_group = db.get(Group, group_id)
            if existing_group is not None and getattr(existing_group, 'timetable_id', None) == timetable_id:
                group = existing_group
        if group is None:
            group = db.scalar(select(Group).where(Group.timetable_id == timetable_id, Group.code == code).limit(1))
        if group is None:
            group = Group(
                timetable_id=timetable_id,
                code=code,
                name=name,
                group_tag_id=group_tag_id,
                size_num=capacity,
                sort_order=sort_order if sort_order is not None else 0,
            )
            db.add(group)
            db.flush()
        else:
            setattr(group, 'timetable_id', timetable_id)
            setattr(group, 'code', code)
            setattr(group, 'name', name)
            setattr(group, 'group_tag_id', group_tag_id)
            setattr(group, 'size_num', capacity)
            setattr(group, 'sort_order', sort_order if sort_order is not None else 0)
        db.query(GroupStudyProgram).filter(GroupStudyProgram.group_id == group.id).delete()
        for program_code in list(dict.fromkeys(_split_codes(row.get('Study Program Codes (comma-separated)')))):
            if not program_code:
                continue
            program_id = _find_study_program_id(db, program_code)
            db.add(GroupStudyProgram(group_id=group.id, study_program_id=program_id))
    db.commit()


def _find_group_id(db: Session, code: str, timetable_id: Optional[int] = None) -> int:
    lookup = _normalize_str(code).upper()
    query = select(Group).where(Group.code == lookup)
    if timetable_id is not None:
        query = query.where(Group.timetable_id == timetable_id)
    group = db.scalar(query.limit(1))
    if not group:
        raise HTTPException(status_code=404, detail=f'Group not found: {lookup}')
    return int(getattr(group, 'id'))


def _import_requirements(file: UploadFile, db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> None:
    rows = _read_excel_rows(file)
    timetable_id = _current_timetable_id(db, timetable_id, cycle_id)
    if timetable_id is None:
        raise HTTPException(status_code=400, detail='No active timetable found for requirements import.')
    for row in rows:
        requirement_id = _parse_int(row.get('Id'))
        req_type = _normalize_str(row.get('Requirement Type (group_tag, program, or group_only)')).lower()
        if not req_type:
            req_type = _normalize_str(row.get('Requirement Type (group_tag or program)')).lower()
        target_code = _normalize_str(row.get('Target Code'))
        course_code = _normalize_str(row.get('Course Code')).upper()
        if not req_type or not target_code or not course_code:
            continue
        course_id = _find_course_id_by_code(db, course_code)
        sessions = int(row.get('Sessions Required') or 1)
        if requirement_id is not None:
            if req_type in {'group_tag', 'group tag'}:
                req = db.get(CourseForGroupTag, requirement_id)
                if not req:
                    raise HTTPException(status_code=404, detail=f'Requirement not found: {requirement_id}')
                setattr(req, 'timetable_id', timetable_id)
                setattr(req, 'group_tag_id', _find_group_tag_id(db, target_code))
                setattr(req, 'course_id', course_id)
                setattr(req, 'sessions_required', sessions)
                continue
            if req_type in {'program', 'study_program', 'study program'}:
                req = db.get(StudyProgramCourse, requirement_id)
                if not req:
                    raise HTTPException(status_code=404, detail=f'Requirement not found: {requirement_id}')
                setattr(req, 'timetable_id', timetable_id)
                setattr(req, 'study_program_id', _find_study_program_id(db, target_code))
                setattr(req, 'course_id', course_id)
                setattr(req, 'sessions_required', sessions)
                continue
            if req_type in {'group_only', 'group-only', 'group only'}:
                req = db.get(CourseForGroup, requirement_id)
                if not req:
                    raise HTTPException(status_code=404, detail=f'Requirement not found: {requirement_id}')
                setattr(req, 'group_id', _find_group_id(db, target_code, timetable_id))
                setattr(req, 'course_id', course_id)
                setattr(req, 'sessions_required', sessions)
                continue
        if req_type in {'group_tag', 'group tag'}:
            group_tag_id = _find_group_tag_id(db, target_code)
            _upsert_group_tag_requirement(db, timetable_id, group_tag_id, course_id, sessions)
        elif req_type in {'program', 'study_program', 'study program'}:
            program_id = _find_study_program_id(db, target_code)
            _upsert_program_requirement(db, timetable_id, program_id, course_id, sessions)
        elif req_type in {'group_only', 'group-only', 'group only'}:
            group_id = _find_group_id(db, target_code, timetable_id)
            existing = db.scalar(
                select(CourseForGroup)
                .where(CourseForGroup.group_id == group_id, CourseForGroup.course_id == course_id)
                .limit(1)
            )
            if existing:
                existing.sessions_required = sessions  # type: ignore
            else:
                db.add(CourseForGroup(group_id=group_id, course_id=course_id, sessions_required=sessions))
        else:
            raise HTTPException(status_code=400, detail=f'Invalid requirement type: {req_type}')
    db.commit()

@app.get('/template/{entity}.xlsx')
def download_template(entity: str):
    workbook = _build_template_workbook(entity)
    filename = f'{entity.replace('-', '_')}_template.xlsx'
    return _template_response(workbook, filename)

@app.get('/export-data/{entity}.xlsx')
def export_current_data(entity: str, db: Session = Depends(get_db), timetable_id: Optional[int] = Query(default=None), cycle_id: Optional[int] = Query(default=None)):
    workbook = _build_current_data_workbook(entity, db, timetable_id, cycle_id)
    filename = f'{entity.replace('-', '_')}_current_data.xlsx'
    return _current_data_response(workbook, filename)

@app.post('/api/import/teachers')
def import_teachers(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _import_teachers(file, db)
    return bootstrap_payload(db)

@app.post('/api/import/study-programs')
def import_study_programs(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _import_study_programs(file, db)
    return bootstrap_payload(db)

@app.post('/api/import/course-tags')
def import_course_tags(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _import_course_tags(file, db)
    return bootstrap_payload(db)

@app.post('/api/import/rooms')
def import_rooms(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _import_rooms(file, db)
    return bootstrap_payload(db)

@app.post('/api/import/courses')
def import_courses(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    timetable_id: Optional[int] = Query(default=None),
    cycle_id: Optional[int] = Query(default=None),
):
    _import_courses(file, db, timetable_id, cycle_id)
    return bootstrap_payload(db, timetable_id, cycle_id)

@app.post('/api/import/group-tags')
def import_group_tags(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _import_group_tags(file, db)
    return bootstrap_payload(db)

@app.post('/api/import/groups')
def import_groups(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    timetable_id: Optional[int] = Query(default=None),
    cycle_id: Optional[int] = Query(default=None),
):
    _import_groups(file, db, timetable_id, cycle_id)
    return bootstrap_payload(db, timetable_id, cycle_id)

@app.post('/api/import/requirements')
def import_requirements(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    timetable_id: Optional[int] = Query(default=None),
    cycle_id: Optional[int] = Query(default=None),
):
    _import_requirements(file, db, timetable_id, cycle_id)
    return bootstrap_payload(db, timetable_id, cycle_id)


def _upsert_group_tag_requirement(db: Session, timetable_id: int, group_tag_id: int, course_id: int, sessions_required: int) -> None:
    req = db.scalar(
        select(CourseForGroupTag)
        .where(
            CourseForGroupTag.group_tag_id == group_tag_id,
            CourseForGroupTag.course_id == course_id,
            CourseForGroupTag.timetable_id == timetable_id,
        )
        .limit(1)
    )
    if req:
        req.sessions_required = sessions_required
    else:
        db.add(CourseForGroupTag(
            group_tag_id=group_tag_id,
            course_id=course_id,
            sessions_required=sessions_required,
            timetable_id=timetable_id,
        ))


def _upsert_program_requirement(db: Session, timetable_id: int, program_id: int, course_id: int, sessions_required: int) -> None:
    req = db.scalar(
        select(StudyProgramCourse)
        .where(
            StudyProgramCourse.study_program_id == program_id,
            StudyProgramCourse.course_id == course_id,
            StudyProgramCourse.timetable_id == timetable_id,
        )
        .limit(1)
    )
    if req:
        req.sessions_required = sessions_required
    else:
        db.add(StudyProgramCourse(
            study_program_id=program_id,
            course_id=course_id,
            sessions_required=sessions_required,
            timetable_id=timetable_id,
        ))


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
        result.append({
            "teacher_id": teacher_id,
            "teacher": teacher.name if teacher else str(teacher_id),
            "timeslot_count": int(count),
        })
    return result


def _build_timetable_payload(db: Session, timetable_id: Optional[int], cycle_id: Optional[int] = None) -> Dict[str, Any]:
    timetable = _selected_timetable(db, timetable_id, cycle_id)
    german_cycle = False
    cycle = None
    if timetable:
        cycle = getattr(timetable, 'cycle', None) or db.get(Cycle, timetable.cycle_id)
        german_cycle = bool(getattr(cycle, 'german_timeslots', False))
    timeslot_query = select(Timeslot).order_by(Timeslot.sort_order)
    if german_cycle:
        timeslot_query = timeslot_query.where(Timeslot.label.like('German%'))
    else:
        timeslot_query = timeslot_query.where(~Timeslot.label.like('German%'))
    timeslots = db.scalars(timeslot_query).all()

    payload: Dict[str, Any] = {
        "selected_timetable_id": timetable.id if timetable else None,
        "selected_cycle_id": getattr(timetable, 'cycle_id', None) if timetable else cycle_id,
        "cycle_name": getattr(cycle, 'name', '') if timetable and cycle is not None else '',
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
                "course_id": first.course.id if first.course else None,
                "course_code": getattr(first.course, 'code', '') or '',
                "course_name": getattr(first.course, 'name', '') or getattr(first.course, 'code', '') or '',
                "teacher_id": first.teacher.id if first.teacher else None,
                "teacher_name": first.teacher.name if first.teacher else "",
                "room_id": first.room.id if first.room else None,
                "room_name": first.room.code if first.room else "",
                "program_codes": programs or [],
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
            "timetable_id": getattr(g, "timetable_id", None),
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


def _entity_payload(db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> Dict[str, Any]:
    cycles = db.scalars(select(Cycle).order_by(Cycle.year_starting.desc(), Cycle.name)).all()
    if cycle_id is not None:
        timetables = db.scalars(select(Timetable).where(Timetable.cycle_id == cycle_id).order_by(Timetable.id)).all()
    else:
        timetables = db.scalars(select(Timetable).order_by(Timetable.id)).all()
    group_tags = db.scalars(select(GroupTag).order_by(GroupTag.code)).all()
    course_tags = db.scalars(select(CourseTag).order_by(CourseTag.name)).all()
    programs = db.scalars(select(StudyProgram).order_by(StudyProgram.code)).all()

    # Use the requested timetable_id if provided; otherwise fall back to active or latest.
    if timetable_id is None and len(timetables) > 0:
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
                "course_name": _sanitize_text(r.course.name if r.course else str(r.course_id)),
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
                "course_name": _sanitize_text(r.course.name if r.course else str(r.course_id)),
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
        "cycles": [{"id": c.id, "name": c.name, "year_starting": c.year_starting, "german_timeslots": getattr(c, 'german_timeslots', False)} for c in cycles],
        "timetables": [{"id": t.id, "cycle_id": t.cycle_id} for t in timetables],
        "group_tags": [
            {
                "id": gt.id,
                "code": _sanitize_text(gt.code),
                "name": _sanitize_text(gt.name),
                "requirements": group_tag_requirement.get(cast(int, gt.id), [])
            }
            for gt in group_tags
        ],
        "course_tags": [{"id": ct.id, "name": _sanitize_text(ct.name)} for ct in course_tags],
        "programs": [
            {
                "id": p.id,
                "code": _sanitize_text(p.code),
                "name": _sanitize_text(p.name),
                "requirements": program_requirements.get(cast(int, p.id), [])
            }
            for p in programs
        ],
        "rooms": [{"id": r.id, "code": _sanitize_text(r.code), "name": _sanitize_text(r.name), "capacity": r.capacity_num} for r in rooms],
        "teachers": [{"id": t.id, "name": _sanitize_text(t.name), "course_tag_ids": sorted(link.course_tag_id for link in t.course_tag_links)} for t in teachers],
        "courses": [
            {
                "id": c.id,
                "code": _sanitize_text(c.code),
                "name": _sanitize_text(c.name),
                "course_tag_id": c.course_tag_id,
                "course_tag_name": _sanitize_text(c.course_tag.name) if c.course_tag else None,
                "require_all": c.require_all_student_in_group,
                "elective": c.elective,
                "study_program_ids": sorted(link.study_program_id for link in c.study_program_links),
            }
            for c in courses
        ],
        "teacher_ids_by_tag": _teacher_ids_by_tag(db),
        #load all requirements for all group tags and programs to avoid loading them separately when user clicks on a group - this is a tradeoff to reduce number of queries and simplify frontend code, at the cost of loading some unused data on the main screen load
       # based on def above, use the latest timetable id when no timetable is explicitly selected so requirements load for the current view
        "group_tag_requirements": group_tag_requirement,
        "program_requirements": program_requirements,
    }


def bootstrap_payload(db: Session, timetable_id: Optional[int] = None, cycle_id: Optional[int] = None) -> Dict[str, Any]:
    return {**_build_timetable_payload(db, timetable_id, cycle_id), **_entity_payload(db, timetable_id, cycle_id)}


def _delete_timetable_with_dependents(db: Session, timetable_id: int) -> None:
    group_ids = db.scalars(select(Group.id).where(Group.timetable_id == timetable_id)).all()
    if group_ids:
        db.query(ScheduledClass).filter(ScheduledClass.group_id.in_(group_ids)).delete(synchronize_session=False)
        db.query(GroupStudyProgram).filter(GroupStudyProgram.group_id.in_(group_ids)).delete(synchronize_session=False)
        db.query(Group).filter(Group.id.in_(group_ids)).delete(synchronize_session=False)
    db.query(CourseForGroupTag).filter(CourseForGroupTag.timetable_id == timetable_id).delete(synchronize_session=False)
    db.query(StudyProgramCourse).filter(StudyProgramCourse.timetable_id == timetable_id).delete(synchronize_session=False)
    db.query(Timetable).filter(Timetable.id == timetable_id).delete(synchronize_session=False)


@app.get("/api/bootstrap")
def api_bootstrap(
    timetable_id: Optional[int] = Query(default=None),
    cycle_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    return JSONResponse(bootstrap_payload(db, timetable_id, cycle_id))


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
    row = Cycle(name=payload.name.strip(), year_starting=payload.year_starting, german_timeslots=payload.german_timeslots)
    db.add(row)
    db.flush()
    timetable = Timetable(cycle_id=row.id, in_action=False)
    db.add(timetable)
    if payload.german_timeslots:
        _ensure_german_timeslots(db)
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/cycles/{cycle_id}/duplicate")
def duplicate_cycle(cycle_id: int, db: Session = Depends(get_db)):
    original = db.get(Cycle, cycle_id)
    if not original:
        raise HTTPException(status_code=404, detail="Cycle not found.")

    base_name = original.name.strip()
    existing_names = {
        name for (name,) in db.execute(select(Cycle.name).where(Cycle.name.like(f"{base_name}%"))).all()
    }
    new_name = f"{base_name} copy"
    suffix = 2
    while new_name in existing_names:
        new_name = f"{base_name} copy {suffix}"
        suffix += 1

    new_cycle = Cycle(name=new_name, year_starting=original.year_starting, german_timeslots=original.german_timeslots)
    db.add(new_cycle)
    db.flush()
    new_cycle_id = int(getattr(new_cycle, 'id'))
    if getattr(new_cycle, 'german_timeslots', False):
        _ensure_german_timeslots(db)

    new_timetable = Timetable(cycle_id=new_cycle_id, in_action=False)
    db.add(new_timetable)
    db.flush()
    new_timetable_id = int(getattr(new_timetable, 'id'))

    original_timetable = db.scalar(select(Timetable).where(Timetable.cycle_id == cycle_id).limit(1))
    if original_timetable:
        for req in db.scalars(select(CourseForGroupTag).where(CourseForGroupTag.timetable_id == original_timetable.id)).all():
            db.add(CourseForGroupTag(
                group_tag_id=req.group_tag_id,
                course_id=req.course_id,
                timetable_id=new_timetable_id,
                sessions_required=req.sessions_required,
            ))
        for req in db.scalars(select(StudyProgramCourse).where(StudyProgramCourse.timetable_id == original_timetable.id)).all():
            db.add(StudyProgramCourse(
                study_program_id=req.study_program_id,
                course_id=req.course_id,
                timetable_id=new_timetable_id,
                sessions_required=req.sessions_required,
            ))

        old_to_new: Dict[int, int] = {}
        groups = db.scalars(select(Group).where(Group.timetable_id == original_timetable.id).order_by(Group.sort_order)).all()
        for group in groups:
            original_group_id = int(getattr(group, 'id'))
            new_group = Group(
                timetable_id=new_timetable_id,
                group_tag_id=group.group_tag_id,
                code=group.code,
                name=group.name,
                size_num=group.size_num,
                sort_order=group.sort_order,
            )
            db.add(new_group)
            db.flush()
            new_group_id = int(getattr(new_group, 'id'))
            old_to_new[original_group_id] = new_group_id

            for link in group.study_program_links:
                db.add(GroupStudyProgram(group_id=new_group_id, study_program_id=link.study_program_id))
            for req in group.course_requirements:
                db.add(CourseForGroup(
                    group_id=new_group_id,
                    course_id=req.course_id,
                    sessions_required=req.sessions_required,
                ))

        classes = db.scalars(select(ScheduledClass).where(ScheduledClass.group_id.in_(list(old_to_new.keys())))).all()
        for cls in classes:
            original_group_id = int(getattr(cls, 'group_id'))
            db.add(ScheduledClass(
                group_id=old_to_new[original_group_id],
                timeslot_id=cls.timeslot_id,
                room_id=cls.room_id,
                teacher_id=cls.teacher_id,
                course_id=cls.course_id,
                study_program_id=cls.study_program_id,
                deploy=cls.deploy,
                shared_key=cls.shared_key,
                expected_size=cls.expected_size,
                notes=cls.notes,
                source=cls.source,
            ))

    db.commit()
    return bootstrap_payload(db, None, new_cycle_id)


@app.put("/api/cycles/{cycle_id}")
def update_cycle(cycle_id: int, payload: CycleIn, db: Session = Depends(get_db)):
    row = db.get(Cycle, cycle_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cycle not found.")
    row.name = payload.name.strip()  # type: ignore
    row.year_starting = payload.year_starting  # type: ignore
    row.german_timeslots = payload.german_timeslots  # type: ignore
    db.commit()
    return bootstrap_payload(db)


@app.post("/api/timetables")
def create_timetable(payload: TimetableIn, db: Session = Depends(get_db)):
    if not db.get(Cycle, payload.cycle_id):
        raise HTTPException(status_code=404, detail="Cycle not found.")
    if db.scalar(select(Timetable.id).where(Timetable.cycle_id == payload.cycle_id).limit(1)):
        raise HTTPException(status_code=400, detail="A timetable already exists for this cycle.")
    row = Timetable(cycle_id=payload.cycle_id)
    db.add(row)
    db.commit()
    db.refresh(row)  # Ensure row.id is populated with the actual int value
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
    old_cycle_id = row.cycle_id
    if payload.cycle_id != old_cycle_id:
        if db.scalar(select(Timetable.id).where(Timetable.cycle_id == payload.cycle_id, Timetable.id != timetable_id).limit(1)):
            raise HTTPException(status_code=400, detail="A timetable already exists for this cycle.")
    row.cycle_id = payload.cycle_id  # type: ignore
    db.commit()
    db.refresh(row)  # Ensure row.id is an int, not a Column
    tid = getattr(row, 'id', None)
    if tid is None or not isinstance(tid, int):
        db.refresh(row)
        tid = getattr(row, 'id', None)
    return bootstrap_payload(db, int(tid) if tid is not None else None)




@app.delete("/api/timetables/{timetable_id}")
def delete_timetable(timetable_id: int, db: Session = Depends(get_db)):
    row = db.get(Timetable, timetable_id)
    if not row:
        raise HTTPException(status_code=404, detail="Timetable not found.")
    _delete_timetable_with_dependents(db, timetable_id)
    db.commit()
    return bootstrap_payload(db)


@app.delete("/api/cycles/{cycle_id}")
def delete_cycle(cycle_id: int, db: Session = Depends(get_db)):
    row = db.get(Cycle, cycle_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cycle not found.")
    timetable_ids = db.scalars(select(Timetable.id).where(Timetable.cycle_id == cycle_id)).all()
    for timetable_id in timetable_ids:
        _delete_timetable_with_dependents(db, timetable_id)
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
    if timetable_id is not None:
        selected_timetable_id = int(timetable_id)
        selected_group_tag_id = int(getattr(row, 'id'))
        for req in payload.requirements:
            _upsert_group_tag_requirement(db, selected_timetable_id, selected_group_tag_id, req.course_id, req.sessions_required)
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
    if timetable_id is None and payload.requirements:
        raise HTTPException(status_code=400, detail="No timetable selected for group tag requirements.")
    def get_int(val: Any) -> int:
        if isinstance(val, int):
            return val
        if hasattr(val, 'value'):
            return int(val.value)
        return int(str(val))
    seen: set[int] = set()
    selected_timetable_id: Optional[int] = None
    if timetable_id is not None:
        selected_timetable_id = int(timetable_id)
    for req in payload.requirements:
        cid = get_int(req.course_id)
        if not db.get(Course, cid):
            raise HTTPException(status_code=404, detail=f"Course {cid} not found.")
        if selected_timetable_id is None:
            raise HTTPException(status_code=400, detail="No timetable selected for group tag requirements.")
        _upsert_group_tag_requirement(db, selected_timetable_id, group_tag_id, cid, req.sessions_required)
        seen.add(cid)
    if selected_timetable_id is not None:
        query = db.query(CourseForGroupTag).filter(
            CourseForGroupTag.group_tag_id == group_tag_id,
            CourseForGroupTag.timetable_id == selected_timetable_id,
        )
        if seen:
            query = query.filter(CourseForGroupTag.course_id.notin_(seen))
        query.delete(synchronize_session=False)
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


def _sync_course_class_type(db: Session, course_id: int, new_require_all: bool, new_elective: bool) -> None:
    """Keep ScheduledClass rows consistent after a course type change.

    When a course flips between required/program/elective, this sync helper
    updates classes so they reflect the new type.
    """
    course = db.get(Course, course_id)
    if not course:
        return

    old_require_all = bool(course.require_all_student_in_group)
    old_elective = bool(course.elective)
    new_require_all = bool(new_require_all)
    new_elective = bool(new_elective)

    if (old_require_all, old_elective) == (new_require_all, new_elective):
        return

    # Any class with study_program_id must be cleared for required or elective courses.
    if new_require_all or new_elective:
        db.query(ScheduledClass).filter(
            ScheduledClass.course_id == course_id,
            ScheduledClass.study_program_id.isnot(None),
        ).update({ScheduledClass.study_program_id: None}, synchronize_session=False)
        return

    # If course becomes a program course, assign study_program_id for any existing
    # require-all classes in groups that have exactly one study program.
    rows = db.query(ScheduledClass).filter(
        ScheduledClass.course_id == course_id,
        ScheduledClass.study_program_id.is_(None),
    ).all()
    if not rows:
        return

    group_ids = sorted({row.group_id for row in rows})
    groups = db.query(Group).options(joinedload(Group.study_program_links)).filter(Group.id.in_(group_ids)).all()
    program_by_group = {
        group.id: [link.study_program_id for link in group.study_program_links]
        for group in groups
    }

    for row in rows:
        prog_ids = program_by_group.get(row.group_id, [])
        if len(prog_ids) == 1:
            row.study_program_id = prog_ids[0]


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
    _sync_course_class_type(db, course_id, payload.require_all, payload.elective)
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
        self_study=getattr(payload, 'self_study', False),
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
    elif getattr(row, 'shared_key', None) is not None:
        candidate_rows = db.query(ScheduledClass).filter(
            ScheduledClass.shared_key == row.shared_key,
            ScheduledClass.deploy.is_(True),
        ).all()

    target_group_ids = [cast(int, row.group_id)]
    rows = [row]
    is_multi_class_edit = (
        mode == MODE_PROGRAM and getattr(row, 'study_program_id', None) is not None
    ) or (
        mode == MODE_ELECTIVE and getattr(row, 'shared_key', None) is not None
    )
    old_teacher_id = row.teacher_id
    old_room_id = row.room_id
    changing_teacher = payload.teacher_id is not None and payload.teacher_id != old_teacher_id
    changing_room = payload.room_id is not None and payload.room_id != old_room_id

    if mode == MODE_REQUIRED and len(target_group_ids) > 1:
        raise HTTPException(status_code=400, detail="Require-all-students classes must be edited one group at a time.")

    if is_multi_class_edit and changing_teacher and changing_room:
        raise HTTPException(
            status_code=400,
            detail="For multi-group or multi-program classes, change only teacher or room in one edit command, not both."
        )

    custom_bulk_update = False
    if is_multi_class_edit and len(candidate_rows) > 1 and (changing_teacher or changing_room):
        if changing_teacher:
            if any(r.room_id != old_room_id for r in candidate_rows):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot bulk update teacher because other same-course classes use a different room in this timeslot. Change only the teacher or update individually."
                )
        if changing_room:
            if any(r.teacher_id != old_teacher_id for r in candidate_rows):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot bulk update room because other same-course classes use a different teacher in this timeslot. Change only the room or update individually."
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
                self_study=getattr(payload, 'self_study', False),
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
    shared_key = getattr(row, 'shared_key', None)
    if shared_key is not None:
        db.query(ScheduledClass).filter(ScheduledClass.shared_key == shared_key).delete(synchronize_session=False)
    elif getattr(row, 'study_program_id', None) is not None:
        db.query(ScheduledClass).filter(
            ScheduledClass.group_id == row.group_id,
            ScheduledClass.timeslot_id == row.timeslot_id,
            ScheduledClass.course_id == row.course_id,
            ScheduledClass.teacher_id == row.teacher_id,
            ScheduledClass.room_id == row.room_id,
            ScheduledClass.study_program_id == row.study_program_id,
        ).delete(synchronize_session=False)
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
    group_ids: Optional[List[int]] = Query(default=None),
    group_tag_ids: Optional[List[int]] = Query(default=None),
    teacher_ids: Optional[List[int]] = Query(default=None),
    course_ids: Optional[List[int]] = Query(default=None),
    db: Session = Depends(get_db),
):
    if (group_ids or teacher_ids or group_tag_ids or course_ids) and (program_id is not None or program_ids is not None):
        raise HTTPException(status_code=400, detail="Cannot combine study program and group/teacher/course export filters.")
    if group_tag_ids is not None and (group_ids is not None or teacher_ids is not None or course_ids is not None):
        raise HTTPException(status_code=400, detail="Cannot combine group tag export filters with other export filters.")
    if course_ids is not None and (group_ids is not None or teacher_ids is not None or group_tag_ids is not None):
        raise HTTPException(status_code=400, detail="Cannot combine course export with group, teacher, or group tag export filters.")

    timetable = _selected_timetable(db, timetable_id)
    if not timetable:
        raise HTTPException(status_code=404, detail="No timetable found.")

    selected_group_ids: Optional[List[int]] = None
    selected_teacher_ids: Optional[List[int]] = None
    selected_course_ids: Optional[List[int]] = None
    selected_program = None
    selected_programs: Optional[List[StudyProgram]] = None
    if group_ids is not None:
        selected_group_ids = group_ids
        groups_query = select(Group.id).where(Group.timetable_id == timetable.id, Group.id.in_(group_ids))
        found_group_ids = [int(gid) for gid in db.scalars(groups_query).all()]
        if not found_group_ids:
            raise HTTPException(status_code=404, detail="No matching groups found for this timetable.")
        selected_group_ids = found_group_ids
    elif teacher_ids is not None:
        selected_teacher_ids = teacher_ids
        found_group_ids = [
            int(gid)
            for gid in db.scalars(
                select(Group.id)
                .join(ScheduledClass, ScheduledClass.group_id == Group.id)
                .where(
                    Group.timetable_id == timetable.id,
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.teacher_id.in_(teacher_ids),
                )
                .distinct()
            ).all()
        ]
        if not found_group_ids:
            raise HTTPException(status_code=404, detail="No deployed groups found for the selected teacher(s) in this timetable.")
        selected_group_ids = found_group_ids
    elif course_ids is not None:
        selected_course_ids = course_ids
        found_group_ids = [
            int(gid)
            for gid in db.scalars(
                select(Group.id)
                .join(ScheduledClass, ScheduledClass.group_id == Group.id)
                .where(
                    Group.timetable_id == timetable.id,
                    ScheduledClass.deploy.is_(True),
                    ScheduledClass.course_id.in_(course_ids),
                )
                .distinct()
            ).all()
        ]
        if not found_group_ids:
            raise HTTPException(status_code=404, detail="No deployed groups found for the selected course(s) in this timetable.")
        selected_group_ids = found_group_ids
    elif group_tag_ids is not None:
        found_group_tag_ids = [int(gtid) for gtid in db.scalars(select(GroupTag.id).where(GroupTag.id.in_(group_tag_ids))).all()]
        if not found_group_tag_ids:
            raise HTTPException(status_code=404, detail="No matching group tags found.")
        selected_group_ids = [int(gid) for gid in db.scalars(
            select(Group.id)
            .where(Group.timetable_id == timetable.id, Group.group_tag_id.in_(found_group_tag_ids))
        ).all()]
        if not selected_group_ids:
            raise HTTPException(status_code=404, detail="No groups found for the selected group tags in this timetable.")
    elif program_ids is not None:
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

    groups = db.execute(
        select(Group)
        .where(Group.timetable_id == timetable.id)
        .options(joinedload(Group.group_tag))
    ).unique().scalars().all()
    if selected_group_ids is not None:
        groups = [group for group in groups if group.id in selected_group_ids]

    class_count_query = select(func.count()).select_from(ScheduledClass).join(Group).where(
        ScheduledClass.deploy.is_(True),
        Group.timetable_id == timetable.id,
    )
    if selected_group_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.group_id.in_(selected_group_ids))
    if selected_teacher_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.teacher_id.in_(selected_teacher_ids))
    if selected_course_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.course_id.in_(selected_course_ids))
    existing_class_count = db.scalar(class_count_query)
    if not existing_class_count:
        raise HTTPException(status_code=400, detail="No deployed classes found for selected timetable.")

    selected_program_export_ids = None
    if program_ids is not None:
        selected_program_export_ids = program_ids
    elif selected_program is not None:
        selected_program_export_ids = [cast(int, getattr(selected_program, 'id'))]

    class_count_query = select(func.count()).select_from(ScheduledClass).join(Group).where(
        ScheduledClass.deploy.is_(True),
        Group.timetable_id == timetable.id,
    )
    if selected_group_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.group_id.in_(selected_group_ids))
    if selected_teacher_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.teacher_id.in_(selected_teacher_ids))
    if selected_program_export_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.study_program_id.in_(selected_program_export_ids))
    if selected_course_ids is not None:
        class_count_query = class_count_query.where(ScheduledClass.course_id.in_(selected_course_ids))
    existing_class_count = db.scalar(class_count_query)
    if not existing_class_count:
        raise HTTPException(status_code=400, detail="No deployed classes found for selected timetable.")

    missing_assignment_query = select(func.count()).select_from(ScheduledClass).join(Group).where(
        ScheduledClass.deploy.is_(True),
        Group.timetable_id == timetable.id,
        (ScheduledClass.teacher_id.is_(None) | ScheduledClass.room_id.is_(None)),
    )
    if selected_group_ids is not None:
        missing_assignment_query = missing_assignment_query.where(ScheduledClass.group_id.in_(selected_group_ids))
    if selected_teacher_ids is not None:
        missing_assignment_query = missing_assignment_query.where(ScheduledClass.teacher_id.in_(selected_teacher_ids))
    if selected_program_export_ids is not None:
        missing_assignment_query = missing_assignment_query.where(ScheduledClass.study_program_id.in_(selected_program_export_ids))
    if selected_course_ids is not None:
        missing_assignment_query = missing_assignment_query.where(ScheduledClass.course_id.in_(selected_course_ids))
    if db.scalar(missing_assignment_query):
        raise HTTPException(status_code=400, detail="Cannot export: some deployed classes are missing teacher or room assignment.")

    if selected_teacher_ids is None:
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
        elif selected_group_ids is not None:
            programs = list(db.scalars(
                select(StudyProgram)
                .join(GroupStudyProgram)
                .where(GroupStudyProgram.group_id.in_(selected_group_ids))
                .distinct()
            ).all())
        else:
            programs = db.scalars(select(StudyProgram)).all()
        for program in programs:
            reqs = db.query(StudyProgramCourse).filter(
                StudyProgramCourse.study_program_id == program.id,
                StudyProgramCourse.timetable_id == timetable.id
            ).all()
            if not reqs:
                continue
            if selected_group_ids is not None:
                group_ids_for_program = [int(gid) for gid in db.scalars(
                    select(GroupStudyProgram.group_id)
                    .where(
                        GroupStudyProgram.study_program_id == program.id,
                        GroupStudyProgram.group_id.in_(selected_group_ids),
                    )
                ).all()]
            else:
                group_ids_for_program = [int(gid) for gid in db.scalars(
                    select(GroupStudyProgram.group_id)
                    .join(Group)
                    .where(
                        GroupStudyProgram.study_program_id == program.id,
                        Group.timetable_id == timetable.id
                    )
                ).all()]
            if not group_ids_for_program:
                continue
            for req in reqs:
                for group_id in group_ids_for_program:
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

    cycle = timetable.cycle if hasattr(timetable, 'cycle') else db.get(Cycle, timetable.cycle_id)
    import re
    def sanitize_filename(s: str) -> str:
        return re.sub(r'[^\w\-_\. ]', '_', s)

    def make_export_suffix(names: list[str], prefix: str, max_items: int = 5, max_length: int = 80) -> str:
        cleaned = [sanitize_filename(str(name)).strip('_') for name in names if name]
        if not cleaned:
            return f"{prefix}-{len(names)}"
        if len(cleaned) > max_items:
            return f"{prefix}-{len(cleaned)}"
        joined = '_'.join(cleaned)
        if len(joined) > max_length:
            joined = joined[:max_length].rstrip('_')
        return f"{prefix}-{joined}"

    cycle_name = sanitize_filename(str(getattr(cycle, 'name', f"cycle{timetable.cycle_id}")))
    cycle_year = str(getattr(cycle, 'year_starting', timetable.cycle_id))
    cycle_label = cycle_name if cycle_year in cycle_name else f"{cycle_name}_{cycle_year}"
    timetable_id = getattr(timetable, 'id', None)
    if timetable_id is None:
        raise HTTPException(status_code=500, detail="Timetable id is unavailable.")
    if group_ids is not None:
        suffix_codes = make_export_suffix([str(group.code) for group in groups], 'groups')
        program_suffix = f"_{suffix_codes}"
    elif group_tag_ids is not None:
        group_tag_codes = [
            str(gt.code)
            for gt in db.scalars(select(GroupTag).where(GroupTag.id.in_(group_tag_ids))).all()
        ]
        suffix_codes = make_export_suffix(group_tag_codes, 'group-tags')
        program_suffix = f"_{suffix_codes}"
    elif teacher_ids is not None:
        teacher_names = [
            str(t.name)
            for t in db.scalars(select(Teacher).where(Teacher.id.in_(selected_teacher_ids or []))).all()
        ]
        suffix_codes = make_export_suffix(teacher_names, 'teachers')
        program_suffix = f"_{suffix_codes}"
    elif course_ids is not None:
        course_names = [
            str(c.name)
            for c in db.scalars(select(Course).where(Course.id.in_(selected_course_ids or [])))
        ]
        suffix_codes = make_export_suffix(course_names, 'courses')
        program_suffix = f"_{suffix_codes}"
    elif program_ids is not None and selected_programs:
        suffix_codes = make_export_suffix([str(prog.code) for prog in selected_programs], 'programs')
        program_suffix = f"_{suffix_codes}"
    elif selected_program is not None:
        program_suffix = f"_program-{sanitize_filename(str(getattr(selected_program, 'code', '')))}"
    else:
        program_suffix = "_all-programs"
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    filename = f"timetable_{cycle_label}_{timetable_id}{program_suffix}_{timestamp}.xlsx"
    out_path: Path = EXPORT_DIR / filename
    selected_program_ids = (
        list(program_ids)
        if program_ids is not None
        else ([cast(int, getattr(selected_program, 'id'))] if selected_program is not None else None)
    )
    export_timetable_xlsx(
        db,
        out_path,
        timetable_id=timetable_id,
        study_program_ids=selected_program_ids,
        group_ids=selected_group_ids,
        group_tag_ids=group_tag_ids,
        teacher_ids=selected_teacher_ids,
        course_ids=selected_course_ids,
    )
    return FileResponse(
        out_path,
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{out_path.name}"', "X-Download-Filename": out_path.name},
    )
@app.delete("/api/group-tags/{group_tag_id}/requirements/{course_id}")
def delete_group_tag_requirement(
    group_tag_id: int,
    course_id: int,
    timetable_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    selected_timetable_id = _current_timetable_id(db, timetable_id)
    if selected_timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    db.query(CourseForGroupTag).filter(
        CourseForGroupTag.group_tag_id == group_tag_id,
        CourseForGroupTag.course_id == course_id,
        CourseForGroupTag.timetable_id == int(selected_timetable_id),
    ).delete(synchronize_session=False)
    db.commit()
    return bootstrap_payload(db, int(selected_timetable_id))

@app.delete("/api/study-programs/{program_id}/requirements/{course_id}")
def delete_study_program_requirement(
    program_id: int,
    course_id: int,
    timetable_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    selected_timetable_id = _current_timetable_id(db, timetable_id)
    if selected_timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    db.query(StudyProgramCourse).filter(
        StudyProgramCourse.study_program_id == program_id,
        StudyProgramCourse.course_id == course_id,
        StudyProgramCourse.timetable_id == int(selected_timetable_id),
    ).delete(synchronize_session=False)
    db.commit()
    return bootstrap_payload(db, int(selected_timetable_id))

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
        timetable_id = db.scalar(select(Timetable.id).order_by(Timetable.id.desc()).limit(1))
    if timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    if not db.get(GroupTag, group_tag_id):
        raise HTTPException(status_code=404, detail="Group tag not found.")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found.")
    _upsert_group_tag_requirement(db, int(timetable_id), group_tag_id, course_id, sessions_required)
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
        _upsert_group_tag_requirement(db, int(timetable_id), group_tag_id, course_id, sessions_required)
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
        timetable_id = db.scalar(select(Timetable.id).order_by(Timetable.id.desc()).limit(1))
    if timetable_id is None:
        raise HTTPException(status_code=400, detail="No timetable selected or available.")
    if not db.get(StudyProgram, program_id):
        raise HTTPException(status_code=404, detail="Study program not found.")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found.")
    _upsert_program_requirement(db, int(timetable_id), program_id, course_id, sessions_required)
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
        _upsert_program_requirement(db, int(timetable_id), study_program_id, course_id, sessions_required)
    db.commit()
    return bootstrap_payload(db)