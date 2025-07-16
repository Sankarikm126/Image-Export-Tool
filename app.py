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

                            dbx_path = f"{SHARED_FOLDER_PATH}/{dropbox_subfolder}/{image_name}".replace("//", "/")
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
        dropbox_folder = request.form.get("course_folder", "").strip("/")

        if not dropbox_folder:
            message = "Dropbox Folder Path is required."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                image_dir = os.path.join(tmpdir, "images")
                os.makedirs(image_dir, exist_ok=True)
                csv_path = os.path.join(tmpdir, "image_metadata.csv")

                image_data = crawl_and_extract(parent_url, image_dir, csv_path, dropbox_folder)

                # Upload metadata CSV
                csv_dropbox_path = f"{SHARED_FOLDER_PATH}/{dropbox_folder}/image_metadata.csv".replace("//", "/")
                csv_url = upload_to_dropbox(csv_path, csv_dropbox_path)

                # Generate gallery.html
                gallery_path = os.path.join(tmpdir, "gallery.html")
                with open(gallery_path, "w", encoding="utf-8") as gfile:
                    gfile.write("<html><head><title>Image Gallery</title></head><body>\n<h2>Extracted Image Gallery</h2>\n")
                    for dbx_url, _ in image_data:
                        gfile.write(f"<img src='{dbx_url}' alt='' style='width:150px; margin:5px;'>\n")
                    gfile.write("</body></html>")

                gallery_dropbox_path = f"{SHARED_FOLDER_PATH}/{dropbox_folder}/gallery.html".replace("//", "/")
                gallery_url = upload_to_dropbox(gallery_path, gallery_dropbox_path)

                folder_link = f"https://www.dropbox.com/home{SHARED_FOLDER_PATH}/{dropbox_folder}".replace("//", "/")
                message = (
                    f"Extracted {len(image_data)} images.<br>"
                    f"<a href='{csv_url}' target='_blank'>Download metadata CSV</a><br>"
                    f"<a href='{gallery_url}' target='_blank'>View Gallery</a><br>"
                    f"<a href='{folder_link}' target='_blank'>Open in Dropbox</a>"
                )
    return render_template("index.html", message=message)
