from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
import dropbox
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DROPBOX_TOKEN = os.environ.get("sl.u.AF01mIbK01QN_IUxejKWFUYhVVDOO0Apmnxkl48VoFeqIPSUgJD75ok4BG9jCpIcHIvmyJhPVIE72DwNH2l4MK5ebxQ0MB2fDlwbdFE4EHKO8NklAynzeVExuMrhZzejX74BIEHgKalzWeC7XwiQB_s12FTeqYAAaMSLRNcSfonGYRfc68AuROlMVdrRbphk1kWFcfnx0dgcjXHRqUVtRUlsw7n8jiqsuAqrTdRwMVbGjSWezowAvrM2FgsZZ1TX1Xm6c5CpEnKaBusP7M59ZwZTNAkNo6AphuuFv6_dEh1zzFhbLWlNpqaMA-ihaiaehLT_YmvsN5yM7lhcn-W7FfvFweRbn_NBFoZhNdbPUcnuwTUq4b2RolfyJVydrKyKjSpcVekjWBVpIVq5nhBFyk05EJzhYq_IvV4q6IbJ9ar8kjcaulDcfIuLYeeyzzeE0-WP9J5SgMkwDQR01rytrqedU9GqhWtFZ3O8vLCuB7tmhEgBXTVJ-FBxbD2Bnk-UyaDYK2PPZjC9RBAAkDY1h12uyXJerD-MHJ1mQDFZPbTPiMyrp0QTcunyWGwRfgiY48UogGAmFmF_50wDnFvcLBh6upsATYo4Bv91N5pXkrBuioxu1IJI6SXVY8GcjkrWiM4RRaWG5oQO3Vkuc215De50aLz0xwcVaP76CRVjpmSBaQMiIEFq7ydruib6MPQ04Bj0eFlHYUcPHemI43dFTDe3qidXaIsTh9CPqDDTdjEu92bmUe9C5uh7ffwy7_G02Qu4cRPbSQB4i2_No8U_xPHo8Ban4i-4tbGFaZcoZaQC8LF9GdRmx1J506xjKCRflnBqdVsM8OYNX19hNqK9Pm1l8O2X3Xwwcqfw8UyF6jFAIxWwKCaqREj5-0s3jJ5nB7Tv8wzO6AKgTZfkMiCsI4FMTuPMgO7jSIm04C-F1aP22OjekWgaHZM4Dqsb-kCflleXSbInD5J45X5f11ar9eu-2x695aLk5sbc50VRipsBT3cq8188MSQpxdeIgUv1o2pBFJ4KPjb2DW8c9-RtS_pYeRAveVgQ5tnF0_AVwQJZ6iyZqifk8N0vfCJu-YAt_bcNbbF-lQlxLg5GTZL6fusBeXma7UFFvd43dW-XYT7M1235GPZ34mOa0PdlzHIxvGCV9KMqegCm71J1xAXLxfmsYCRXWt1KVjq6G9JJVyMl0WVpUHMNVY8ZkkxO8W1JlSj4fEaq-4xC_f8UiP0P4cxuGLyD8dOIDVje-r4dSehGxvnRGoWggVLOJV0_nEizldfZybaqaBqPZabnMfE2ZPIiJJbwixfj5x_Qfzi-4Jffzbn0DijXCxgL0CzIheca2RE")

SKIP_KEYWORDS = [
    "logo", "icon", "avatar", "author", "profile", "signature", "favicon",
    "bio", "team", "headshot", "user", "staff", "linkedin", "twitter", "instagram", "fb", "social"
]

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def crawl_and_extract(base_url, output_dir, csv_path):
    visited = set()
    image_urls = set()
    queue = [base_url]

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
                            img_data = requests.get(full_img_url).content
                            with open(image_path, 'wb') as f:
                                f.write(img_data)
                            downloaded = "Yes"
                            image_urls.add((full_img_url, image_name))
                        except Exception as e:
                            print(f"Error downloading {full_img_url}: {e}")

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
                print(f"Failed to process {url}: {e}")

    return image_urls

def upload_to_dropbox(local_path, dropbox_path):
    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        print(f"Uploaded to Dropbox: {dropbox_path}")

@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    if request.method == "POST":
        parent_url = request.form["url"]
        dropbox_folder = request.form.get("dropbox_folder")

        if not dropbox_folder:
            message = "Dropbox folder path is required to upload."
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                image_dir = os.path.join(tmpdir, "images")
                os.makedirs(image_dir, exist_ok=True)
                csv_path = os.path.join(tmpdir, "image_metadata.csv")

                image_data = crawl_and_extract(parent_url, image_dir, csv_path)

                for _, name in image_data:
                    img_path = os.path.join(image_dir, name)
                    dropbox_img_path = f"{dropbox_folder}/images/{name}"
                    if os.path.exists(img_path):
                        upload_to_dropbox(img_path, dropbox_img_path)

                upload_to_dropbox(csv_path, f"{dropbox_folder}/image_metadata.csv")
                message = "Upload to Dropbox completed!"

    return render_template("index.html", message=message)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)