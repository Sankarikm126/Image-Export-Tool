from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
import dropbox
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
DROPBOX_BASE_PATH = os.environ.get("DROPBOX_MASTER_FOLDER", "/Extracted-Images")
MAX_IMAGES = 500  # Adjust as needed

SKIP_KEYWORDS = [
    "logo", "icon", "avatar", "author", "profile", "signature", "favicon",
    "bio", "team", "headshot", "user", "staff", "linkedin", "twitter", "instagram", "fb", "social"
]

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def crawl_and_extract(base_url, output_dir, csv_path, max_images=200):
    visited = set()
    downloaded_urls = set()
    image_data = []
    queue = [base_url]
    image_count = 0

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
                    if image_count >= max_images:
                        print("🟠 Reached max image limit.")
                        return image_data

                    src = img.get("src")
                    alt = img.get("alt", "")

                    if not src or src.startswith("data:image"):
                        print(f"⚠️ Skipping embedded image: {src[:30]}..." if src else "⚠️ Skipping empty src.")
                        continue

                    full_img_url = urljoin(url, src)
                    image_name = os.path.basename(full_img_url.split("?")[0])

                    if any(kw in full_img_url.lower() for kw in SKIP_KEYWORDS) or full_img_url in downloaded_urls:
                        print(f"⏭️ Skipping duplicate or filtered image: {image_name}")
                        continue

                    image_path = os.path.join(output_dir, image_name)
                    downloaded = "No"

                    try:
                        img_resp = requests.get(full_img_url, timeout=10)
                        img_resp.raise_for_status()
                        with open(image_path, 'wb') as f:
                            f.write(img_resp.content)
                        downloaded = "Yes"
                        image_count += 1
                        downloaded_urls.add(full_img_url)
                        image_data.append((full_img_url, image_name, alt))
                        print(f"✅ Downloaded image ({image_count}): {image_name}")

                    except Exception as e:
                        print(f"❌ Error downloading {full_img_url}: {e}")

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
                print(f"🚫 Failed to process {url}: {e}")

    return image_data

def upload_to_dropbox(local_path, dropbox_path):
    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        print(f"✅ Uploaded to Dropbox: {dropbox_path}")

@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    if request.method == 'POST':
        parent_url = request.form.get('url')
        subfolder = request.form.get('subfolder', 'sample1')

        if not parent_url:
            message = "❌ Please enter a valid parent URL."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                image_dir = os.path.join(tmpdir, "images")
                os.makedirs(image_dir, exist_ok=True)
                csv_path = os.path.join(tmpdir, "image_metadata.csv")

                image_data = crawl_and_extract(parent_url, image_dir, csv_path)

                for url, name, alt in image_data:
                    img_path = os.path.join(image_dir, name)
                    dropbox_img_path = f"{DROPBOX_BASE_PATH}/{subfolder}/images/{name}"
                    if os.path.exists(img_path):
                        upload_to_dropbox(img_path, dropbox_img_path)

                upload_to_dropbox(csv_path, f"{DROPBOX_BASE_PATH}/{subfolder}/image_metadata.csv")
                message = "✅ Extraction and upload completed. Please check your Dropbox folder."

    return render_template("index.html", message=message)

if __name__ == '__main__':
    app.run(debug=True)
