from flask import Flask, request, render_template
import os, requests, csv, tempfile, threading
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
import dropbox
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
DROPBOX_BASE_PATH = os.environ.get("DROPBOX_MASTER_FOLDER", "/Extracted-Images")
MAX_IMAGES = 500  # You can increase this if needed


def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc


def crawl_and_extract(base_url, output_dir, csv_path, max_images=MAX_IMAGES):
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
                res = requests.get(url, timeout=30)
                res.raise_for_status()
                soup = BeautifulSoup(res.text, "html.parser")
            except requests.exceptions.RequestException as e:
                print(f"🚫 Failed to fetch {url}: {e}")
                continue

            for img in soup.find_all("img"):
                if image_count >= max_images:
                    print("🟠 Reached max image limit.")
                    return image_data

                src = img.get("src")
                alt = img.get("alt", "")

                if not src or src.startswith("data:image"):
                    continue

                full_img_url = urljoin(url, src)
                image_name = os.path.basename(full_img_url.split("?")[0])

                if full_img_url in downloaded_urls:
                    continue

                image_path = os.path.join(output_dir, image_name)
                downloaded = "No"

                try:
                    img_resp = requests.get(full_img_url, timeout=30)
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

    return image_data


def upload_to_dropbox(local_path, dropbox_path):
    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        print(f"✅ Uploaded to Dropbox: {dropbox_path}")


def background_upload(image_dir, csv_path, raw_subfolder):
    try:
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                image_name = row["image_name"]
                img_path = os.path.join(image_dir, image_name)
                dropbox_img_path = f"{DROPBOX_BASE_PATH}/{raw_subfolder}/images/{image_name}"
                if os.path.exists(img_path):
                    upload_to_dropbox(img_path, dropbox_img_path)

        dropbox_csv_path = f"{DROPBOX_BASE_PATH}/{raw_subfolder}/image_metadata.csv"
        upload_to_dropbox(csv_path, dropbox_csv_path)
        print("🎉 Background upload completed.")

    except Exception as e:
        print(f"❌ Error in background upload: {e}")


@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    if request.method == 'POST':
        parent_url = request.form.get('url')
        raw_subfolder = request.form.get('subfolder', 'sample1').strip()
        print(f"🟨 Using subfolder name: {raw_subfolder}")

        if not parent_url:
            message = "❌ Please enter a valid parent URL."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                image_dir = os.path.join(tmpdir, "images")
                os.makedirs(image_dir, exist_ok=True)
                csv_path = os.path.join(tmpdir, "image_metadata.csv")

                crawl_and_extract(parent_url, image_dir, csv_path)

                thread = threading.Thread(target=background_upload, args=(image_dir, csv_path, raw_subfolder))
                thread.start()
                message = "✅ Extraction started. Uploading in background."

    return render_template("index.html", message=message)


if __name__ == '__main__':
    app.run(debug=True)
