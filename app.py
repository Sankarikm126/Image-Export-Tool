import os
import csv
import tempfile
import requests
from urllib.parse import urljoin, urlparse
from flask import Flask, request, render_template
from bs4 import BeautifulSoup
import threading

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- Flask setup ---
app = Flask(__name__)

# --- Google Drive setup ---
SERVICE_ACCOUNT_FILE = 'credentials.json'  # <-- Make sure this file exists
SCOPES = ['https://www.googleapis.com/auth/drive']
GOOGLE_DRIVE_PARENT_FOLDER_ID = '1m677PtYekbqioM6NI-AvElQ9bQ8NqPE-'  # <-- Replace this

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=creds)


# --- Utility: Create a folder in Google Drive ---
def create_drive_folder(name, parent_id):
    file_metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = drive_service.files().create(
        body=file_metadata,
        fields='id'
    ).execute()
    print(f"📁 Created Google Drive folder: {name} (ID: {folder.get('id')})")
    return folder.get('id')


# --- Utility: Upload file to a Drive folder ---
def upload_to_gdrive(local_path, filename, parent_folder_id):
    file_metadata = {
        'name': filename,
        'parents': [parent_folder_id]
    }
    media = MediaFileUpload(local_path, resumable=True)
    uploaded_file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    print(f"✅ Uploaded to Google Drive: {filename} (ID: {uploaded_file.get('id')})")


# --- Utility: Determine if a link is internal ---
def is_internal_link(link, base_url):
    return urlparse(link).netloc == urlparse(base_url).netloc


# --- Scraper: Get all images from internal pages ---
def scrape_images_from_all_links(base_url):
    visited = set()
    queue = [base_url]
    image_data = []
    temp_dir = tempfile.mkdtemp()

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            for img in soup.find_all("img"):
                src = img.get("src")
                alt = img.get("alt", "")
                if not src:
                    continue

                img_url = urljoin(url, src)
                try:
                    img_resp = requests.get(img_url, timeout=10)
                    img_resp.raise_for_status()

                    filename = os.path.basename(urlparse(img_url).path)
                    local_path = os.path.join(temp_dir, filename)

                    with open(local_path, "wb") as f:
                        f.write(img_resp.content)

                    image_data.append({
                        "filename": filename,
                        "local_path": local_path,
                        "alt": alt
                    })

                    print(f"✅ Downloaded image: {filename}")

                except Exception as e:
                    print(f"❌ Failed to download image {img_url}: {e}")

            for a in soup.find_all("a", href=True):
                link = urljoin(url, a['href'])
                if is_internal_link(link, base_url):
                    queue.append(link)

        except Exception as e:
            print(f"❌ Failed to fetch {url}: {e}")

    return image_data, temp_dir


# --- Background uploader ---
def background_upload(image_data, subfolder_name, temp_dir):
    try:
        # Create a folder inside the main Google Drive folder
        subfolder_id = create_drive_folder(subfolder_name, GOOGLE_DRIVE_PARENT_FOLDER_ID)

        # Save image metadata as CSV
        csv_path = os.path.join(temp_dir, "image_metadata.csv")
        with open(csv_path, "w", newline="", encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Filename", "Alt Text"])
            for item in image_data:
                writer.writerow([item["filename"], item["alt"]])

        # Upload images
        for item in image_data:
            upload_to_gdrive(item["local_path"], item["filename"], subfolder_id)

        # Upload CSV
        upload_to_gdrive(csv_path, "image_metadata.csv", subfolder_id)

    except Exception as e:
        print(f"❌ Error in background upload: {e}")


# --- Flask route ---
@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    if request.method == 'POST':
        parent_url = request.form.get('url')
        folder_name = request.form.get('folder_name', 'ExtractedJob')
        print(f"🌐 Starting scrape from: {parent_url}")
        print(f"📁 Target Drive folder name: {folder_name}")

        try:
            image_data, temp_dir = scrape_images_from_all_links(parent_url)
            threading.Thread(target=background_upload, args=(image_data, folder_name, temp_dir)).start()
            message = f"🔄 Extracting {len(image_data)} images and uploading to Google Drive in the background."
        except Exception as e:
            message = f"❌ Failed to extract: {e}"

    return render_template("index.html", message=message)


if __name__ == '__main__':
    app.run(debug=True)
