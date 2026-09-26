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

import fitz
from concurrent.futures import ProcessPoolExecutor
from docxcompose.composer import Composer
from docx import Document
import io

def convert_chunk(args):
    input_pdf, output_docx, start_page, end_page = args
    cv = Converter(input_pdf)
    cv.convert(output_docx, start=start_page, end=end_page)
    cv.close()
    return output_docx

@app.post("/api/v1/convert")
def convert_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    from_format: str = Form(alias="from"),
    to_format: str = Form(alias="to")
):
    if from_format != "pdf" or to_format != "docx":
        raise HTTPException(status_code=400, detail="Currently only PDF to DOCX is supported")

    file_id = str(uuid.uuid4())
    input_filename = f"{file_id}.pdf"
    output_filename = f"{file_id}.docx"
    input_path = os.path.join(TEMP_DIR, input_filename)
    output_path = os.path.join(TEMP_DIR, output_filename)
    
    files_to_cleanup = [input_path, output_path]

    try:
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Count pages
        doc = fitz.open(input_path)
        num_pages = len(doc)
        doc.close()

        if num_pages <= 3:
            # For small files, just do it directly
            cv = Converter(input_path)
            cv.convert(output_path, multi_processing=True, cpu_count=4)
            cv.close()
        else:
            # Split and process concurrently
            chunk_size = 5
            tasks = []
            for i in range(0, num_pages, chunk_size):
                end = min(i + chunk_size, num_pages)
                chunk_out = os.path.join(TEMP_DIR, f"{file_id}_part_{i}.docx")
                files_to_cleanup.append(chunk_out)
                tasks.append((input_path, chunk_out, i, end))

            # Run in parallel
            with ProcessPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(convert_chunk, tasks))

            # Merge DOCX chunks
            master = Document(results[0])
            composer = Composer(master)
            for res in results[1:]:
                doc_part = Document(res)
                composer.append(doc_part)
            
            composer.save(output_path)

        background_tasks.add_task(cleanup_files, files_to_cleanup)

        return FileResponse(
            path=output_path, 
            filename=f"converted_{file.filename}.docx",
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        cleanup_files(files_to_cleanup)
        raise HTTPException(status_code=500, detail=str(e))
