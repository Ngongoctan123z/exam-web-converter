from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import uuid
import sys
from pdf_to_docx_google import split_pdf, convert_pdf_to_docx_google, merge_docx
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "temp_uploads"
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize Google Drive Service
try:
    creds_path = os.path.join(os.path.dirname(__file__), "google-credentials.json")
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=['https://www.googleapis.com/auth/drive']
    )
    drive_service = build('drive', 'v3', credentials=creds)
except Exception as e:
    print(f"Error initializing Google Drive API: {e}")
    drive_service = None

def cleanup_files(files):
    for f in files:
        if os.path.exists(f):
            os.remove(f)

@app.get("/")
def health_check():
    return {"status": "ok", "service": "exam-web-converter"}

@app.post("/api/v1/convert")
async def convert_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    from_format: str = Form(alias="from"),
    to_format: str = Form(alias="to")
):
    if not drive_service:
        raise HTTPException(status_code=500, detail="Google Drive API not configured")

    if from_format != "pdf" or to_format != "docx":
        raise HTTPException(status_code=400, detail="Currently only PDF to DOCX is supported by this microservice")

    file_id = str(uuid.uuid4())
    input_filename = f"{file_id}.pdf"
    output_filename = f"{file_id}.docx"
    input_path = os.path.join(TEMP_DIR, input_filename)
    output_path = os.path.join(TEMP_DIR, output_filename)

    try:
        # Save uploaded file
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process: Split -> Upload -> Convert -> Merge
        chunks = split_pdf(input_path, TEMP_DIR)
        
        docx_contents = []
        for chunk in chunks:
            docx_contents.append(convert_pdf_to_docx_google(chunk, drive_service))
            if chunk != input_path:
                os.remove(chunk)
                
        merge_docx(docx_contents, output_path)

        # Schedule cleanup after response
        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            path=output_path, 
            filename=f"converted_{file.filename}.docx",
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        cleanup_files([input_path, output_path])
        raise HTTPException(status_code=500, detail=str(e))
