import os
import csv
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from flask import Flask, render_template, request
import dropbox

DROPBOX_TOKEN = os.environ.get("DROPBOX_TOKEN")
app = Flask(__name__)

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    return not parsed_link.netloc or parsed_link.netloc == urlparse(base_url).netloc

def extract_images_from_url(url, base_url, download_folder, image_data, visited):
    if url in visited:
        return
    visited.add(url)

    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")

        # Extract and download images
        for img in soup.find_all("img"):
            src = img.get("src")
            alt = img.get("alt") or ""
            if not src:
                continue

            full_url = urljoin(url, src)
            filename = os.path.basename(urlparse(full_url).path)
            local_path = os.path.join(download_folder, filename)

            try:
                img_data = requests.get(full_url, timeout=10).content
                with open(local_path, "wb") as f:
                    f.write(img_data)
                print(f"✅ Downloaded image: {filename}")
                image_data.append({
                    "source_page": url,
                    "image_url": full_url,
                    "filename": filename,
                    "alt_text_present": "Yes" if alt else "No",
                    "alt_text": alt,
                    "downloaded": True
                })
            except Exception as e:
                print(f"❌ Failed to download {full_url}: {e}")

        # Traverse internal links
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a['href'])
            if is_internal_link(link, base_url):
                extract_images_from_url(link, base_url, download_folder, image_data, visited)

    except Exception as e:
        print(f"❌ Failed to fetch {url}: {e}")

def upload_to_dropbox(local_path, dropbox_path):
    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        print(f"✅ Uploaded to Dropbox: {dropbox_path}")

def background_upload(image_dir, csv_path, dropbox_subfolder):
    dbx_path_base = f"/Extracted-Images/{dropbox_subfolder}"
    try:
        for filename in os.listdir(image_dir):
            local_file = os.path.join(image_dir, filename)
            dropbox_path = f"{dbx_path_base}/images/{filename}"
            upload_to_dropbox(local_file, dropbox_path)
        if csv_path and os.path.exists(csv_path):
            csv_dropbox_path = f"{dbx_path_base}/image_metadata.csv"
            upload_to_dropbox(csv_path, csv_dropbox_path)
        print("✅ All files uploaded successfully.")
    except Exception as e:
        print(f"❌ Error during Dropbox upload: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""

    if request.method == 'POST':
        parent_url = request.form.get('url')
        raw_subfolder = request.form.get('dropbox_folder', 'sample1')
        subfolder = raw_subfolder.strip('/').replace('/', '_')
        image_dir = f"downloads/{subfolder}/images"
        os.makedirs(image_dir, exist_ok=True)
        csv_path = f"downloads/{subfolder}/image_metadata.csv"

        image_data = []
        visited = set()

        print(f"📥 Starting extraction from: {parent_url}")
        extract_images_from_url(parent_url, parent_url, image_dir, image_data, visited)

        if image_data:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ["source_page", "image_url", "filename", "alt_text_present", "alt_text", "downloaded"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for data in image_data:
                    writer.writerow(data)
            print(f"📝 Metadata CSV written: {csv_path}")
        else:
            print("⚠️ No image data extracted.")

        background_upload(image_dir, csv_path, raw_subfolder)
        message = "✅ Extraction and upload complete."

    return render_template("index.html", message=message)

if __name__ == '__main__':
    app.run(debug=True)
