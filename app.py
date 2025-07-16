from flask import Flask, request, render_template
import os, requests, csv, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import boto3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
S3_FOLDER_PREFIX = os.environ.get("S3_FOLDER_PREFIX", "edtech")

s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def is_internal_link(link, base_url):
    parsed_link = urlparse(link)
    parsed_base = urlparse(base_url)
    return parsed_link.netloc == '' or parsed_link.netloc == parsed_base.netloc

def upload_to_s3(file_path, s3_key):
    try:
        s3.upload_file(file_path, S3_BUCKET_NAME, s3_key)
        return f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
    except Exception as e:
        print(f"Failed to upload {file_path} to S3: {e}")
        return ""

def crawl_and_extract(base_url, output_dir, csv_path, course_folder):
    visited = set()
    image_urls = set()
    queue = [base_url]

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["page_url", "image_url", "image_name", "alt_text_present", "alt_text", "s3_url"]
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
                        image_path = os.path.join(output_dir, image_name)

                        try:
                            img_data = requests.get(full_img_url).content
                            with open(image_path, 'wb') as f:
                                f.write(img_data)

                            s3_key = f"{S3_FOLDER_PREFIX}/{course_folder}/{image_name}".replace("//", "/")
                            s3_url = upload_to_s3(image_path, s3_key)

                            writer.writerow({
                                "page_url": url,
                                "image_url": full_img_url,
                                "image_name": image_name,
                                "alt_text_present": "Yes" if alt else "No",
                                "alt_text": alt,
                                "s3_url": s3_url
                            })

                            image_urls.add(s3_url)

                        except Exception as e:
                            print(f"Error processing {full_img_url}: {e}")

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

                image_data = crawl_and_extract(parent_url, image_dir, csv_path, course_folder)

                # Upload CSV file to S3
                csv_key = f"{S3_FOLDER_PREFIX}/{course_folder}/image_metadata.csv"
                csv_url = upload_to_s3(csv_path, csv_key)

                count = len(image_data)
                aws_console_link = f"https://s3.console.aws.amazon.com/s3/buckets/{S3_BUCKET_NAME}?prefix={S3_FOLDER_PREFIX}/{course_folder}/"
                message = f"Extracted {count} images. <a href='{csv_url}' target='_blank'>Download metadata CSV</a> or <a href='{aws_console_link}' target='_blank'>View S3 folder in AWS Console</a>"

    return render_template("index.html", message=message)
