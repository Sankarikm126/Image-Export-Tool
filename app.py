import os
import csv
import tempfile
import requests
from urllib.parse import urljoin, urlparse
from flask import Flask, request, render_template
from bs4 import BeautifulSoup
import dropbox
import threading

DROPBOX_TOKEN = os.environ.get("DROPBOX_TOKEN")
dbx = dropbox.Dropbox(DROPBOX_TOKEN)

app = Flask(__name__)

def is_internal_link(link, base_url):
    return urlparse(link).netloc == urlparse(base_url).netloc

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

def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
    print(f"✅ Uploaded to Dropbox: {dropbox_path}")

def background_upload(image_data, raw_subfolder, temp_dir):
    try:
        csv_path = os.path.join(temp_dir, "image_metadata.csv")
        with open(csv_path, "w", newline="", encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Filename", "Alt Text"])
            for item in image_data:
                writer.writerow([item["filename"], item["alt"]])

        for item in image_data:
            dropbox_path = os.path.join("/Extracted-Images", raw_subfolder, "images", item["filename"])
            upload_to_dropbox(item["local_path"], dropbox_path)

        csv_dropbox_path = os.path.join("/Extracted-Images", raw_subfolder, "image_metadata.csv")
        upload_to_dropbox(csv_path, csv_dropbox_path)

    except Exception as e:
        print(f"❌ Error in background upload: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    if request.method == 'POST':
        parent_url = request.form.get('url')
        raw_subfolder = request.form.get('dropbox_folder', 'sample1')
        print(f"📁 Using subfolder name: {raw_subfolder}")

        try:
            image_data, temp_dir = scrape_images_from_all_links(parent_url)
            threading.Thread(target=background_upload, args=(image_data, raw_subfolder, temp_dir)).start()
            message = f"🔄 Extracting {len(image_data)} images and uploading in the background."
        except Exception as e:
            message = f"❌ Failed to extract: {e}"

    return render_template("index.html", message=message)

if __name__ == '__main__':
    app.run(debug=True)
