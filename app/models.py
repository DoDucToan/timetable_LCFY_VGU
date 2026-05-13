from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Cycle(Base):
    __tablename__ = "cycle"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    year_starting = Column(Integer, nullable=False)
    german_timeslots = Column(Boolean, default=False, nullable=False)

    timetables = relationship("Timetable", back_populates="cycle")


class Timetable(Base):
    __tablename__ = "timetable"

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("cycle.id"), nullable=False)
    in_action = Column(Boolean, default=False, nullable=False)

    cycle = relationship("Cycle", back_populates="timetables")
    groups = relationship("Group", back_populates="timetable")


class GroupTag(Base):
    __tablename__ = "group_tag"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)

    groups = relationship("Group", back_populates="group_tag")
    course_links = relationship("CourseForGroupTag", back_populates="group_tag")


class StudyProgram(Base):
    __tablename__ = "study_program"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False, unique=True)

    group_links = relationship("GroupStudyProgram", back_populates="study_program")
    course_links = relationship("StudyProgramCourse", back_populates="study_program")


class CourseTag(Base):
    __tablename__ = "course_tag"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)

    courses = relationship("Course", back_populates="course_tag")
    teacher_links = relationship("TeacherCourseTag", back_populates="course_tag")


class Room(Base):
    __tablename__ = "room"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    capacity_num = Column(Integer, nullable=False, default=80)

    classes = relationship("ScheduledClass", back_populates="room")


class Timeslot(Base):
    __tablename__ = "timeslot"

    id = Column(Integer, primary_key=True)
    weekday = Column(String, nullable=False)
    day_index = Column(Integer, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    label = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, unique=True)

    classes = relationship("ScheduledClass", back_populates="timeslot")


class Teacher(Base):
    __tablename__ = "teacher"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)

    classes = relationship("ScheduledClass", back_populates="teacher")
    course_tag_links = relationship("TeacherCourseTag", back_populates="teacher")


class Course(Base):
    __tablename__ = "course"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False, unique=True)
    require_all_student_in_group = Column(Boolean, default=False, nullable=False)
    elective = Column(Boolean, default=False, nullable=False)
    name = Column(String, nullable=False)
    course_tag_id = Column(Integer, ForeignKey("course_tag.id"), nullable=False)

    course_tag = relationship("CourseTag", back_populates="courses")
    study_program_links = relationship("StudyProgramCourse", back_populates="course")
    group_tag_links = relationship("CourseForGroupTag", back_populates="course")
    group_course_links = relationship("CourseForGroup", back_populates="course")
    classes = relationship("ScheduledClass", back_populates="course")


class StudyProgramCourse(Base):
    __tablename__ = "study_program_has_course"
    __table_args__ = (
        UniqueConstraint("study_program_id", "course_id", "timetable_id", name="uq_study_program_course"),
    )

    id = Column(Integer, primary_key=True)
    study_program_id = Column(Integer, ForeignKey("study_program.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    timetable_id = Column(Integer, ForeignKey("timetable.id"), nullable=False)
    sessions_required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    study_program = relationship("StudyProgram", back_populates="course_links")
    course = relationship("Course", back_populates="study_program_links")


class Group(Base):
    __tablename__ = "group_tbl"
    __table_args__ = (
        UniqueConstraint("timetable_id", "code", name="uq_group_timetable_code"),
    )

    id = Column(Integer, primary_key=True)
    timetable_id = Column(Integer, ForeignKey("timetable.id"), nullable=False)
    group_tag_id = Column(Integer, ForeignKey("group_tag.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    size_num = Column(Integer, nullable=False, default=40)
    sort_order = Column(Integer, nullable=False, default=0)

    timetable = relationship("Timetable", back_populates="groups")
    group_tag = relationship("GroupTag", back_populates="groups")
    study_program_links = relationship(
        "GroupStudyProgram",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    classes = relationship(
        "ScheduledClass",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    course_requirements = relationship(
        "CourseForGroup",
        back_populates="group",
        cascade="all, delete-orphan",
    )


class GroupStudyProgram(Base):
    __tablename__ = "group_has_study_program"
    __table_args__ = (
        UniqueConstraint("group_id", "study_program_id", name="uq_group_study_program"),
    )

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("group_tbl.id"), nullable=False)
    study_program_id = Column(Integer, ForeignKey("study_program.id"), nullable=False)

    group = relationship("Group", back_populates="study_program_links")
    study_program = relationship("StudyProgram", back_populates="group_links")


class CourseForGroupTag(Base):
    __tablename__ = "course_for_group_tag"
    __table_args__ = (
        UniqueConstraint("group_tag_id", "course_id", "timetable_id", name="uq_group_tag_course"),
    )

    id = Column(Integer, primary_key=True)
    group_tag_id = Column(Integer, ForeignKey("group_tag.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    timetable_id = Column(Integer, ForeignKey("timetable.id"), nullable=False)
    sessions_required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    group_tag = relationship("GroupTag", back_populates="course_links")
    course = relationship("Course", back_populates="group_tag_links")


class CourseForGroup(Base):
    __tablename__ = "course_for_group_only"
    __table_args__ = (
        UniqueConstraint("group_id", "course_id", name="uq_group_course"),
    )

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("group_tbl.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    sessions_required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    group = relationship("Group", back_populates="course_requirements")
    course = relationship("Course", back_populates="group_course_links")


class TeacherCourseTag(Base):
    __tablename__ = "teacher_course_tag"
    __table_args__ = (
        UniqueConstraint("teacher_id", "course_tag_id", name="uq_teacher_course_tag"),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teacher.id"), nullable=False)
    course_tag_id = Column(Integer, ForeignKey("course_tag.id"), nullable=False)

    teacher = relationship("Teacher", back_populates="course_tag_links")
    course_tag = relationship("CourseTag", back_populates="teacher_links")


class ScheduledClass(Base):
    __tablename__ = "class"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("group_tbl.id"), nullable=False)
    timeslot_id = Column(Integer, ForeignKey("timeslot.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("room.id"), nullable=True)
    teacher_id = Column(Integer, ForeignKey("teacher.id"), nullable=True)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    study_program_id = Column(Integer, ForeignKey("study_program.id"), nullable=True)
    deploy = Column(Boolean, default=True, nullable=False)
    shared_key = Column(String, nullable=True)
    expected_size = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)
    source = Column(String, nullable=True)

    group = relationship("Group", back_populates="classes")
    timeslot = relationship("Timeslot", back_populates="classes")
    room = relationship("Room", back_populates="classes")
    teacher = relationship("Teacher", back_populates="classes")
    course = relationship("Course", back_populates="classes")
    study_program = relationship("StudyProgram")