import os
import time
import uuid
import glob
import subprocess
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory
import requests
import yt_dlp

app = Flask(__name__)

BASE_DIR = "/tmp/pocketvault"
INPUT_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUT_DIR = os.path.join(BASE_DIR, "converted")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def cleanup_old_files():
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
    return jsonify({"status": "PocketVault 2yxa Engine v3 Ready"})

@app.route("/convert", methods=["POST"])
def convert():
    cleanup_old_files()

    target_format = request.form.get("format", "mp3").lower()
    resolution = request.form.get("resolution", "176x144")
    url = request.form.get("url", "").strip()
    uid = str(uuid.uuid4())[:8]

    input_path = None
    original_title = "media"

    # 1. PROCESS URL
    if url:
        if "ct.ws" in url or "epizy.com" in url or "infinityfree" in url:
            return jsonify({
                "success": False, 
                "error": "InfinityFree blocks external scripts. Use the 'Upload File' tab for this file!"
            }), 400

        # Best extractor configuration to bypass YouTube datacenter blocks
        ydl_opts = {
            'outtmpl': os.path.join(INPUT_DIR, f"{uid}_%(title)s.%(ext)s"),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv', 'web_embedded', 'android_vr'],
                    'player_skip': ['webpage', 'configs']
                }
            }
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                original_title = info.get('title', 'video')
                downloaded_files = glob.glob(os.path.join(INPUT_DIR, f"{uid}_*"))
                if downloaded_files:
                    input_path = downloaded_files[0]
        except Exception as yt_err:
            # Fallback for Direct Links (.mp4 / .mp3)
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                r = requests.get(url, headers=headers, stream=True, timeout=30)
                if r.status_code == 200 and 'video' in r.headers.get('content-type', '') or 'audio' in r.headers.get('content-type', '') or url.endswith(('.mp4', '.3gp', '.mp3')):
                    parsed_path = urllib.parse.urlparse(url).path
                    ext = os.path.splitext(parsed_path)[1] or ".mp4"
                    original_title = os.path.splitext(os.path.basename(parsed_path))[0] or "web_media"
                    input_path = os.path.join(INPUT_DIR, f"{uid}{ext}")
                    with open(input_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                else:
                    return jsonify({"success": False, "error": f"YouTube/Link error: {str(yt_err)}"}), 400
            except Exception:
                return jsonify({"success": False, "error": f"Download failed: {str(yt_err)}"}), 400

    # 2. PROCESS DIRECT FILE UPLOAD
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
        return jsonify({"success": False, "error": "File was not downloaded. Try another link or upload directly."}), 500

    # Clean filename
    safe_title = "".join(c for c in original_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:40]
    out_filename = f"{safe_title}_{uid}.{target_format}"
    output_path = os.path.join(OUTPUT_DIR, out_filename)

    if 'x' in resolution:
        res_w, res_h = resolution.split('x')
    else:
        res_w, res_h = '176', '144'

    # 3. FFMPEG TRANSCODING
    if target_format == "mp3":
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            output_path
        ]
    elif target_format == "3gp":
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r", "15",
            "-c:v", "mpeg4", "-b:v", "120k",
            "-c:a", "aac", "-b:a", "32k", "-ar", "22050", "-ac", "1",
            output_path
        ]
    elif target_format == "mp4":
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p",
            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "64k",
            output_path
        ]
    else:
        return jsonify({"success": False, "error": "Unsupported target format"}), 400

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if proc.returncode != 0:
            err_msg = proc.stderr.decode('utf-8', errors='ignore')
            short_err = "\n".join(err_msg.strip().splitlines()[-3:])
            return jsonify({"success": False, "error": f"FFmpeg error: {short_err}"}), 500

        if os.path.exists(output_path):
            file_bytes = os.path.getsize(output_path)
            file_size_mb = round(file_bytes / (1024 * 1024), 2)
            
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
            return jsonify({"success": False, "error": "Output file was not created"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
