from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.auth.transport.requests
import base64
import re
import traceback
import os
import html

# Always resolve token.json relative to this file's directory
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BACKEND_DIR, "token.json")

print("APP STARTING...")

app = Flask(__name__)
CORS(app)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def load_credentials():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    # Auto-refresh if expired
    if not creds.valid and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print("Token auto-refreshed.")
    return creds


def clean_text_content(text):
    """Remove URLs, image references, HTML artifacts, and other non-text elements."""
    if not text:
        return ""
    
    # Unescape HTML entities first (e.g. &zwnj; -> \u200c, &nbsp; -> \u00a0, &amp; -> &)
    text = html.unescape(text)
    
    # Remove zero-width non-joiner, zero-width space, and other hidden characters
    text = text.replace('\u200c', '')
    text = text.replace('\u200b', '')
    text = text.replace('\u200d', '')
    text = text.replace('\ufeff', '')
    
    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    
    # Remove HTML tags and their content (especially img, script, style)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)  # Remove all remaining HTML tags
    
    # Remove URLs (http, https, ftp, www)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r'ftp://\S+', '', text)
    
    # Remove markdown image syntax
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)

    # Remove image filenames (e.g. image001.png, img_123.jpg) and common inline placeholders
    text = re.sub(r'\b[\w\-_]*(?:image|img)[\w\-_]*\.\w+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\s*(?:image|img)[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(\s*(?:image|img)[^\)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'alt=.*?(?:\s|$)', '', text)
    
    # Remove email addresses
    text = re.sub(r'\S+@\S+', '', text)
    
    # Remove base64 encoded data (common in HTML emails)
    text = re.sub(r'data:image/\w+;base64,\S+', '', text)
    
    # Remove special characters and control sequences
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]', '', text)
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove leading/trailing hyphens and dashes (common in email separators)
    text = re.sub(r'^[\-_\=]+\s*', '', text)
    text = re.sub(r'\s*[\-_\=]+$', '', text)
    
    return text


def extractive_summarize(text, max_chars=250):
    """Simple extractive summarizer."""
    if not text or not text.strip():
        return "No text content available."
    # Clean URLs, images, and artifacts
    text = clean_text_content(text)
    if not text:
        return "No text content available."
    if len(text) <= max_chars:
        return text
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    if not sentences:
        return text[:max_chars] + "..."
    summary, total_len = [], 0
    for sent in sentences[:5]:
        if total_len + len(sent) <= max_chars:
            summary.append(sent)
            total_len += len(sent)
        else:
            remaining = max_chars - total_len
            if remaining > 40:
                summary.append(sent[:remaining] + "...")
            break
    return ' '.join(summary) if summary else text[:max_chars] + "..."


SUMMARIZER_MODEL = "sshleifer/distilbart-cnn-6-6"
summarizer_pipeline = None
summarizer_loaded = False

def get_summarizer():
    global summarizer_pipeline, summarizer_loaded
    if not summarizer_loaded:
        summarizer_loaded = True
        try:
            print("Loading abstractive summarization pipeline...")
            from transformers import pipeline
            summarizer_pipeline = pipeline("summarization", model=SUMMARIZER_MODEL, device=-1)
            print("Abstractive summarizer pipeline loaded successfully!")
        except Exception as e:
            print("Failed to load transformers summarizer, using extractive backup:", e)
            summarizer_pipeline = None
    return summarizer_pipeline

def abstractive_summarize(text, max_chars=250):
    if not text or not text.strip():
        return "No content to summarize."
    cleaned = clean_text_content(text)
    if not cleaned:
        return "No text content available."
    
    pipeline_obj = get_summarizer()
    if pipeline_obj:
        try:
            words = cleaned.split()
            truncated_text = " ".join(words[:600])
            
            # Map max/min lengths depending on requested size
            max_len = 50 if max_chars <= 120 else 80
            min_len = 15 if max_chars <= 120 else 30
            
            res = pipeline_obj(truncated_text, max_length=max_len, min_length=min_len, do_sample=False)
            if res and len(res) > 0:
                return res[0]['summary_text'].strip()
        except Exception as e:
            print("Error during Hugging Face summarization:", e)
            
    return extractive_summarize(text, max_chars)

def short_summarize(text, max_chars=100):
    """Create a very short summary of text."""
    return abstractive_summarize(text, max_chars=max_chars)


