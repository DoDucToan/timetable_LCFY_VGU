# Timetable Builder for LCFY VGU

A database-backed timetable management application for the Language Center and Foundation Year (LCFY) at Vietnamese-German University (VGU).

The application helps staff create and manage academic timetables by cycle, group, study program, course, teacher, room, and timeslot. It also validates common scheduling conflicts and exports the final timetable to Excel.

---

## Table of Contents

- [Main Features](#main-features)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Run the Application](#run-the-application)
- [How to Use the Application](#how-to-use-the-application)
- [Import Data](#import-data)
- [Export Timetable](#export-timetable)
- [Database Notes](#database-notes)
- [Common Issues](#common-issues)
- [Useful Git Commands](#useful-git-commands)

---

## Main Features

### Timetable management

- Create and manage academic cycles.
- Open each cycle on its own timetable page.
- Add, edit, duplicate, and delete cycles.
- Create groups and place classes into timetable cells.
- Select one cell or multiple cells in the same timeslot row.
- Support normal timetable blocks and optional German-specific timeslots.

### Master data management

The system includes pages for managing:

- Teachers
- Rooms
- Courses
- Course tags
- Study programs
- Group tags
- Groups
- Requirements

### Class types

The timetable supports three main class modes:

1. **Require all students in group**  
   Used when every student in the selected group must attend the class.

2. **Study program class**  
   Used when only students from specific study programs inside a group attend the class.

3. **Elective**  
   Used for optional classes.

### Conflict and validation checks

The system checks common scheduling problems, including:

- Teacher clash
- Room clash
- Room capacity
- Group-wide clash
- Study-program clash inside a group
- Missing teacher or room before export
- Missing required class sessions before export

### Excel export

The application can export timetables to Excel, including:

- Full timetable export
- Export by study program
- Export by group
- Export by group tag
- Export by course
- Export by teacher
- Export all groups
- Export all courses
- Export all teachers

---

## Technology Stack

### Backend

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- SQLite
- Pydantic
- OpenPyXL
- Pillow
- python-multipart

### Frontend

- HTML
- CSS
- JavaScript
- Jinja2 templates

### Database

- SQLite database file: `timetable.db`

---

## Project Structure

```text
timetable_LCFY_VGU/
├── alembic/
├── app/
│   ├── migrations/
│   │   └── versions/
│   ├── static/
│   │   ├── VGU-Logo.png
│   │   ├── favicon.png
│   │   ├── script.js
│   │   └── style.css
│   ├── templates/
│   │   ├── course-tags.html
│   │   ├── courses.html
│   │   ├── data_sync.html
│   │   ├── entity.html
│   │   ├── entity_base.html
│   │   ├── group-tags.html
│   │   ├── home.html
│   │   ├── index.html
│   │   ├── rooms.html
│   │   ├── study-programs.html
│   │   ├── teachers.html
│   │   └── upload.html
│   ├── __init__.py
│   ├── database.py
│   ├── excel_exporter.py
│   ├── main.py
│   ├── models.py
│   ├── scheduler.py
│   ├── schemas.py
│   └── seed.py
├── data/
│   └── FY2025_Timetable_Phase_4_complete.json
├── exports/
├── tmp_export_test/
├── FY2025_Timetable_Phase 4.xlsx
├── courses_current_data_new.xlsx
├── courses_current_data_old.xlsx
├── import_excel_entities.py
├── requirements.txt
├── run_app.bat
├── run_app.py
├── timetable.db
└── README.md
```

---

## Requirements

Before running the project, install:

- Python 3.10 or newer is recommended.
- Git.
- A modern browser such as Chrome, Edge, or Firefox.

No external database server is required because the project uses SQLite.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/DoDucToan/timetable_LCFY_VGU.git
cd timetable_LCFY_VGU
```

### 2. Create a virtual environment

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Windows Command Prompt

```cmd
python -m venv .venv
.venv\Scripts\activate
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `pip install -r requirements.txt` fails because the requirements are stored on one line, install the packages manually:

```bash
pip install fastapi==0.116.1 "uvicorn[standard]==0.35.0" sqlalchemy==2.0.43 jinja2==3.1.6 openpyxl==3.1.5 Pillow==12.2.0 pydantic==2.11.7 python-multipart==0.0.7
```

---

## Run the Application

### Option 1: Run with Uvicorn

```bash
python -m uvicorn app.main:app --reload
```

Then open this address in your browser:

```text
http://127.0.0.1:8000
```

### Option 2: Run with the Python helper script

```bash
python run_app.py
```

### Option 3: Run on Windows with the batch file

```cmd
run_app.bat
```

The batch file creates a virtual environment if needed, activates it, installs dependencies, and starts the FastAPI app.

---

## How to Use the Application

### 1. Open the home page

Open:

```text
http://127.0.0.1:8000
```

The home page shows the available cycles.

### 2. Select or create a cycle

A cycle represents an academic timetable period, for example:

```text
FY2025 Phase 4
```

On the timetable page, use the cycle controls to:

- Add a new cycle.
- Edit an existing cycle.
- Duplicate an existing cycle.
- Delete a cycle.

After opening a cycle, the timetable board is displayed.

### 3. Prepare master data

Before scheduling classes, check or create the required master data:

- Teachers
- Rooms
- Courses
- Course tags
- Study programs
- Group tags
- Groups
- Requirements

These pages are available from the navigation menu.

Recommended setup order:

1. Create course tags.
2. Create courses and assign course tags.
3. Create teachers and assign teacher course tags.
4. Create rooms and capacities.
5. Create study programs.
6. Create group tags.
7. Create groups.
8. Define requirements.
9. Start scheduling classes.

### 4. Add groups to the timetable

Groups are the columns of the timetable board.

A group should include:

- Group code
- Group name
- Group tag
- Capacity / student size
- Study programs inside the group
- Required courses and required number of sessions if applicable

### 5. Add a class

To create a class:

1. Click a timetable cell.
2. Choose the class mode.
3. Select the course.
4. Select the teacher.
5. Select the room.
6. Add expected size if needed.
7. Add notes if needed.
8. Click **Create class**.

### 6. Add a class for multiple groups or programs

To schedule a class across multiple cells:

1. Hold `Ctrl` on Windows or `Cmd` on macOS.
2. Click multiple cells in the same timeslot row.
3. Create the class from the modal.
4. The system will validate whether the class can be placed without conflicts.

### 7. Understand timetable labels

The timetable includes labels such as:

- `E` = Elective
- `Gs` = Multiple Groups Class
- `Ps` = Multiple Programs Class

---

## Import Data

The project includes an upload/import area.

Supported import categories include:

- Teachers
- Study programs
- Course tags
- Rooms
- Courses
- Group tags
- Groups
- Requirements

General import workflow:

1. Open the upload/import page.
2. Choose the correct import category.
3. Select the Excel file.
4. Upload the file.
5. Check whether the data appears correctly in the relevant management page.

Important: the import file should follow the expected column structure used by the application. If an upload fails, check the column names, empty rows, and duplicated values.

---

## Export Timetable

Use the **Export** button in the timetable page.

Available export options:

- Export Excel
- Export by program
- Export for group
- Export by group tags
- Export all groups
- Export by course
- Export all courses
- Export by teacher
- Export all teachers

Before exporting, make sure:

- Classes are deployed.
- Each deployed class has a teacher.
- Each deployed class has a room.
- Required sessions are fully scheduled.
- There are no unresolved conflicts.

If the export fails, the application usually shows a message explaining what needs to be fixed.

---

## Database Notes

The application uses SQLite.

Database file:

```text
timetable.db
```

The database is created and used locally. You do not need to install MySQL, PostgreSQL, or SQL Server.

### Reset the database

To reset the local database:

1. Stop the running application.
2. Delete:

```text
timetable.db
```

3. Start the app again:

```bash
python -m uvicorn app.main:app --reload
```

The application startup process will recreate the database and load the initial data.

Warning: deleting `timetable.db` removes the local timetable data.

---

## Common Issues

### 1. `python` is not recognized

Python is not installed or not added to PATH.

Fix:

- Install Python.
- During installation, select **Add Python to PATH**.
- Restart the terminal.

### 2. Virtual environment cannot activate in PowerShell

PowerShell may block script execution.

Fix:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 3. Port 8000 is already in use

Another app is already using port 8000.

Fix option 1: stop the other app.

Fix option 2: run this app on another port:

```bash
python -m uvicorn app.main:app --reload --port 8001
```

Then open:

```text
http://127.0.0.1:8001
```

### 4. Dependency installation fails

Try upgrading pip:

```bash
python -m pip install --upgrade pip
```

Then install the packages manually:

```bash
pip install fastapi==0.116.1 "uvicorn[standard]==0.35.0" sqlalchemy==2.0.43 jinja2==3.1.6 openpyxl==3.1.5 Pillow==12.2.0 pydantic==2.11.7 python-multipart==0.0.7
```

### 5. Export fails

Common causes:

- A deployed class has no teacher.
- A deployed class has no room.
- Required sessions are not fully scheduled.
- Teacher or room conflicts still exist.
- The selected export filter has no deployed classes.

Check the timetable board and requirements section before exporting again.

---

## Useful Git Commands

After replacing or updating this README file:

```bash
git add README.md
git commit -m "docs: improve README user guidance"
git push
```

If you also changed code files:

```bash
git add .
git commit -m "update timetable builder"
git push
```

---

## Author

Created by Do Duc Toan.

Repository:

```text
https://github.com/DoDucToan/timetable_LCFY_VGU
```
