from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import dropbox
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SHARED_FOLDER_PATH = os.environ.get("SHARED_FOLDER_PATH", "/Shared/SME")

dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
    return f"https://www.dropbox.com/home{dropbox_path}"

def crawl_and_extract(base_url, output_dir, csv_path, dropbox_subfolder):
    visited = set()
    image_urls = set()
    queue = [base_url]

    os.makedirs(output_dir, exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["page_url", "image_url", "image_name", "alt_text_present", "alt_text", "dropbox_url"]
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

                    if src:
                        full_img_url = urljoin(url, src)
                        image_name = os.path.basename(full_img_url.split("?")[0])
                        image_path = os.path.join(output_dir, image_name)
                        alt = img.get("alt", "")
                        try:
                            img_data = requests.get(full_img_url).content
                            with open(image_path, "wb") as f:
                                f.write(img_data)

                            dbx_path = f"{SHARED_FOLDER_PATH}/{dropbox_subfolder}/Images/{image_name}"
                            dbx_path = dbx_path.replace("//", "/")
                            dropbox_url = upload_to_dropbox(image_path, dbx_path)


                            writer.writerow({
                                "page_url": url,
                                "image_url": full_img_url,
                                "image_name": image_name,
                                "alt_text_present": "Yes" if alt else "No",
                                "alt_text": alt,
                                "dropbox_url": dropbox_url
                            })
                            image_urls.add((dropbox_url, image_name))
                        except Exception as e:
                            print(f"Download failed: {full_img_url} | {e}")

                for a in soup.find_all("a", href=True):
                    link = urljoin(url, a["href"])
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
        folder_subpath = request.form.get("course_folder", "").strip("/")

        if not folder_subpath:
            message = "Please enter a subfolder path for Dropbox."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                csv_path = os.path.join(tmpdir, "image_metadata.csv")
                crawl_and_extract(parent_url, tmpdir, csv_path, folder_subpath)
                dropbox_csv_path = f"{SHARED_FOLDER_PATH}/{folder_subpath}/image_metadata.csv"
                csv_url = upload_to_dropbox(csv_path, dropbox_csv_path)
                message = (
                    count = len(extracted_images)
                    f"Extracted {count} images. "
                    f"<a href='{csv_url}' target='_blank'>Download metadata CSV</a> or "
                    f"<a href='{dropbox_folder_url}' target='_blank'>View Dropbox Folder</a>"
                )
                
    return render_template("index.html", message=message)
