from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
from dotenv import load_dotenv
import dropbox

load_dotenv()

app = Flask(__name__)
DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SHARED_FOLDER_PATH = os.environ.get("SHARED_FOLDER_PATH")

dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

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

def upload_to_dropbox(local_path, dropbox_subfolder, file_name):
    dropbox_path = f"{SHARED_FOLDER_PATH}/{dropbox_subfolder}/{file_name}".replace("//", "/")
    with open(local_path, "rb") as f:
        dbx.files_upload(
            f.read(),
            dropbox_path,
            mode=dropbox.files.WriteMode.overwrite
        )
    print(f"Uploaded to Dropbox: {dropbox_path}")
    return dropbox_path

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
        upload_to_dropbox(img_path, f"{dropbox_path}/{name}")

# Upload the CSV file
upload_to_dropbox(csv_path, f"{dropbox_path}/image_metadata.csv")

# ✅ Add this block below the uploads
downloaded_count = sum(1 for _, name in image_data if os.path.exists(os.path.join(image_dir, name)))
folder_link = f"https://www.dropbox.com/home{dropbox_path}"
message = f"Extracted {downloaded_count} images and uploaded to folder: <a href='{folder_link}' target='_blank'>{folder_link}</a>"
