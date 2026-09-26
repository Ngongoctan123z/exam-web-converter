import sys
import os
import fitz # PyMuPDF
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from docxcompose.composer import Composer
from docx import Document
import io

def split_pdf(input_path, output_dir, max_size_mb=1.8):
    """Splits PDF into smaller chunks if it exceeds max_size_mb"""
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    chunks = []
    
    if file_size_mb <= max_size_mb:
        chunks.append(input_path)
        return chunks
        
    doc = fitz.open(input_path)
    num_pages = len(doc)
    
    # Estimate pages per chunk
    avg_page_size = file_size_mb / num_pages
    pages_per_chunk = max(1, int(max_size_mb / avg_page_size))
    
    for i in range(0, num_pages, pages_per_chunk):
        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(doc, from_page=i, to_page=min(i + pages_per_chunk - 1, num_pages - 1))
        chunk_path = os.path.join(output_dir, f"chunk_{os.path.basename(input_path)}_{i}.pdf")
        chunk_doc.save(chunk_path)
        chunk_doc.close()
        chunks.append(chunk_path)
        
    doc.close()
    return chunks

def convert_pdf_to_docx_google(pdf_path, drive_service):
    """Uploads PDF to Google Drive as Google Doc, downloads as DOCX, and deletes it."""
    file_metadata = {
        'name': os.path.basename(pdf_path),
        'mimeType': 'application/vnd.google-apps.document'
    }
    media = MediaFileUpload(pdf_path, mimetype='application/pdf', resumable=True)
    
    # Upload
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')
    
    # Download as DOCX
    request = drive_service.files().export_media(fileId=file_id, mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    docx_content = request.execute()
    
    # Delete from Drive
    drive_service.files().delete(fileId=file_id).execute()
    
    return docx_content

def merge_docx(docx_contents, output_path):
    """Merges multiple DOCX contents into a single file."""
    if not docx_contents:
        raise Exception("No content to merge")
        
    if len(docx_contents) == 1:
        with open(output_path, 'wb') as f:
            f.write(docx_contents[0])
        return

    # Open first document
    master = Document(io.BytesIO(docx_contents[0]))
    composer = Composer(master)
    
    # Append the rest
    for content in docx_contents[1:]:
        doc = Document(io.BytesIO(content))
        # Append adds page break by default
        composer.append(doc)
        
    composer.save(output_path)

def main():
    if len(sys.argv) < 3:
        print("Usage: python pdf_to_docx_google.py <input_pdf> <output_docx>")
        sys.exit(1)
        
    input_pdf = sys.argv[1]
    output_docx = sys.argv[2]
    
    try:
        # Load credentials
        creds_path = os.path.join(os.path.dirname(__file__), "..", "google-credentials.json")
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Split PDF if necessary
        temp_dir = os.path.dirname(output_docx)
        chunks = split_pdf(input_pdf, temp_dir)
        
        # Convert chunks
        docx_contents = []
        for chunk in chunks:
            docx_contents.append(convert_pdf_to_docx_google(chunk, drive_service))
            
            # Clean up chunk if it's a temp file
            if chunk != input_pdf:
                os.remove(chunk)
                
        # Merge DOCX
        merge_docx(docx_contents, output_docx)
        
        print(f"Successfully converted {input_pdf} to {output_docx}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
