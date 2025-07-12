# Image Export to Dropbox Tool

This Flask-based web tool allows users to:
- Crawl all child pages from a parent URL
- Extract images while skipping known logos/author icons
- Upload those images + metadata CSV to a Dropbox folder

## 🚀 How to Deploy on Render

1. Push this repo to GitHub
2. Go to [https://render.com](https://render.com) → New Web Service
3. Link your repo and set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python app.py`
4. In "Environment", add:

```
DROPBOX_ACCESS_TOKEN = your_dropbox_token_here
```

Done! Visit your URL and paste in any parent revision note URL to begin extraction.

## ✅ Example Dropbox Path
```
/CIE IGCSE Physics
```

This will create subfolders like:
- `/CIE IGCSE Physics/images/*.png`
- `/CIE IGCSE Physics/image_metadata.csv`