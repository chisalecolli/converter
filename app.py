import os
import re
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

def extract_youtube_id(url):
    patterns = [
        r'(?:v=|\/videos\/|embed\/|shorts\/|youtu\.be\/|\/v\/)([0-9A-Za-z_-]{11})',
        r'^([0-9A-Za-z_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_youtube_invidious(video_id, target_path):
    instances = [
        "https://inv.nadeko.net",
        "https://invidious.nerdvpn.de",
        "https://invidious.jing.rocks",
        "https://vid.puffyan.us"
    ]
    for inst in instances:
        try:
            api_url = f"{inst}/api/v1/videos/{video_id}"
            r = requests.get(api_url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", "youtube_video")
                streams = data.get("formatStreams", [])
                if streams:
                    stream_url = streams[0]["url"]
                    if stream_url.startswith("/"):
                        stream_url = f"{inst}{stream_url}"

                    headers = {'User-Agent': 'Mozilla/5.0'}
                    media_resp = requests.get(stream_url, headers=headers, stream=True, timeout=60)
                    if media_resp.status_code == 200:
                        with open(target_path, 'wb') as f:
                            for chunk in media_resp.iter_content(chunk_size=16384):
                                f.write(chunk)
                        return title
        except Exception:
            continue
    return None

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "PocketVault 2yxa Master Studio Ready"})

@app.route("/convert", methods=["POST"])
def convert():
    cleanup_old_files()

    target_format = request.form.get("format", "mp3").lower()
    resolution    = request.form.get("resolution", "176x144")
    url           = request.form.get("url", "").strip()
    
    # 2yxa Advanced Parameters
    start_time    = request.form.get("start_time", "").strip()
    duration      = request.form.get("duration", "").strip()
    volume_boost  = request.form.get("volume", "1.0").strip()
    data_saver    = request.form.get("data_saver", "medium").lower()
    tag_title     = request.form.get("tag_title", "").strip()
    tag_artist    = request.form.get("tag_artist", "").strip()

    uid = str(uuid.uuid4())[:8]
    input_path = None
    original_title = "media"

    # 1. PROCESS URL
    if url:
        if "ct.ws" in url or "epizy.com" in url or "infinityfree" in url:
            return jsonify({"success": False, "error": "Use 'Upload File' tab for site files!"}), 400

        yt_id = extract_youtube_id(url)
        if yt_id:
            input_path = os.path.join(INPUT_DIR, f"{uid}_yt.mp4")
            yt_title = download_youtube_invidious(yt_id, input_path)
            if yt_title:
                original_title = yt_title
            else:
                input_path = None

        if not input_path:
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
                    downloaded_files = glob.glob(os.path.join(INPUT_DIR, f"{uid}_*"))
                    if downloaded_files:
                        input_path = downloaded_files[0]
            except Exception:
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    r = requests.get(url, headers=headers, stream=True, timeout=30)
                    if r.status_code == 200:
                        parsed_path = urllib.parse.urlparse(url).path
                        ext = os.path.splitext(parsed_path)[1] or ".mp4"
                        original_title = os.path.splitext(os.path.basename(parsed_path))[0] or "web_media"
                        input_path = os.path.join(INPUT_DIR, f"{uid}{ext}")
                        with open(input_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                except Exception as e:
                    return jsonify({"success": False, "error": f"Download failed: {str(e)}"}), 400

    # 2. PROCESS FILE UPLOAD
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
        return jsonify({"success": False, "error": "Could not fetch media. Please try again."}), 500

    # Safe Title
    custom_title = tag_title if tag_title else original_title
    safe_title = "".join(c for c in custom_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:40]
    out_filename = f"{safe_title}_{uid}.{target_format}"
    output_path = os.path.join(OUTPUT_DIR, out_filename)

    # Resolution Parse
    res_w, res_h = resolution.split('x') if 'x' in resolution else ('176', '144')

    # Data-Saver Bitrates
    if data_saver == "mini":
        v_bitrate, a_bitrate, fps_rate = "64k", "24k", "12"
    elif data_saver == "high":
        v_bitrate, a_bitrate, fps_rate = "350k", "96k", "24"
    else:  # medium (default)
        v_bitrate, a_bitrate, fps_rate = "120k", "48k", "15"

    # Volume filter
    vol_filter = f"volume={volume_boost}"

    # Build Trimming Options
    trim_args = []
    if start_time:
        trim_args.extend(["-ss", start_time])
    if duration:
        trim_args.extend(["-t", duration])

    # 3. BUILD 2YXA FFMPEG COMMAND
    if target_format == "mp3":
        cmd = ["ffmpeg", "-y"] + trim_args + [
            "-i", input_path,
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", a_bitrate,
            "-filter:a", vol_filter,
            "-metadata", f"title={safe_title}",
            "-metadata", f"artist={tag_artist or 'PocketVault'}",
            output_path
        ]
    elif target_format == "3gp":
        # Universal 3GP for Nokia/Button phones
        cmd = ["ffmpeg", "-y"] + trim_args + [
            "-i", input_path,
            "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r", fps_rate,
            "-c:v", "mpeg4", "-b:v", v_bitrate,
            "-c:a", "aac", "-b:a", a_bitrate, "-ar", "22050", "-ac", "1",
            "-filter:a", vol_filter,
            output_path
        ]
    elif target_format == "mp4":
        cmd = ["ffmpeg", "-y"] + trim_args + [
            "-i", input_path,
            "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p",
            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", a_bitrate,
            "-filter:a", vol_filter,
            output_path
        ]
    elif target_format == "gif":
        # Animated GIF generator (avoids oversized gifs with 10fps limit)
        gif_duration = duration if duration else "6"
        cmd = ["ffmpeg", "-y"] + trim_args + [
            "-i", input_path,
            "-t", gif_duration,
            "-vf", f"fps=10,scale={res_w}:-1:flags=lanczos",
            output_path
        ]
    elif target_format == "jpg":
        # Video Screenshot / Poster Grabber
        capture_at = start_time if start_time else "00:00:05"
        cmd = ["ffmpeg", "-y", "-ss", capture_at, "-i", input_path, "-vframes", "1", "-q:v", "2", output_path]
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
            return jsonify({"success": False, "error": "Output file not created"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
