from flask import Flask, request, render_template
import os, requests, csv, tempfile, traceback
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import dropbox
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
DROPBOX_MASTER_PATH = os.environ.get("DROPBOX_MASTER_PATH", "/Extracted-Images")

SKIP_KEYWORDS = [
    "logo", "icon", "avatar", "author", "profile", "signature", "favicon",
    "bio", "team", "headshot", "user", "staff", "linkedin", "twitter", "instagram", "fb", "social"
]

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

import time

def crawl_and_extract(base_url, output_dir, csv_path):
    MAX_PAGES = 200
    MAX_IMAGES = 200

    visited = set()
    queue = [base_url]
    image_data = []

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["page_url", "image_url", "image_name", "alt_text_present", "alt_text", "downloaded"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        while queue and len(visited) < MAX_PAGES and len(image_data) < MAX_IMAGES:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                print(f"🌐 Visiting page ({len(visited)}): {url}")
                res = requests.get(url, timeout=10)
                soup = BeautifulSoup(res.text, "html.parser")
                time.sleep(0.2)

                for img in soup.find_all("img"):
                    if len(image_data) >= MAX_IMAGES:
                        print("🛑 Reached image limit.")
                        break

                    src = img.get("src")
                    alt = img.get("alt", "")
                    if src:
                        full_img_url = urljoin(url, src)
                        image_name = os.path.basename(full_img_url.split("?")[0])

                        if any(kw in full_img_url.lower() for kw in SKIP_KEYWORDS):
                            continue

                        image_path = os.path.join(output_dir, image_name)
                        downloaded = "No"
                        try:
                            img_resp = requests.get(full_img_url, timeout=10)
                            img_resp.raise_for_status()
                            with open(image_path, 'wb') as f:
                                f.write(img_resp.content)
                            downloaded = "Yes"
                            image_data.append((full_img_url, image_name))
                            print(f"🖼 Downloaded image ({len(image_data)}): {image_name}")
                        except Exception as e:
                            print(f"❌ Error downloading {full_img_url}: {e}")
                        time.sleep(0.2)

                        writer.writerow({
                            "page_url": url,
                            "image_url": full_img_url,
                            "image_name": image_name,
                            "alt_text_present": "Yes" if alt else "No",
                            "alt_text": alt,
                            "downloaded": downloaded
                        })

                for a in soup.find_all("a", href=True):
                    link = urljoin(url, a["href"])
                    if is_internal_link(link, base_url) and link not in visited and link.startswith(base_url):
                        queue.append(link)

                if len(visited) % 10 == 0:
                    print(f"🧭 Pages crawled: {len(visited)}")
                if len(image_data) % 10 == 0:
                    print(f"📷 Images collected: {len(image_data)}")

            except Exception as e:
                print(f"❌ Failed to process {url}: {e}")
                time.sleep(1)

    print(f"✅ Finished crawling {len(visited)} pages and extracting {len(image_data)} images.")
    return image_data

def upload_to_dropbox(local_path, dropbox_path):
    try:
        if not os.path.exists(local_path):
            print(f"❌ Local file missing: {local_path}")
            return
        print(f"⬆️ Uploading to Dropbox: {dropbox_path} from {local_path}")
        dbx = dropbox.Dropbox(DROPBOX_TOKEN)
        with open(local_path, "rb") as f:
            dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        print(f"✅ Uploaded: {dropbox_path}")
    except Exception as e:
        print(f"❌ Dropbox upload failed: {dropbox_path} - {e}")

@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    if request.method == "POST":
        try:
            parent_url = request.form["url"]
            dropbox_folder = request.form.get("dropbox_folder", "").strip().strip("/")

            if not dropbox_folder:
                message = "❌ Dropbox folder path is required."
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    image_dir = os.path.join(tmpdir, "images")
                    os.makedirs(image_dir, exist_ok=True)
                    csv_path = os.path.join(tmpdir, "image_metadata.csv")

                    print(f"🔍 Starting extraction from: {parent_url}")
                    images = crawl_and_extract(parent_url, image_dir, csv_path)
                    print(f"📦 Total images extracted: {len(images)}")

                    print(f"➡️ Dropbox upload path: {DROPBOX_MASTER_PATH}/{dropbox_folder}")

                    # ✅ FIXED: correct unpacking of (url, name)
                    for full_img_url, image_name in images:
                        local_img_path = os.path.join(image_dir, image_name)
                        dropbox_img_path = f"{DROPBOX_MASTER_PATH}/{dropbox_folder}/images/{image_name}".replace("//", "/")
                        if os.path.exists(local_img_path):
                            print(f"📤 Uploading image: {image_name}")
                            upload_to_dropbox(local_img_path, dropbox_img_path)
                        else:
                            print(f"❌ Skipping missing image: {local_img_path}")

                    dropbox_csv_path = f"{DROPBOX_MASTER_PATH}/{dropbox_folder}/image_metadata.csv".replace("//", "/")
                    upload_to_dropbox(csv_path, dropbox_csv_path)

                    message = "Extraction completed. Please check the Dropbox folder."

        except Exception as e:
            traceback.print_exc()
            message = f"❌ An error occurred:<br><code>{e}</code>"

    return render_template("index.html", message=message)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
