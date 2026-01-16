import shutil
import os
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from config import settings
from graph import app_graph
from langchain_core.messages import HumanMessage

app = FastAPI(title="Multi-Source AI Agent")

# In-memory storage for the current session's files. 
# Note: For production, use a database or Redis to track this per user.
# Ensure upload directory exists immediately
if not os.path.exists(settings.UPLOAD_DIR):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# Function to get files from the local folder
def get_local_files():
    return [
        f for f in os.listdir(settings.UPLOAD_DIR)
        if f.lower().endswith((".csv", ".db"))
    ]

# Initialize session_files with whatever is already in the folder
session_files = get_local_files()

class QueryRequest(BaseModel):
    prompt: str


@app.get("/files")
async def list_files():
    """
    Returns a list of all files currently inside the uploads folder.
    This allows the UI to 'see' files without re-uploading.
    """
    global session_files
    session_files = get_local_files()
    return {"files": session_files}


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Upload one or multiple files (CSV or DB).
    They are stored in the uploads folder and tracked for the session.
    """

    uploaded_names = []
    for file in files:
        file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            if file.filename not in session_files:
                session_files.append(file.filename)
            uploaded_names.append(file.filename)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error saving {file.filename}: {e}")
    
    return {
        "message": "Files uploaded successfully",
        "current_files": session_files
    }



@app.post("/query")
async def process_query(request: QueryRequest):
    """
    Query the agent using files currently in the uploads folder.
    """
    available_files = get_local_files()

    if not available_files:
        raise HTTPException(
            status_code=400,
            detail="No data files found in the uploads directory."
        )

    # Prepare the Initial State for LangGraph
    initial_state = {
        "messages": [HumanMessage(content=request.prompt)],
        "file_paths": available_files,
        "active_worker": "supervisor"
    }

    try:
        # thread_id: user_session_1 keeps a single conversation thread
        config = {"configurable": {"thread_id": "user_session_1"},
                  "recursion_limit": 100}
        
        final_output = app_graph.invoke(initial_state, config=config)
        
        return {
            "query": request.prompt,
            "active_files": available_files,
            "answer": final_output["messages"][-1].content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)