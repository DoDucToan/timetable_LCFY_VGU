# Run this script to start the Timetable Builder FastAPI app

import uvicorn



if __name__ == "__main__":
    # run app in venv
    
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
