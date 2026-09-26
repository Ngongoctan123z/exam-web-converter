from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import uuid
import io
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "temp_uploads"
os.makedirs(TEMP_DIR, exist_ok=True)

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save updated token
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        else:
            raise Exception("token.json không hợp lệ. Vui lòng chạy get_token.py để đăng nhập lại.")
    return build('drive', 'v3', credentials=creds)

def cleanup_files(files):
    for f in files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

@app.get("/")
def health_check():
    return {"status": "ok", "service": "exam-web-converter-googledrive"}

@app.post("/api/v1/convert")
def convert_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    from_format: str = Form(alias="from"),
    to_format: str = Form(alias="to")
):
    if from_format != "pdf" or to_format != "docx":
        raise HTTPException(status_code=400, detail="Hiện tại chỉ hỗ trợ chuyển đổi từ PDF sang DOCX")

    file_id = str(uuid.uuid4())
    input_filename = f"{file_id}.pdf"
    output_filename = f"{file_id}.docx"
    input_path = os.path.join(TEMP_DIR, input_filename)
    output_path = os.path.join(TEMP_DIR, output_filename)

    files_to_cleanup = [input_path, output_path]
    drive_file_id = None
    service = None

    try:
        # 1. Lưu file PDF tải lên
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Khởi tạo Google Drive Service
        service = get_drive_service()

        # 3. Tải PDF lên Google Drive và nhờ nó OCR thành Google Docs
        file_metadata = {
            'name': file.filename,
            'mimeType': 'application/vnd.google-apps.document'
        }
        media = MediaFileUpload(input_path, mimetype='application/pdf', resumable=True)
        
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        drive_file_id = uploaded_file.get('id')

        # 4. Tải file Google Docs đó về dưới định dạng DOCX
        request = service.files().export_media(fileId=drive_file_id, mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        fh = io.FileIO(output_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        # Xóa rác local
        background_tasks.add_task(cleanup_files, files_to_cleanup)

        # Trả về file DOCX
        return FileResponse(
            path=output_path, 
            filename=f"converted_{file.filename}.docx",
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        cleanup_files(files_to_cleanup)
        raise HTTPException(status_code=500, detail=f"Lỗi Convert: {str(e)}")
    finally:
        # 5. Luôn luôn xóa file trên Google Drive để tránh đầy 15GB
        if service and drive_file_id:
            try:
                service.files().delete(fileId=drive_file_id).execute()
            except:
                pass
