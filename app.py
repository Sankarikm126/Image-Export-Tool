from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import dropbox
import pytesseract
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SHARED_FOLDER_PATH = os.environ.get("SHARED_FOLDER_PATH")

dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def has_all_caps_text(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return any(line.isupper() for line in lines if any(c.isalpha() for c in line))
    except Exception:
        return False

def upload_to_dropbox(local_path, dropbox_file_path):
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_file_path, mode=dropbox.files.WriteMode.overwrite)
    shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_file_path)
    return shared_link_metadata.url.replace("?dl=0", "?raw=1")

def crawl_and_extract(base_url, output_dir, csv_path, course_folder):
    visited = set()
    image_urls = []
    queue = [base_url]

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "page_url", "image_url", "image_name", "alt_text_present", "alt_text",
            "dropbox_url", "all_caps_text"
        ]
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
                        local_path = os.path.join(output_dir, image_name)

                        try:
                            img_data = requests.get(full_img_url).content
                            with open(local_path, 'wb') as f:
                                f.write(img_data)

                            # Upload image to Dropbox inside images/
                            dropbox_path = f"{SHARED_FOLDER_PATH}/{course_folder}/images/{image_name}"
                            dropbox_url = upload_to_dropbox(local_path, dropbox_path)

                            is_all_caps = has_all_caps_text(local_path)

                            writer.writerow({
                                "page_url": url,
                                "image_url": full_img_url,
                                "image_name": image_name,
                                "alt_text_present": "Yes" if alt else "No",
                                "alt_text": alt,
                                "dropbox_url": dropbox_url,
                                "all_caps_text": "Yes" if is_all_caps else "No"
                            })

                            image_urls.append(dropbox_url)
                        except Exception as e:
                            print(f"Failed to upload {full_img_url}: {e}")

                for a in soup.find_all("a", href=True):
                    link = urljoin(url, a['href'])
                    if is_internal_link(link, base_url) and link.startswith(base_url):
                        queue.append(link)

            except Exception as e:
                print(f"Failed to process {url}: {e}")

    return image_urls

@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
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

                image_links = crawl_and_extract(parent_url, image_dir, csv_path, course_folder)

                # Upload metadata CSV directly under the course folder (not inside /images)
                csv_dropbox_path = f"{SHARED_FOLDER_PATH}/{course_folder}/image_metadata.csv"
                csv_url = upload_to_dropbox(csv_path, csv_dropbox_path)

                folder_url = f"https://www.dropbox.com/home{SHARED_FOLDER_PATH}/{course_folder}"
                message = (
                    f"Extracted {len(image_links)} images.<br>"
                    f"<a href='{csv_url}' target='_blank'>Download metadata CSV</a><br>"
                    f"<a href='{folder_url}' target='_blank'>View Shared Folder</a>"
                )

    return render_template("index.html", message=message)

if __name__ == "__main__":
    app.run(debug=True)