def walk_parts(parts, result_text, result_images):
    """
    Recursively walk MIME parts.
    - Collect the best text/plain body
    - Collect image attachments (inline data or attachment IDs)
    """
    for part in parts:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        sub_parts = part.get("parts", [])

        if mime == "text/plain" and not result_text["text"]:
            data = body.get("data", "")
            if data:
                result_text["text"] = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        elif mime == "text/html" and not result_text["html"]:
            data = body.get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                # Remove script and style tags first
                html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
                # Remove HTML comments
                html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
                # Remove all HTML tags
                clean = re.sub(r'<[^>]+>', ' ', html)
                result_text["html"] = re.sub(r'\s+', ' ', clean).strip()

        elif mime.startswith("image/"):
            attachment_id = body.get("attachmentId", "")
            inline_data = body.get("data", "")
            filename = part.get("filename", "") or f"image.{mime.split('/')[-1]}"
            if attachment_id:
                result_images.append({
                    "type": "attachment",
                    "attachment_id": attachment_id,
                    "mime_type": mime,
                    "filename": filename
                })
            elif inline_data:
                result_images.append({
                    "type": "inline",
                    "data": inline_data,   # already url-safe base64
                    "mime_type": mime,
                    "filename": filename
                })

        # Recurse into sub-parts (multipart/*)
        if sub_parts:
            walk_parts(sub_parts, result_text, result_images)


def extract_email_content(message):
    """Return (body_text, images_list) from a full Gmail message."""
    payload = message.get("payload", {})
    result_text = {"text": "", "html": ""}
    result_images = []

    # Single-part message
    top_mime = payload.get("mimeType", "")
    top_data = payload.get("body", {}).get("data", "")

    if top_data:
        if top_mime == "text/plain":
            result_text["text"] = base64.urlsafe_b64decode(top_data).decode("utf-8", errors="ignore")
        elif top_mime == "text/html":
            html = base64.urlsafe_b64decode(top_data).decode("utf-8", errors="ignore")
            # Remove script and style tags first
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML comments
            html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
            # Remove all HTML tags
            clean = re.sub(r'<[^>]+>', ' ', html)
            result_text["html"] = re.sub(r'\s+', ' ', clean).strip()
        elif top_mime.startswith("image/"):
            result_images.append({
                "type": "inline",
                "data": top_data,
                "mime_type": top_mime,
                "filename": "image"
            })

    # Multi-part: recurse
    parts = payload.get("parts", [])
    if parts:
        walk_parts(parts, result_text, result_images)

    body = result_text["text"] or result_text["html"] or ""
    return body, result_images


# ─── Routes ────────────────────────────────────────────────────────────────

@app.route("/emails")
def get_emails():
    try:
        creds = load_credentials()
        service = build("gmail", "v1", credentials=creds)
        
        # Pagination parameters
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 5))
        
        # Check if user wants short summaries
        use_short = request.args.get("short", "false").lower() == "true"

        # Get all message IDs first (up to 50)
        results = service.users().messages().list(
            userId="me",
            maxResults=50
        ).execute()

        all_messages = results.get("messages", [])
        total_count = len(all_messages)
        
        # Calculate pagination
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_messages = all_messages[start_idx:end_idx]
        
        email_data = []

        for msg in paginated_messages:
            message = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="full"
            ).execute()

            body, images = extract_email_content(message)
            summary = short_summarize(body) if use_short else abstractive_summarize(body)

            headers = message.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(No Subject)")
            sender  = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")

            # Build image list for frontend
            image_list = []
            for img in images:
                if img["type"] == "inline":
                    # Embed directly as data-url
                    image_list.append({
                        "url": f"data:{img['mime_type']};base64,{img['data']}",
                        "filename": img["filename"],
                        "mime_type": img["mime_type"]
                    })
                else:
                    # Frontend will fetch via /attachment endpoint
                    image_list.append({
                        "url": f"/attachment/{msg['id']}/{img['attachment_id']}",
                        "filename": img["filename"],
                        "mime_type": img["mime_type"]
                    })

            is_unread = "UNREAD" in message.get("labelIds", [])
            email_data.append({
                "id": msg["id"],
                "subject": subject,
                "sender": sender,
                "summary": summary,
                "read": not is_unread,
                "images": image_list
            })

        return jsonify({
            "emails": email_data,
            "total_count": total_count,
            "page": page,
            "per_page": per_page,
            "has_next": end_idx < total_count
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/attachment/<msg_id>/<attachment_id>")
def get_attachment(msg_id, attachment_id):
    """Serve a Gmail attachment as an image response."""
    try:
        creds = load_credentials()
        service = build("gmail", "v1", credentials=creds)

        att = service.users().messages().attachments().get(
            userId="me",
            messageId=msg_id,
            id=attachment_id
        ).execute()

        data = att.get("data", "")
        # Gmail uses URL-safe base64
        image_bytes = base64.urlsafe_b64decode(data + "==")  # pad just in case

        # Try to guess mime type from the request context — default to jpeg
        mime = request.args.get("mime", "image/jpeg")
        return Response(image_bytes, mimetype=mime)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/mark-read", methods=["POST"])
def mark_read():
    try:
        creds = load_credentials()
        service = build("gmail", "v1", credentials=creds)

        msg_id = request.json["id"]
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()

        return jsonify({"message": "Marked as read"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)