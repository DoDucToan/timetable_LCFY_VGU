# Timetable Builder (DB-backed)

This rebuild keeps the same overall project structure under `app/`, removes the old JSON textbox workflow, and seeds the database from the extracted FY2025 Phase 4 timetable.

## What it does
- Uses SQLite instead of pasted JSON input.
- Seeds sample data from `data/FY2025_Timetable_Phase_4_complete.json`.
- Lets users add groups with the mouse.
- Lets users click one cell or Ctrl/Cmd-click multiple cells in the same timeslot row.
- Supports three class modes:
  - Require all students in group
  - Study program class
  - Elective
- Checks constraints:
  - teacher clash
  - room clash
  - room capacity
  - group-wide clash
  - study-program clash within a group
- Exports an Excel file and adds teacher timeslot counts below the timetable.

## Structure
```text
app/
  main.py
  database.py
  models.py
  schemas.py
  scheduler.py
  seed.py
  excel_exporter.py
  templates/index.html
  static/script.js
  static/style.css
```

## First run
```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open:
```text
http://127.0.0.1:8000
```

## Copy into your current project
Replace your existing `app/` folder files with the files from this package.
Also copy:
- `requirements.txt`
- `data/FY2025_Timetable_Phase_4_complete.json`

## Reset database and reseed
Delete `timetable.db`, then run the app again.
The startup hook creates the DB and seeds it automatically.

## Mouse interaction notes
- Single click a cell: select it and open add-class modal.
- Ctrl/Cmd-click multiple cells in the same row: multi-select for program/elective classes.
- Use the plus button on the far-right header to add a new group.

## Export
Use the **Export Excel** button in the UI.
The file is generated at runtime from the current DB state.
