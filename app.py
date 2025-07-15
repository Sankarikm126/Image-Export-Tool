from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = '/etc/secrets/sodium-daylight-466004-h9-3e5e71cf4e5b.json'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('drive', 'v3', credentials=credentials)
MY_DRIVE_FOLDER_ID = os.environ.get("MY_DRIVE_FOLDER_ID")  # Target folder in user's My Drive

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def crawl_and_extract(base_url, output_dir, csv_path):
    visited = set()
    image_urls = set()
    queue = [base_url]

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["page_url", "image_url", "image_name", "alt_text_present", "alt_text", "downloaded"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                res = requests.get(url)
                soup = BeautifulSoup(res.text, "html.parser")

                for img in soup.find_all("img"):
                    src = img.get("src")
                    if src and "/_next/image" in src and "url=" in src:
                        parsed = urlparse(src)
                        query = parse_qs(parsed.query)
                        if "url" in query:
                            src = query["url"][0]

                    alt = img.get("alt", "")
                    if src:
                        full_img_url = urljoin(url, src)
                        image_name = os.path.basename(full_img_url.split("?")[0])

                        image_path = os.path.join(output_dir, image_name)
                        downloaded = "No"
                        try:
                            img_data = requests.get(full_img_url).content
                            with open(image_path, 'wb') as f:
                                f.write(img_data)
                            downloaded = "Yes"
                            image_urls.add((full_img_url, image_name))
                        except Exception as e:
                            print(f"Error downloading {full_img_url}: {e}")

                        writer.writerow({
                            "page_url": url,
                            "image_url": full_img_url,
                            "image_name": image_name,
                            "alt_text_present": "Yes" if alt else "No",
                            "alt_text": alt,
                            "downloaded": downloaded
                        })

                for a in soup.find_all("a", href=True):
                    link = urljoin(url, a['href'])
                    if is_internal_link(link, base_url) and link.startswith(base_url):
                        queue.append(link)

            except Exception as e:
                print(f"Failed to process {url}: {e}")

    return image_urls

def upload_to_gdrive(local_path, file_name):
    file_metadata = {
        'name': file_name,
        'parents': [MY_DRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(local_path, resumable=True)
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    print(f"Uploaded to Google Drive: {file.get('id')}")
    return file.get('id')

@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    drive_links = []
    if request.method == "POST":
        parent_url = request.form["url"]
        course_folder = request.form.get("course_folder", "").strip("/")

        if not course_folder:
            message = "Course folder is required to organize extracted content."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                image_dir = os.path.join(tmpdir, "images")
                os.makedirs(image_dir, exist_ok=True)
                csv_path = os.path.join(tmpdir, "image_metadata.csv")

                image_data = crawl_and_extract(parent_url, image_dir, csv_path)

                for _, name in image_data:
                    img_path = os.path.join(image_dir, name)
                    if os.path.exists(img_path):
                        file_id = upload_to_gdrive(img_path, name)
                        drive_links.append(f"https://drive.google.com/file/d/{file_id}/view")

                meta_id = upload_to_gdrive(csv_path, "image_metadata.csv")
                drive_links.append(f"https://drive.google.com/file/d/{meta_id}/view")

                message = "Upload to My Drive completed!" 

    return render_template("index.html", message=message, links=drive_links)
