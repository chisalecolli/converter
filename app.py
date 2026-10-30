import os
import time
import uuid
import glob
import subprocess
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp
h

app = Flask(__name__)

BASE_DIR = "/tmp/pocketvault"
INPUT_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUT_DIR = os.path.join(BASE_DIR, "converted")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def cleanup_old_files():
    """Delete files older than 2 hours to keep Render disk clean"""
    now = time.time()
    for folder in [INPUT_DIR, OUTPUT_DIR]:
        for filepath in glob.glob(os.path.join(folder, "*")):
            if os.stat(filepath).st_mtime < now - 7200:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "PocketVault 2yxa Engine Ready (YouTube, TikTok & Files)"})

@app.route("/convert", methods=["POST"])
def convert():
    cleanup_old_files()

    target_format = request.form.get("format", "mp3").lower()
    resolution = request.form.get("resolution", "176x144")
    url = request.form.get("url", "").strip()
    uid = str(uuid.uuid4())[:8]

    input_path = None
    original_title = "media"

    # CASE A: User gave a Link (YouTube, TikTok, or Direct URL)
    if url:
        ydl_opts = {
            'outtmpl': os.path.join(INPUT_DIR, f"{uid}_%(title)s.%(ext)s"),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                original_title = info.get('title', 'video')
                # Find the downloaded file
                downloaded_files = glob.glob(os.path.join(INPUT_DIR, f"{uid}_*"))
                if downloaded_files:
                    input_path = downloaded_files[0]
        except Exception as e:
            return jsonify({"success": False, "error": f"Failed to fetch link: {str(e)}"}), 400

    # CASE B: User uploaded a File
    elif "file" in request.files:
        uploaded_file = request.files["file"]
        if uploaded_file.filename == '':
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        ext = os.path.splitext(uploaded_file.filename)[1] or ".mp4"
        original_title = os.path.splitext(uploaded_file.filename)[0]
        input_path = os.path.join(INPUT_DIR, f"{uid}{ext}")
        uploaded_file.save(input_path)

    else:
        return jsonify({"success": False, "error": "No file or URL provided"}), 400

    if not input_path or not os.path.exists(input_path):
        return jsonify({"success": False, "error": "Could not retrieve media file"}), 500

    # Prepare Output
    safe_title = "".join(c for c in original_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:40]
    out_filename = f"{safe_title}_{uid}.{target_format}"
    output_path = os.path.join(OUTPUT_DIR, out_filename)

    # Build FFmpeg command
    if target_format == "mp3":
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            output_path
        ]
    elif target_format == "3gp":
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-s", resolution, "-r", "15", "-b:v", "100k",
            "-c:a", "amr_nb", "-ar", "8000", "-ac", "1",
            output_path
        ]
    elif target_format == "mp4":
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={resolution}", "-c:v", "libx264", "-crf", "28",
            "-c:a", "aac", "-b:a", "64k", "-preset", "veryfast",
            output_path
        ]
    else:
        return jsonify({"success": False, "error": "Unsupported target format"}), 400

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        if os.path.exists(output_path):
            file_bytes = os.path.getsize(output_path)
            file_size_mb = round(file_bytes / (1024 * 1024), 2)
            
            # Clean up input file to save space
            if os.path.exists(input_path):
                os.remove(input_path)

            download_url = f"{request.host_url.rstrip('/')}/download/{out_filename}"

            return jsonify({
                "success": True,
                "title": safe_title,
                "format": target_format.upper(),
                "size": f"{file_size_mb} MB",
                "download_url": download_url
            })
        else:
            return jsonify({"success": False, "error": "Conversion failed"}), 500

    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": "FFmpeg transcoding error"}), 500

@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
