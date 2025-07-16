from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import dropbox
from dotenv import load_dotenv
import pytesseract
from PIL import Image
from io import BytesIO

load_dotenv()

app = Flask(__name__)

DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
DROPBOX_FOLDER_BASE = os.environ.get("SHARED_FOLDER_PATH", "/Share/SME")
dbx = dropbox.Dropbox(DROPBOX_TOKEN)

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
    shared_link = dbx.sharing_create_shared_link_with_settings(dropbox_path)
    return shared_link.url.replace("?dl=0", "?raw=1")

def has_all_caps_text(image_path):
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        words = [w for w in text.split() if w.isalpha()]
        upper_count = sum(1 for w in words if w.isupper())
        return "Yes" if upper_count >= 1 else "No"
    except Exception as e:
        print(f"OCR failed for {image_path}: {e}")
        return "No"

def crawl_and_extract(base_url, output_dir, csv_path, folder_subpath):
    visited = set()
    queue = [base_url]

    image_dir = os.path.join(output_dir, "images")
    os.makedirs(image_dir, exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            "page_url", "image_url", "image_name", "alt_text_present", "alt_text", "dropbox_url", "contains_all_caps"
        ])
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
                        src = query.get("url", [src])[0]

                    alt = img.get("alt", "")
                    if src:
                        full_img_url = urljoin(url, src)
                        image_name = os.path.basename(full_img_url.split("?")[0])
                        image_path = os.path.join(image_dir, image_name)

                        try:
                            img_data = requests.get(full_img_url).content
                            with open(image_path, 'wb') as f:
                                f.write(img_data)

                            dropbox_path = f"{DROPBOX_FOLDER_BASE}/{folder_subpath}/{image_name}".replace("//", "/")
                            dropbox_url = upload_to_dropbox(image_path, dropbox_path)

                            has_caps = has_all_caps_text(image_path)

                            writer.writerow({
                                "page_url": url,
                                "image_url": full_img_url,
                                "image_name": image_name,
                                "alt_text_present": "Yes" if alt else "No",
                                "alt_text": alt,
                                "dropbox_url": dropbox_url,
                                "contains_all_caps": has_caps
                            })
                        except Exception as e:
                            print(f"Image download or upload failed: {full_img_url} - {e}")

                for a in soup.find_all("a", href=True):
                    link = urljoin(url, a['href'])
                    if is_internal_link(link, base_url):
                        queue.append(link)

            except Exception as e:
                print(f"Failed to process {url}: {e}")

@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    if request.method == "POST":
        parent_url = request.form["url"]
        folder_subpath = request.form.get("course_folder", "").strip("/")

        if not folder_subpath:
            message = "Please enter a subfolder path for Dropbox."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                csv_path = os.path.join(tmpdir, "image_metadata.csv")
                crawl_and_extract(parent_url, tmpdir, csv_path, folder_subpath)

                # Upload CSV to base Dropbox folder
                dropbox_csv_path = f"{DROPBOX_FOLDER_BASE}/{folder_subpath}_image_metadata.csv"
                csv_url = upload_to_dropbox(csv_path, dropbox_csv_path)

                message = (
                    f"Extraction complete. "
                    f"<a href='{csv_url}' target='_blank'>Download metadata CSV</a> or "
                    f"<a href='https://www.dropbox.com/home{DROPBOX_FOLDER_BASE}/{folder_subpath}' target='_blank'>Open Dropbox folder</a>"
                )
    return render_template("index.html", message=message)
