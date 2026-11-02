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
from PIL import Image, ImageDraw, ImageFont, ImageFilter

app = Flask(__name__)


BASE_DIR = "/tmp/pocketvault"
INPUT_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUT_DIR = os.path.join(BASE_DIR, "converted")
FONT_DIR = os.path.join(BASE_DIR, "fonts")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

DEFAULT_FONT_PATH = os.path.join(FONT_DIR, "Anton-Regular.ttf")

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

def get_bold_font(font_size):
    """Auto-downloads a heavy, bold headline font if not present"""
    if not os.path.exists(DEFAULT_FONT_PATH):
        try:
            font_url = "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
            r = requests.get(font_url, timeout=10)
            if r.status_code == 200:
                with open(DEFAULT_FONT_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass
    try:
        return ImageFont.truetype(DEFAULT_FONT_PATH, font_size)
    except Exception:
        return ImageFont.load_default()

# ----------------- ROUTES ----------------- #

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "PocketVault 2yxa Master Studio & Logo Engine Ready"})

# 1. 2YXA MEDIA CONVERTER
@app.route("/convert", methods=["POST"])
def convert():
    cleanup_old_files()

    target_format = request.form.get("format", "mp3").lower()
    resolution    = request.form.get("resolution", "176x144")
    url           = request.form.get("url", "").strip()
    
    start_time    = request.form.get("start_time", "").strip()
    duration      = request.form.get("duration", "").strip()
    volume_boost  = request.form.get("volume", "1.0").strip()
    data_saver    = request.form.get("data_saver", "medium").lower()
    tag_title     = request.form.get("tag_title", "").strip()
    tag_artist    = request.form.get("tag_artist", "").strip()

    uid = str(uuid.uuid4())[:8]
    input_source = None
    original_title = "media"
    is_direct_stream = False

    # A: Check URL
    if url:
        if "ct.ws" in url or "epizy.com" in url or "infinityfree" in url:
            return jsonify({"success": False, "error": "Use 'Upload File' tab for site files!"}), 400

        yt_id = extract_youtube_id(url)
        if yt_id:
            input_source = os.path.join(INPUT_DIR, f"{uid}_yt.mp4")
            yt_title = download_youtube_invidious(yt_id, input_source)
            if yt_title:
                original_title = yt_title
            else:
                input_source = None

        if not input_source and ('.mp4' in url or 'hakunaymatata' in url or 'bcdn' in url):
            input_source = url
            is_direct_stream = True
            original_title = "movie_part"

        if not input_source:
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
                        input_source = downloaded_files[0]
            except Exception as e:
                return jsonify({"success": False, "error": f"Failed to download link: {str(e)}"}), 400

    # B: Check Uploaded File
    elif "file" in request.files:
        uploaded_file = request.files["file"]
        if uploaded_file.filename == '':
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        ext = os.path.splitext(uploaded_file.filename)[1] or ".mp4"
        original_title = os.path.splitext(uploaded_file.filename)[0]
        input_source = os.path.join(INPUT_DIR, f"{uid}{ext}")
        uploaded_file.save(input_source)
    else:
        return jsonify({"success": False, "error": "No file or URL provided"}), 400

    if not input_source:
        return jsonify({"success": False, "error": "Could not access media stream. Check link."}), 500

    custom_title = tag_title if tag_title else original_title
    safe_title = "".join(c for c in custom_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:40]
    out_filename = f"{safe_title}_{uid}.{target_format}"
    output_path = os.path.join(OUTPUT_DIR, out_filename)

    res_w, res_h = resolution.split('x') if 'x' in resolution else ('176', '144')

    if data_saver == "mini":
        v_bitrate, a_bitrate, fps_rate = "64k", "24k", "12"
    elif data_saver == "high":
        v_bitrate, a_bitrate, fps_rate = "350k", "96k", "24"
    else:
        v_bitrate, a_bitrate, fps_rate = "120k", "48k", "15"

    vol_filter = f"volume={volume_boost}"

    trim_args = []
    if start_time:
        trim_args.extend(["-ss", start_time])
    if duration:
        trim_args.extend(["-t", duration])

    headers_arg = []
    if is_direct_stream:
        headers_arg = [
            "-headers", 
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\nReferer: https://videodownloader.site/\r\nOrigin: https://videodownloader.site\r\n"
        ]

    if target_format == "mp3":
        cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + [
            "-i", input_source,
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", a_bitrate,
            "-filter:a", vol_filter,
            "-metadata", f"title={safe_title}",
            "-metadata", f"artist={tag_artist or 'PocketVault'}",
            output_path
        ]
    elif target_format == "3gp":
        cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + [
            "-i", input_source,
            "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r", fps_rate,
            "-c:v", "mpeg4", "-b:v", v_bitrate,
            "-c:a", "aac", "-b:a", a_bitrate, "-ar", "22050", "-ac", "1",
            "-filter:a", vol_filter,
            output_path
        ]
    elif target_format == "mp4":
        if is_direct_stream and data_saver != "mini" and not start_time:
            cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + [
                "-i", input_source,
                "-c", "copy",
                output_path
            ]
        else:
            cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + [
                "-i", input_source,
                "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p",
                "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "64k",
                "-filter:a", vol_filter,
                output_path
            ]
    elif target_format == "gif":
        gif_duration = duration if duration else "6"
        cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + [
            "-i", input_source,
            "-t", gif_duration,
            "-vf", f"fps=10,scale={res_w}:-1:flags=lanczos",
            output_path
        ]
    elif target_format == "jpg":
        capture_at = start_time if start_time else "00:00:05"
        cmd = ["ffmpeg", "-y"] + headers_arg + ["-ss", capture_at, "-i", input_source, "-vframes", "1", "-q:v", "2", output_path]
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
            
            if not is_direct_stream and os.path.exists(input_source):
                os.remove(input_source)

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


