import openpyxl
from typing import Any, Dict, Set, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Teacher, Course, Room, StudyProgram


def extract_entities_from_excel(filepath: str) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    wb: Any = openpyxl.load_workbook(filepath)
    ws: Any = wb.active
    teachers: Set[str] = set()
    courses: Set[str] = set()
    rooms: Set[str] = set()
    study_programs: Set[str] = set()
    # Scan all cells for relevant info
    for row in ws.iter_rows(min_row=1, values_only=True):
        for cell in row:
            if not cell or not isinstance(cell, str):
                continue
            # Simple heuristics based on your export format
            if '_Mr.' in cell or '_Ms.' in cell or '_Dr.' in cell:
                teachers.add(cell.split('_')[1].replace('Mr. ', '').replace('Ms. ', '').replace('Dr. ', '').strip())
            if 'Room:' in cell:
                rooms.add(cell.split('Room:')[1].strip())
            if '_' in cell:
                courses.add(cell.split('_')[0].strip())
            if '[' in cell and ']' in cell:
                tags = cell[cell.find('[')+1:cell.find(']')].split(',')
                study_programs.update([t.strip() for t in tags])
    return teachers, courses, rooms, study_programs

def get_existing_entities(db: Session) -> Dict[str, Set[str]]:
    return {
        'teachers': set(str(getattr(t, 'name', '')) for t in db.query(Teacher).all() if getattr(t, 'name', None) is not None),
        'courses': set(str(getattr(c, 'name', '')) for c in db.query(Course).all() if getattr(c, 'name', None) is not None),
        'rooms': set(str(getattr(r, 'code', '')) for r in db.query(Room).all() if getattr(r, 'code', None) is not None),
        'study_programs': set(str(getattr(sp, 'code', '')) for sp in db.query(StudyProgram).all() if getattr(sp, 'code', None) is not None),
    }


def add_missing_entities(db: Session, missing: Dict[str, Set[str]]) -> None:
    for t in missing['teachers']:
        db.add(Teacher(name=t))
    for c in missing['courses']:
        db.add(Course(name=c, code=c, course_tag_id=1, require_all_student_in_group=False, elective=False))
    for r in missing['rooms']:
        db.add(Room(code=r, name=r, capacity_num=80))
    for sp in missing['study_programs']:
        db.add(StudyProgram(code=sp, name=sp))
    db.commit()


def main() -> None:
    excel_path = 'FY2025_Timetable_Phase 4.xlsx'  # Update path if needed
    teachers, courses, rooms, study_programs = extract_entities_from_excel(excel_path)
    db = SessionLocal()
    try:
        existing = get_existing_entities(db)
        missing: Dict[str, Set[str]] = {
            'teachers': teachers - existing['teachers'],
            'courses': courses - existing['courses'],
            'rooms': rooms - existing['rooms'],
            'study_programs': study_programs - existing['study_programs'],
        }
        print('Missing:', missing)
        if any(missing.values()):
            add_missing_entities(db, missing)
            print('Added missing entities.')
        else:
            print('No missing entities found.')
    finally:
        db.close()

if __name__ == '__main__':
    main()
