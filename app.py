from flask import Flask, request, render_template
import os, requests, csv, tempfile, traceback
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import dropbox
import traceback
from dotenv import load_dotenv

load_dotenv()

from PIL import Image  # Ensure 'Pillow' is in requirements.txt
from io import BytesIO

app = Flask(__name__)

DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SHARED_FOLDER_PATH = os.environ.get("SHARED_FOLDER_PATH", "/Shared/SME")
dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def upload_to_dropbox(local_path, dropbox_path):
    try:
        print(f"Uploading to Dropbox: {dropbox_path}")
        with open(local_path, "rb") as f:
            dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        return f"https://www.dropbox.com/home{dropbox_path}"
    except Exception as e:
        print(f"Dropbox upload failed for {local_path}: {e}")
        return ""

def crawl_and_extract(base_url, output_dir, csv_path, dropbox_subfolder):
    visited = set()
    image_urls = set()
    queue = [base_url]

    image_dir = os.path.join(output_dir, "Images")
    os.makedirs(image_dir, exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            "page_url", "image_url", "image_name", "alt_text_present", "alt_text", "dropbox_url"
        ])
        writer.writeheader()

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                print(f"Processing page: {url}")
                res = requests.get(url, timeout=10)
                soup = BeautifulSoup(res.text, "html.parser")

                for img in soup.find_all("img"):
                    src = img.get("src")
                    if src and "/_next/image" not in src:
                        parsed_src = urlparse(src)
                        query = parse_qs(parsed_src.query)
                        img_url = query.get("url", [src])[0] if "url" in query else src
                        full_img_url = urljoin(url, img_url)

                        if full_img_url in image_urls:
                            continue
                        image_urls.add(full_img_url)

                        try:
                            img_content = requests.get(full_img_url, timeout=10).content
                            image_name = os.path.basename(full_img_url.split("?")[0])
                            image_path = os.path.join(image_dir, image_name)

                            with open(image_path, 'wb') as f:
                                f.write(img_content)

                            dropbox_image_path = f"{SHARED_FOLDER_PATH}/{dropbox_subfolder}/Images/{image_name}".replace("//", "/")
                            dropbox_url = upload_to_dropbox(image_path, dropbox_image_path)

                            alt_text = img.get("alt", "")
                            writer.writerow({
                                "page_url": url,
                                "image_url": full_img_url,
                                "image_name": image_name,
                                "alt_text_present": "Yes" if alt_text else "No",
                                "alt_text": alt_text,
                                "dropbox_url": dropbox_url
                            })
                        except Exception as e:
                            print(f"Image failed: {full_img_url} - {e}")

                for a in soup.find_all("a", href=True):
                    link = urljoin(url, a["href"])
                    if is_internal_link(link, base_url):
                        queue.append(link)

            except Exception as e:
                print(f"Failed to process {url}: {e}")

    return len(image_urls)

@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    if request.method == "POST":
        try:
            parent_url = request.form["url"]
            folder_subpath = request.form.get("course_folder", "").strip("/")

            if not folder_subpath:
                message = "Please enter a subfolder path for Dropbox."
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    csv_path = os.path.join(tmpdir, "image_metadata.csv")
                    image_count = crawl_and_extract(parent_url, tmpdir, csv_path, folder_subpath)

                    dropbox_csv_path = f"{SHARED_FOLDER_PATH}/{folder_subpath}/image_metadata.csv".replace("//", "/")
                    upload_to_dropbox(csv_path, dropbox_csv_path)

                    message = f"✅ Extracted {image_count} images.<br>Check Dropbox folder: <strong>{folder_subpath}</strong>."
        except Exception as e:
            traceback.print_exc()
            message = f"❌ Error: <code>{e}</code>"

    return render_template("index.html", message=message)
