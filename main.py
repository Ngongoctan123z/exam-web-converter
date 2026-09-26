from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import uuid
from pdf2docx import Converter

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

def cleanup_files(files):
    for f in files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

@app.get("/")
def health_check():
    return {"status": "ok", "service": "exam-web-converter-offline"}

@app.post("/api/v1/convert")
def convert_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    from_format: str = Form(alias="from"),
    to_format: str = Form(alias="to")
):
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

        # Convert purely offline using pdf2docx
        cv = Converter(input_path)
        cv.convert(output_path)
        cv.close()

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
