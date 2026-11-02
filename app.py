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
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

app = Flask(__name__)

BASE_DIR = "/tmp/pocketvault"
INPUT_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUT_DIR = os.path.join(BASE_DIR, "converted")
FONT_DIR = os.path.join(BASE_DIR, "fonts")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

# Font URL mappings (Free Google Fonts)
FONT_URLS = {
    "anton": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "bangers": "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
    "orbitron": "https://github.com/google/fonts/raw/main/ofl/orbitron/static/Orbitron-Bold.ttf",
    "pixel": "https://github.com/google/fonts/raw/main/ofl/pressstart2p/PressStart2P-Regular.ttf"
}

def cleanup_old_files():
    now = time.time()
    for folder in [INPUT_DIR, OUTPUT_DIR]:
        for filepath in glob.glob(os.path.join(folder, "*")):
            if os.stat(filepath).st_mtime < now - 7200:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

def get_custom_font(font_key, font_size):
    """Auto-downloads and loads the selected font"""
    font_path = os.path.join(FONT_DIR, f"{font_key}.ttf")
    if not os.path.exists(font_path) and font_key in FONT_URLS:
        try:
            r = requests.get(FONT_URLS[font_key], timeout=8)
            if r.status_code == 200:
                with open(font_path, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass
    try:
        return ImageFont.truetype(font_path, font_size)
    except Exception:
        # Fallback to Anton or default
        anton_path = os.path.join(FONT_DIR, "anton.ttf")
        if os.path.exists(anton_path):
            try:
                return ImageFont.truetype(anton_path, font_size)
            except Exception:
                pass
        return ImageFont.load_default()

def draw_vector_icon(draw, icon_name, cx, cy, size, color):
    """Draws clean geometric icons without external emoji dependencies"""
    hs = size // 2
    if icon_name == "crown":
        pts = [
            (cx - hs, cy + hs // 2),
            (cx - hs, cy - hs // 4),
            (cx - hs // 2, cy),
            (cx, cy - hs // 2),
            (cx + hs // 2, cy),
            (cx + hs, cy - hs // 4),
            (cx + hs, cy + hs // 2)
        ]
        draw.polygon(pts, fill=color)
        for pt in [(cx - hs, cy - hs // 4), (cx, cy - hs // 2), (cx + hs, cy - hs // 4)]:
            draw.ellipse((pt[0]-2, pt[1]-4, pt[0]+2, pt[1]), fill=(255, 255, 255, 255))
    elif icon_name == "star":
        pts = []
        import math
        for i in range(10):
            r = hs if i % 2 == 0 else hs // 2
            angle = i * math.pi / 5 - math.pi / 2
            pts.append((cx + int(r * math.cos(angle)), cy + int(r * math.sin(angle))))
        draw.polygon(pts, fill=color)
    elif icon_name == "lightning":
        pts = [
            (cx + hs // 4, cy - hs),
            (cx - hs // 3, cy),
            (cx, cy),
            (cx - hs // 4, cy + hs),
            (cx + hs // 2, cy - hs // 4),
            (cx + hs // 8, cy - hs // 4)
        ]
        draw.polygon(pts, fill=color)
    elif icon_name == "headphones":
        draw.arc((cx - hs, cy - hs, cx + hs, cy + hs), start=180, end=0, fill=color, width=4)
        draw.rounded_rectangle((cx - hs - 2, cy - 2, cx - hs + 6, cy + hs - 2), radius=3, fill=color)
        draw.rounded_rectangle((cx + hs - 6, cy - 2, cx + hs + 2, cy + hs - 2), radius=3, fill=color)
    elif icon_name == "fire":
        pts = [
            (cx, cy - hs),
            (cx + hs // 2, cy - hs // 4),
            (cx + hs, cy + hs // 3),
            (cx + hs // 3, cy + hs),
            (cx - hs // 3, cy + hs),
            (cx - hs, cy + hs // 3),
            (cx - hs // 2, cy - hs // 4)
        ]
        draw.polygon(pts, fill=color)

# ----------------- ROUTES ----------------- #

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "PocketVault Studio v2 Ready (Converter + Pro Logo Maker)"})

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

    if url:
        if "ct.ws" in url or "epizy.com" in url or "infinityfree" in url:
            return jsonify({"success": False, "error": "Use 'Upload File' tab for site files!"}), 400

        # Check YouTube
        patterns = [r'(?:v=|\/videos\/|embed\/|shorts\/|youtu\.be\/|\/v\/)([0-9A-Za-z_-]{11})', r'^([0-9A-Za-z_-]{11})$']
        yt_id = None
        for p in patterns:
            m = re.search(p, url)
            if m:
                yt_id = m.group(1)
                break

        if yt_id:
            input_source = os.path.join(INPUT_DIR, f"{uid}_yt.mp4")
            for inst in ["https://inv.nadeko.net", "https://invidious.nerdvpn.de", "https://invidious.jing.rocks"]:
                try:
                    r = requests.get(f"{inst}/api/v1/videos/{yt_id}", timeout=8)
                    if r.status_code == 200:
                        data = r.json()
                        streams = data.get("formatStreams", [])
                        if streams:
                            s_url = streams[0]["url"]
                            if s_url.startswith("/"): s_url = f"{inst}{s_url}"
                            mr = requests.get(s_url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=60)
                            if mr.status_code == 200:
                                with open(input_source, 'wb') as f:
                                    for ch in mr.iter_content(16384): f.write(ch)
                                original_title = data.get("title", "youtube_video")
                                break
                except Exception:
                    continue

        if not input_source and ('.mp4' in url or 'hakunaymatata' in url or 'bcdn' in url):
            input_source = url
            is_direct_stream = True
            original_title = "movie_part"

        if not input_source:
            ydl_opts = {'outtmpl': os.path.join(INPUT_DIR, f"{uid}_%(title)s.%(ext)s"), 'quiet': True, 'noplaylist': True}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    original_title = info.get('title', 'video')
                    df = glob.glob(os.path.join(INPUT_DIR, f"{uid}_*"))
                    if df: input_source = df[0]
            except Exception as e:
                return jsonify({"success": False, "error": f"Failed to download link: {str(e)}"}), 400

    elif "file" in request.files:
        f = request.files["file"]
        if f.filename == '': return jsonify({"success": False, "error": "No file selected"}), 400
        ext = os.path.splitext(f.filename)[1] or ".mp4"
        original_title = os.path.splitext(f.filename)[0]
        input_source = os.path.join(INPUT_DIR, f"{uid}{ext}")
        f.save(input_source)
    else:
        return jsonify({"success": False, "error": "No file or URL provided"}), 400

    if not input_source:
        return jsonify({"success": False, "error": "Could not access media stream."}), 500

    custom_title = tag_title if tag_title else original_title
    safe_title = "".join(c for c in custom_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:40]
    out_filename = f"{safe_title}_{uid}.{target_format}"
    output_path = os.path.join(OUTPUT_DIR, out_filename)

    res_w, res_h = resolution.split('x') if 'x' in resolution else ('176', '144')
    v_bitrate, a_bitrate, fps_rate = ("64k", "24k", "12") if data_saver == "mini" else (("350k", "96k", "24") if data_saver == "high" else ("120k", "48k", "15"))
    vol_filter = f"volume={volume_boost}"

    trim_args = []
    if start_time: trim_args.extend(["-ss", start_time])
    if duration: trim_args.extend(["-t", duration])

    headers_arg = ["-headers", "User-Agent: Mozilla/5.0\r\nReferer: https://videodownloader.site/\r\n"] if is_direct_stream else []

    if target_format == "mp3":
        cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + ["-i", input_source, "-vn", "-ar", "44100", "-ac", "2", "-b:a", a_bitrate, "-filter:a", vol_filter, output_path]
    elif target_format == "3gp":
        cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + ["-i", input_source, "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1", "-r", fps_rate, "-c:v", "mpeg4", "-b:v", v_bitrate, "-c:a", "aac", "-b:a", a_bitrate, "-ar", "22050", "-ac", "1", "-filter:a", vol_filter, output_path]
    elif target_format == "mp4":
        if is_direct_stream and data_saver != "mini" and not start_time:
            cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + ["-i", input_source, "-c", "copy", output_path]
        else:
            cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + ["-i", input_source, "-vf", f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p", "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "64k", "-filter:a", vol_filter, output_path]
    elif target_format == "gif":
        cmd = ["ffmpeg", "-y"] + headers_arg + trim_args + ["-i", input_source, "-t", duration or "6", "-vf", f"fps=10,scale={res_w}:-1:flags=lanczos", output_path]
    elif target_format == "jpg":
        cmd = ["ffmpeg", "-y"] + headers_arg + ["-ss", start_time or "00:00:05", "-i", input_source, "-vframes", "1", "-q:v", "2", output_path]
    else:
        return jsonify({"success": False, "error": "Unsupported target format"}), 400

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            err = proc.stderr.decode('utf-8', errors='ignore')
            return jsonify({"success": False, "error": f"FFmpeg: {err.strip()[-100:]}"}), 500

        if os.path.exists(output_path):
            file_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
            if not is_direct_stream and os.path.exists(input_source): os.remove(input_source)
            return jsonify({
                "success": True,
                "title": safe_title,
                "format": target_format.upper(),
                "size": f"{file_mb} MB",
                "download_url": f"{request.host_url.rstrip('/')}/download/{out_filename}"
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# 2. LOGO STUDIO V2
@app.route("/logo", methods=["POST"])
def generate_logo():
    cleanup_old_files()

    text        = request.form.get("text", "LOGO").strip().upper()[:25] or "LOGO"
    subtitle    = request.form.get("subtitle", "").strip().upper()[:30]
    font_key    = request.form.get("font_family", "anton").lower()
    style       = request.form.get("style", "3d_chrome")
    icon_name   = request.form.get("icon", "none").lower()
    frame_style = request.form.get("frame", "none").lower()
    has_refl    = request.form.get("reflection", "no").lower() == "yes"
    bg_mode     = request.form.get("bg_mode", "transparent")
    canvas_mode = request.form.get("canvas_mode", "logo")

    # Dimensions
    if canvas_mode == "nokia":
        width, height = 240, 320
        font_size = 28 if len(text) > 10 else 38
        sub_size = 11
    elif canvas_mode == "android":
        width, height = 720, 1280
        font_size = 65 if len(text) > 10 else 90
        sub_size = 22
    else:  # Standard Banner / Badge
        width, height = 750, 360
        font_size = 56 if len(text) > 10 else 76
        sub_size = 16

    # Base Background
    is_dark = (bg_mode == "black" or "neon" in style or style in ["fire", "ice", "toxic"])
    if is_dark:
        img = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    elif bg_mode == "white":
        img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    else:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    draw = ImageDraw.Draw(img)
    main_font = get_custom_font(font_key, font_size)
    sub_font = get_custom_font("orbitron" if font_key != "orbitron" else "anton", sub_size)

    # Main text bounds
    bbox = draw.textbbox((0, 0), text, font=main_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Center alignment math
    total_block_h = th
    if subtitle: total_block_h += sub_size + 14
    if icon_name != "none": total_block_h += 38

    start_y = (height - total_block_h) // 2
    if has_refl: start_y = max(20, start_y - 25)

    curr_y = start_y

    # DRAW ICON BADGE
    if icon_name != "none":
        icon_color = (250, 204, 21, 255) if "gold" in style or style == "comic" else ((6, 182, 212, 255) if "cyan" in style or style == "ice" else (241, 245, 249, 255))
        draw_vector_icon(draw, icon_name, width // 2, curr_y + 12, 24, icon_color)
        curr_y += 34

    # DRAW MAIN TEXT STYLES
    tx = (width - tw) // 2

    if style == "3d_chrome":
        for o in range(12, 0, -1):
            draw.text((tx + o, curr_y + o), text, font=main_font, fill=(30, 41, 59, 255))
        draw.text((tx + 1, curr_y + 1), text, font=main_font, fill=(71, 85, 105, 255))
        draw.text((tx, curr_y), text, font=main_font, fill=(241, 245, 249, 255))

    elif style == "gold":
        for o in range(10, 0, -1):
            draw.text((tx + o, curr_y + o), text, font=main_font, fill=(113, 63, 18, 255))
        draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(202, 138, 4, 255))
        draw.text((tx, curr_y), text, font=main_font, fill=(254, 240, 138, 255))

    elif style in ["neon_cyan", "neon_green"]:
        nc = (6, 182, 212, 255) if style == "neon_cyan" else (34, 197, 94, 255)
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        for go in range(10, 0, -2):
            gdraw.text((tx, curr_y), text, font=main_font, fill=nc)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=7))
        img = Image.alpha_composite(img, glow)
        draw = ImageDraw.Draw(img)
        draw.text((tx, curr_y), text, font=main_font, fill=(255, 255, 255, 255))

    elif style == "fire":
        for o in range(10, 0, -1):
            draw.text((tx + o, curr_y + o), text, font=main_font, fill=(127, 29, 29, 255)) # Dark red shadow
        draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(234, 88, 12, 255))  # Orange
        draw.text((tx, curr_y), text, font=main_font, fill=(254, 240, 138, 255))         # Bright Yellow

    elif style == "ice":
        for o in range(9, 0, -1):
            draw.text((tx + o, curr_y + o), text, font=main_font, fill=(12, 74, 110, 255)) # Deep ice blue
        draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(56, 189, 248, 255)) # Cyan
        draw.text((tx, curr_y), text, font=main_font, fill=(240, 249, 255, 255))        # Frost White

    elif style == "toxic":
        for o in range(8, 0, -1):
            draw.text((tx + o, curr_y + o), text, font=main_font, fill=(20, 83, 45, 255))
        draw.text((tx, curr_y), text, font=main_font, fill=(74, 222, 128, 255), stroke_width=3, stroke_fill=(5, 46, 22, 255))

    elif style == "comic":
        draw.text((tx + 4, curr_y + 4), text, font=main_font, fill=(0, 0, 0, 180))
        draw.text((tx, curr_y), text, font=main_font, fill=(250, 204, 21, 255), stroke_width=4, stroke_fill=(15, 23, 42, 255))

    curr_y += th + 8

    # DRAW SUBTITLE / TAGLINE
    if subtitle:
        sbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sw = sbox[2] - sbox[0]
        sx = (width - sw) // 2
        # Pill badge background behind subtitle
        draw.rounded_rectangle((sx - 12, curr_y, sx + sw + 12, curr_y + sub_size + 8), radius=4, fill=(30, 41, 59, 220))
        draw.text((sx, curr_y + 3), subtitle, font=sub_font, fill=(148, 163, 184, 255))
        curr_y += sub_size + 14

    # DRAW FRAMES / BORDERS
    margin_w = min(tw + 70, width - 20)
    frame_x1 = (width - margin_w) // 2
    frame_x2 = frame_x1 + margin_w
    frame_y1 = max(10, start_y - 12)
    frame_y2 = curr_y + 8

    if frame_style == "box":
        draw.rectangle((frame_x1, frame_y1, frame_x2, frame_y2), outline=(56, 189, 248, 255), width=2)
    elif frame_style == "pill":
        draw.rounded_rectangle((frame_x1, frame_y1, frame_x2, frame_y2), radius=16, outline=(250, 204, 21, 255), width=2)
    elif frame_style == "underline":
        draw.line((frame_x1 + 20, frame_y2, frame_x2 - 20, frame_y2), fill=(56, 189, 248, 255), width=3)
        draw.line((frame_x1 + 40, frame_y2 + 5, frame_x2 - 40, frame_y2 + 5), fill=(148, 163, 184, 180), width=1)

    # DRAW GLASS FLOOR REFLECTION
    if has_refl and frame_y2 < height - 30:
        crop_box = (frame_x1 - 10, start_y, frame_x2 + 10, min(curr_y, height - 10))
        cropped = img.crop(crop_box)
        flipped = ImageOps.flip(cropped)

        # Create gradient alpha mask
        alpha_mask = Image.new("L", flipped.size, 0)
        for y_idx in range(flipped.height):
            alpha_val = int(100 * (1 - (y_idx / flipped.height)))
            for x_idx in range(flipped.width):
                alpha_mask.putpixel((x_idx, y_idx), alpha_val)

        flipped.putalpha(alpha_mask)
        img.paste(flipped, (crop_box[0], curr_y + 2), flipped)

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


@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