# 2. 3D & STYLED TEXT LOGO MAKER
@app.route("/logo", methods=["POST"])
def generate_logo():
    cleanup_old_files()

    text = request.form.get("text", "LOGO").strip().upper()
    if not text:
        text = "LOGO"
    if len(text) > 25:
        text = text[:25]

    style = request.form.get("style", "3d_chrome")
    bg_mode = request.form.get("bg_mode", "transparent")
    canvas_mode = request.form.get("canvas_mode", "logo")

    if canvas_mode == "nokia":
        width, height = 240, 320
        font_size = 32 if len(text) > 10 else 44
    elif canvas_mode == "android":
        width, height = 720, 1280
        font_size = 70 if len(text) > 10 else 95
    else:
        width, height = 650, 220
        font_size = 55 if len(text) > 10 else 75

    if bg_mode == "black" or style.startswith("neon"):
        img = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    elif bg_mode == "white":
        img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    else:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    draw = ImageDraw.Draw(img)
    font = get_bold_font(font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = (height - text_h) // 2

    # STYLE 1: 3D Chrome
    if style == "3d_chrome":
        for offset in range(12, 0, -1):
            draw.text((x + offset, y + offset), text, font=font, fill=(30, 41, 59, 255))
        draw.text((x + 1, y + 1), text, font=font, fill=(71, 85, 105, 255))
        draw.text((x, y), text, font=font, fill=(241, 245, 249, 255))

    # STYLE 2: Gold Metallic
    elif style == "gold":
        for offset in range(10, 0, -1):
            draw.text((x + offset, y + offset), text, font=font, fill=(113, 63, 18, 255))
        draw.text((x + 2, y + 2), text, font=font, fill=(202, 138, 4, 255))
        draw.text((x, y), text, font=font, fill=(254, 240, 138, 255))

    # STYLE 3: Cyber Neon (Cyan / Green)
    elif style == "neon_cyan" or style == "neon_green":
        neon_color = (6, 182, 212, 255) if style == "neon_cyan" else (34, 197, 94, 255)
        glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        for glow_offset in range(8, 0, -2):
            glow_draw.text((x, y), text, font=font, fill=neon_color)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=6))
        img = Image.alpha_composite(img, glow_layer)
        draw = ImageDraw.Draw(img)
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    # STYLE 4: Comic / Graffiti
    elif style == "comic":
        stroke_color = (15, 23, 42, 255)
        fill_color = (250, 204, 21, 255)
        draw.text((x + 4, y + 4), text, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), text, font=font, fill=fill_color, stroke_width=4, stroke_fill=stroke_color)

    uid = str(uuid.uuid4())[:8]
    clean_name = "".join(c for c in text if c.isalnum()).lower()[:12] or "logo"
    out_filename = f"{clean_name}_{uid}.png"
    output_path = os.path.join(OUTPUT_DIR, out_filename)
    img.save(output_path, "PNG")

    download_url = f"{request.host_url.rstrip('/')}/download/{out_filename}"

    return jsonify({
        "success": True,
        "title": text,
        "download_url": download_url
    })


# 3. DIRECT DOWNLOAD ROUTE
@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
