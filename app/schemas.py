from typing import List, Optional

from pydantic import BaseModel, Field


class GroupRequirementIn(BaseModel):
    course_id: int
    sessions_required: int = Field(ge=1, le=20, default=1)


class CycleIn(BaseModel):
    name: str
    year_starting: int = Field(ge=2000, le=2100)
    german_timeslots: bool = False


class TimetableIn(BaseModel):
    cycle_id: int


class GroupTagIn(BaseModel):
    code: str
    name: str
    requirements: List[GroupRequirementIn] = []


class CourseTagIn(BaseModel):
    name: str


class StudyProgramIn(BaseModel):
    code: str
    name: str


class RoomIn(BaseModel):
    code: str
    name: str
    capacity: int = Field(ge=1, le=500)


class TeacherIn(BaseModel):
    name: str
    course_tag_ids: List[int] = []


class CourseIn(BaseModel):
    code: str
    name: str
    course_tag_id: int
    require_all: bool = False
    elective: bool = False
    study_program_ids: List[int] = []


class GroupCreateIn(BaseModel):
    timetable_id: int
    code: str
    name: Optional[str] = None
    group_tag_id: int
    study_program_ids: List[int]
    capacity: int = Field(ge=1, le=500)
    sort_order: Optional[int] = None
    group_requirements: List[GroupRequirementIn] = []
    requirements: List[GroupRequirementIn] = []  # legacy alias for compatibility


class GroupUpdateIn(GroupCreateIn):
    pass


class GroupOrderIn(BaseModel):
    group_ids: List[int]


class ClassCreateIn(BaseModel):
    timeslot_id: int
    target_group_ids: List[int]
    mode: str
    course_id: int
    teacher_id: Optional[int] = None
    room_id: Optional[int] = None
    study_program_ids: List[int] = []
    expected_size: Optional[int] = None
    notes: Optional[str] = None
    self_study: bool = False
    allow_teacher_conflict: bool = False