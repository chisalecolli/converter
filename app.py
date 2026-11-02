import os
import re
import time
import uuid
import glob
import math
import subprocess
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory
import requests
import yt_dlp
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageEnhance

app = Flask(__name__)

BASE_DIR = "/tmp/pocketvault"
INPUT_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUT_DIR = os.path.join(BASE_DIR, "converted")
FONT_DIR = os.path.join(BASE_DIR, "fonts")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

# Free Google Fonts mapping
FONT_URLS = {
    "anton": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "bangers": "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
    "orbitron": "https://github.com/google/fonts/raw/main/ofl/orbitron/static/Orbitron-Bold.ttf",
    "pixel": "https://github.com/google/fonts/raw/main/ofl/pressstart2p/PressStart2P-Regular.ttf",
    "signature": "https://github.com/google/fonts/raw/main/ofl/pacifico/Pacifico-Regular.ttf",
    "gothic": "https://github.com/google/fonts/raw/main/ofl/creepster/Creepster-Regular.ttf",
    "modern": "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Black.ttf"
}

def cleanup_old_files():
    """Removes temporary files older than 2 hours to keep disk space free"""
    now = time.time()
    for folder in [INPUT_DIR, OUTPUT_DIR]:
        for filepath in glob.glob(os.path.join(folder, "*")):
            if os.stat(filepath).st_mtime < now - 7200:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

def get_custom_font(font_key, font_size):
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
        anton_path = os.path.join(FONT_DIR, "anton.ttf")
        if os.path.exists(anton_path):
            try:
                return ImageFont.truetype(anton_path, font_size)
            except Exception:
                pass
        return ImageFont.load_default()

def draw_vector_icon(draw, icon_name, cx, cy, size, color):
    hs = size // 2
    if icon_name == "crown":
        pts = [(cx - hs, cy + hs // 2), (cx - hs, cy - hs // 4), (cx - hs // 2, cy), (cx, cy - hs // 2), (cx + hs // 2, cy), (cx + hs, cy - hs // 4), (cx + hs, cy + hs // 2)]
        draw.polygon(pts, fill=color)
        for pt in [(cx - hs, cy - hs // 4), (cx, cy - hs // 2), (cx + hs, cy - hs // 4)]:
            draw.ellipse((pt[0]-2, pt[1]-4, pt[0]+2, pt[1]), fill=(255, 255, 255, 255))
    elif icon_name == "star":
        pts = []
        for i in range(10):
            r = hs if i % 2 == 0 else hs // 2
            angle = i * math.pi / 5 - math.pi / 2
            pts.append((cx + int(r * math.cos(angle)), cy + int(r * math.sin(angle))))
        draw.polygon(pts, fill=color)
    elif icon_name == "lightning":
        pts = [(cx + hs // 4, cy - hs), (cx - hs // 3, cy), (cx, cy), (cx - hs // 4, cy + hs), (cx + hs // 2, cy - hs // 4), (cx + hs // 8, cy - hs // 4)]
        draw.polygon(pts, fill=color)
    elif icon_name == "headphones":
        draw.arc((cx - hs, cy - hs, cx + hs, cy + hs), start=180, end=0, fill=color, width=4)
        draw.rounded_rectangle((cx - hs - 2, cy - 2, cx - hs + 6, cy + hs - 2), radius=3, fill=color)
        draw.rounded_rectangle((cx + hs - 6, cy - 2, cx + hs + 2, cy + hs - 2), radius=3, fill=color)
    elif icon_name == "fire":
        pts = [(cx, cy - hs), (cx + hs // 2, cy - hs // 4), (cx + hs, cy + hs // 3), (cx + hs // 3, cy + hs), (cx - hs // 3, cy + hs), (cx - hs, cy + hs // 3), (cx - hs // 2, cy - hs // 4)]
        draw.polygon(pts, fill=color)

def make_circle_crop(img, size, border_color=(250, 204, 21, 255), border_width=4):
    img = ImageOps.fit(img, (size, size), centering=(0.5, 0.5))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(img, (0, 0), mask=mask)
    out_draw = ImageDraw.Draw(output)
    out_draw.ellipse((1, 1, size - 2, size - 2), outline=border_color, width=border_width)
    return output

def resolve_phoneky_link(phoneky_url):
    """Inspects a Phoneky download page and finds the real downloadwap.com .jar URL using mobile headers"""
    if phoneky_url.endswith('.jar'):
        return phoneky_url, None

    mobile_headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Upgrade-Insecure-Requests': '1'
    }

    game_title = None
    session = requests.Session()

    try:
        r = session.get(phoneky_url, headers=mobile_headers, timeout=20, allow_redirects=True)
        if r.status_code == 403 and "mobile.phoneky.com" in phoneky_url:
            desktop_url = phoneky_url.replace("mobile.phoneky.com", "phoneky.com")
            r = session.get(desktop_url, headers=mobile_headers, timeout=20, allow_redirects=True)

        if r.status_code == 200:
            tm = re.search(r'<title>(.*?)</title>', r.text, re.IGNORECASE)
            if tm:
                t_str = tm.group(1).split('|')[0].split('-')[0].strip()
                if t_str:
                    game_title = t_str

            # 1. Search for .jar link in page
            jar_matches = re.findall(r'href=["\'](https?://[^"\']+\.jar[^"\']*)["\']', r.text)
            if jar_matches:
                return jar_matches[0], game_title

            # 2. Search for downloadwap link
            wap_matches = re.findall(r'href=["\'](https?://[^"\']*downloadwap\.com/[^"\']*)["\']', r.text)
            if wap_matches:
                return wap_matches[0], game_title
    except Exception as e:
        print(f"Error resolving Phoneky link: {e}")

    return phoneky_url, game_title

# ----------------- HOME STATUS ----------------- #
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "PocketVault Master Server Ready (2yxa, Logo Studio, Audio FX, Memes, Wallpapers, Java Leech)"})

# ----------------- 1. 2YXA MEDIA CONVERTER ----------------- #
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
            return jsonify({"success": True, "title": safe_title, "format": target_format.upper(), "size": f"{file_mb} MB", "download_url": f"{request.host_url.rstrip('/')}/download/{out_filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ----------------- 2. LOGO STUDIO V3 ----------------- #
@app.route("/logo", methods=["POST"])
def generate_logo():
    cleanup_old_files()
    text        = request.form.get("text", "LOGO").strip()[:25] or "LOGO"
    subtitle    = request.form.get("subtitle", "").strip()[:30]
    font_key    = request.form.get("font_family", "anton").lower()
    style       = request.form.get("style", "3d_chrome")
    icon_name   = request.form.get("icon", "none").lower()
    frame_style = request.form.get("frame", "none").lower()
    has_refl    = request.form.get("reflection", "no").lower() == "yes"
    bg_mode     = request.form.get("bg_mode", "transparent")
    canvas_mode = request.form.get("canvas_mode", "logo")
    photo_mode  = request.form.get("photo_mode", "none").lower()
    filter_mode = request.form.get("photo_filter", "none").lower()

    if font_key not in ["signature"]:
        text = text.upper()
        if subtitle: subtitle = subtitle.upper()

    user_img = None
    if "user_image" in request.files:
        uf = request.files["user_image"]
        if uf and uf.filename != '':
            try:
                user_img = Image.open(uf.stream).convert("RGBA")
                user_img = ImageOps.exif_transpose(user_img)
            except Exception:
                user_img = None

    if canvas_mode == "avatar" or photo_mode == "avatar_badge":
        width, height = 540, 540
        font_size = 38 if len(text) > 10 else 52
        sub_size = 14
    elif canvas_mode == "nokia":
        width, height = 240, 320
        font_size = 26 if len(text) > 10 else 36
        sub_size = 11
    elif canvas_mode == "android":
        width, height = 720, 1280
        font_size = 65 if len(text) > 10 else 90
        sub_size = 22
    else:
        width, height = 750, 380
        font_size = 56 if len(text) > 10 else 76
        sub_size = 16

    if user_img:
        if filter_mode == "bw": user_img = ImageOps.grayscale(user_img).convert("RGBA")
        elif filter_mode == "blur": user_img = user_img.filter(ImageFilter.GaussianBlur(radius=6))
        elif filter_mode == "contrast":
            user_img = ImageEnhance.Contrast(user_img).enhance(1.4)
            user_img = ImageEnhance.Color(user_img).enhance(1.3)

    if user_img and photo_mode in ["wallpaper_bg", "watermark"]:
        img = ImageOps.fit(user_img, (width, height), centering=(0.5, 0.5))
        if filter_mode == "dark" or photo_mode == "wallpaper_bg":
            overlay = Image.new("RGBA", (width, height), (15, 23, 42, 160))
            img = Image.alpha_composite(img, overlay)
    else:
        is_dark = (bg_mode == "black" or "neon" in style or style in ["fire", "ice", "toxic", "magenta", "blood", "sunset"])
        img = Image.new("RGBA", (width, height), (15, 23, 42, 255) if is_dark else ((255, 255, 255, 255) if bg_mode == "white" else (0, 0, 0, 0)))

    draw = ImageDraw.Draw(img)
    main_font = get_custom_font(font_key, font_size)
    sub_font = get_custom_font("orbitron" if font_key != "orbitron" else "anton", sub_size)

    accent_color = (250, 204, 21, 255) if ("gold" in style or style == "comic") else ((6, 182, 212, 255) if ("cyan" in style or style == "ice") else ((236, 72, 153, 255) if ("magenta" in style or style == "sunset") else ((239, 68, 68, 255) if ("blood" in style or style == "fire") else ((34, 197, 94, 255) if ("toxic" in style or style == "neon_green") else (241, 245, 249, 255)))))

    if user_img and photo_mode == "watermark":
        wbox = draw.textbbox((0, 0), text, font=main_font)
        ww, wh = wbox[2] - wbox[0], wbox[3] - wbox[1]
        wm_x, wm_y = width - ww - 25, height - wh - 25
        draw.text((wm_x + 2, wm_y + 2), text, font=main_font, fill=(0, 0, 0, 180))
        draw.text((wm_x, wm_y), text, font=main_font, fill=(255, 255, 255, 220))
        if subtitle: draw.text((wm_x, wm_y - sub_size - 4), subtitle, font=sub_font, fill=accent_color)
    else:
        curr_y = 20
        if user_img and photo_mode == "avatar_badge":
            avatar_size = 190 if canvas_mode == "avatar" else 150
            circle_avatar = make_circle_crop(user_img, avatar_size, border_color=accent_color, border_width=4)
            img.paste(circle_avatar, ((width - avatar_size) // 2, curr_y), circle_avatar)
            curr_y += avatar_size + 16
        else:
            bbox = draw.textbbox((0, 0), text, font=main_font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            total_block_h = th + (sub_size + 14 if subtitle else 0) + (38 if icon_name != "none" else 0)
            curr_y = (height - total_block_h) // 2
            if has_refl: curr_y = max(20, curr_y - 25)

        if icon_name != "none":
            draw_vector_icon(draw, icon_name, width // 2, curr_y + 12, 24, accent_color)
            curr_y += 34

        bbox = draw.textbbox((0, 0), text, font=main_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx, start_text_y = (width - tw) // 2, curr_y

        if style == "3d_chrome":
            for o in range(12, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(30, 41, 59, 255))
            draw.text((tx + 1, curr_y + 1), text, font=main_font, fill=(71, 85, 105, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(241, 245, 249, 255))
        elif style == "gold":
            for o in range(10, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(113, 63, 18, 255))
            draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(202, 138, 4, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(254, 240, 138, 255))
        elif style in ["neon_cyan", "neon_green", "magenta"]:
            nc = (6, 182, 212, 255) if style == "neon_cyan" else ((34, 197, 94, 255) if style == "neon_green" else (236, 72, 153, 255))
            glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            gdraw = ImageDraw.Draw(glow)
            for go in range(10, 0, -2): gdraw.text((tx, curr_y), text, font=main_font, fill=nc)
            glow = glow.filter(ImageFilter.GaussianBlur(radius=7))
            img = Image.alpha_composite(img, glow)
            draw = ImageDraw.Draw(img)
            draw.text((tx, curr_y), text, font=main_font, fill=(255, 255, 255, 255))
        elif style == "fire":
            for o in range(10, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(127, 29, 29, 255))
            draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(234, 88, 12, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(254, 240, 138, 255))
        elif style == "ice":
            for o in range(9, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(12, 74, 110, 255))
            draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(56, 189, 248, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(240, 249, 255, 255))
        elif style == "toxic":
            for o in range(8, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(20, 83, 45, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(74, 222, 128, 255), stroke_width=3, stroke_fill=(5, 46, 22, 255))
        elif style == "blood":
            for o in range(10, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(69, 10, 10, 255))
            draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(185, 28, 28, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(254, 202, 202, 255))
        elif style == "sunset":
            for o in range(10, 0, -1): draw.text((tx + o, curr_y + o), text, font=main_font, fill=(76, 29, 149, 255))
            draw.text((tx + 2, curr_y + 2), text, font=main_font, fill=(217, 70, 239, 255))
            draw.text((tx, curr_y), text, font=main_font, fill=(253, 186, 116, 255))
        elif style == "comic":
            draw.text((tx + 4, curr_y + 4), text, font=main_font, fill=(0, 0, 0, 180))
            draw.text((tx, curr_y), text, font=main_font, fill=(250, 204, 21, 255), stroke_width=4, stroke_fill=(15, 23, 42, 255))

        curr_y += th + 8
        if subtitle:
            sbox = draw.textbbox((0, 0), subtitle, font=sub_font)
            sw = sbox[2] - sbox[0]
            sx = (width - sw) // 2
            draw.rounded_rectangle((sx - 12, curr_y, sx + sw + 12, curr_y + sub_size + 8), radius=4, fill=(30, 41, 59, 220))
            draw.text((sx, curr_y + 3), subtitle, font=sub_font, fill=(148, 163, 184, 255))
            curr_y += sub_size + 14

        margin_w = min(tw + 70, width - 20)
        frame_x1, frame_x2 = (width - margin_w) // 2, (width - margin_w) // 2 + margin_w
        frame_y1, frame_y2 = max(10, start_text_y - 12), curr_y + 8

        if frame_style == "box": draw.rectangle((frame_x1, frame_y1, frame_x2, frame_y2), outline=accent_color, width=2)
        elif frame_style == "pill": draw.rounded_rectangle((frame_x1, frame_y1, frame_x2, frame_y2), radius=16, outline=accent_color, width=2)
        elif frame_style == "underline": draw.line((frame_x1 + 20, frame_y2, frame_x2 - 20, frame_y2), fill=accent_color, width=3)

        if has_refl and frame_y2 < height - 30 and photo_mode != "avatar_badge":
            crop_box = (frame_x1 - 10, start_text_y, frame_x2 + 10, min(curr_y, height - 10))
            cropped = img.crop(crop_box)
            flipped = ImageOps.flip(cropped)
            alpha_mask = Image.new("L", flipped.size, 0)
            for y_idx in range(flipped.height):
                alpha_val = int(100 * (1 - (y_idx / flipped.height)))
                for x_idx in range(flipped.width): alpha_mask.putpixel((x_idx, y_idx), alpha_val)
            flipped.putalpha(alpha_mask)
            img.paste(flipped, (crop_box[0], curr_y + 2), flipped)

    uid = str(uuid.uuid4())[:8]
    clean_name = "".join(c for c in text if c.isalnum()).lower()[:12] or "studio"
    out_filename = f"{clean_name}_{uid}.png"
    output_path = os.path.join(OUTPUT_DIR, out_filename)
    img.save(output_path, "PNG")

    return jsonify({"success": True, "title": text, "download_url": f"{request.host_url.rstrip('/')}/download/{out_filename}"})

# ----------------- 3. AUDIO EFFECTS & REMIXER STUDIO ----------------- #
@app.route("/audio_fx", methods=["POST"])
def audio_effects():
    cleanup_old_files()
    effect = request.form.get("effect", "nightcore").lower()
    url = request.form.get("url", "").strip()
    uid = str(uuid.uuid4())[:8]
    input_audio = None
    original_title = "remix"

    if url:
        yt_id = None
        patterns = [r'(?:v=|\/videos\/|embed\/|shorts\/|youtu\.be\/|\/v\/)([0-9A-Za-z_-]{11})', r'^([0-9A-Za-z_-]{11})$']
        for p in patterns:
            m = re.search(p, url)
            if m:
                yt_id = m.group(1)
                break

        if yt_id:
            input_audio = os.path.join(INPUT_DIR, f"{uid}_yt.mp4")
            for inst in ["https://inv.nadeko.net", "https://invidious.nerdvpn.de"]:
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
                                with open(input_audio, 'wb') as f:
                                    for ch in mr.iter_content(16384): f.write(ch)
                                original_title = data.get("title", "audio_remix")
                                break
                except Exception:
                    continue

        if not input_audio:
            ydl_opts = {'outtmpl': os.path.join(INPUT_DIR, f"{uid}_%(title)s.%(ext)s"), 'quiet': True}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    original_title = info.get('title', 'remix')
                    df = glob.glob(os.path.join(INPUT_DIR, f"{uid}_*"))
                    if df: input_audio = df[0]
            except Exception as e:
                return jsonify({"success": False, "error": f"Failed to download audio: {str(e)}"}), 400

    elif "audio_file" in request.files:
        f = request.files["audio_file"]
        if f.filename == '': return jsonify({"success": False, "error": "No audio file selected"}), 400
        ext = os.path.splitext(f.filename)[1] or ".mp3"
        original_title = os.path.splitext(f.filename)[0]
        input_audio = os.path.join(INPUT_DIR, f"{uid}{ext}")
        f.save(input_audio)
    else:
        return jsonify({"success": False, "error": "No audio provided"}), 400

    if not input_audio or not os.path.exists(input_audio):
        return jsonify({"success": False, "error": "Could not retrieve audio."}), 500

    out_filename = f"{original_title[:25]}_{effect}_{uid}.mp3"
    output_path = os.path.join(OUTPUT_DIR, out_filename)

    if effect == "nightcore":
        af_filter = "asetrate=44100*1.25,aresample=44100,atempo=1.03"
    elif effect == "slowed_reverb":
        af_filter = "asetrate=44100*0.83,aresample=44100,aecho=0.8:0.88:60:0.4"
    elif effect == "mega_bass":
        af_filter = "equalizer=f=60:width_type=o:width=2:g=15,equalizer=f=100:width_type=o:width=2:g=10"
    elif effect == "8d_audio":
        af_filter = "apulsator=mode=sine:hz=0.125"
    elif effect == "karaoke":
        af_filter = "pan=stereo|c0=c0-c1|c1=c1-c0"
    elif effect == "chipmunk":
        af_filter = "asetrate=44100*1.55,aresample=44100"
    else:
        af_filter = "volume=1.0"

    cmd = ["ffmpeg", "-y", "-i", input_audio, "-vn", "-af", af_filter, "-b:a", "128k", output_path]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            return jsonify({"success": False, "error": "Audio processing failed"}), 500

        size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
        if os.path.exists(input_audio): os.remove(input_audio)
        return jsonify({
            "success": True,
            "title": f"{original_title} ({effect.upper()})",
            "size": f"{size_mb} MB",
            "download_url": f"{request.host_url.rstrip('/')}/download/{out_filename}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ----------------- 4. MEME GENERATOR ----------------- #
@app.route("/meme", methods=["POST"])
def generate_meme():
    cleanup_old_files()
    top_text = request.form.get("top_text", "").strip().upper()
    bottom_text = request.form.get("bottom_text", "").strip().upper()
    meme_style = request.form.get("meme_style", "classic")

    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image uploaded"}), 400

    f = request.files["image"]
    try:
        img = Image.open(f.stream).convert("RGBA")
        img = ImageOps.exif_transpose(img)
    except Exception:
        return jsonify({"success": False, "error": "Invalid image file"}), 400

    w, h = img.size
    if w > 800:
        new_h = int(h * (800 / w))
        img = img.resize((800, new_h), Image.Resampling.LANCZOS)
        w, h = img.size

    font_size = max(24, int(w * 0.08))
    font = get_custom_font("anton", font_size)

    def draw_bordered_text(draw, txt, center_x, top_y):
        stroke_w = max(2, font_size // 14)
        bbox = draw.textbbox((0, 0), txt, font=font)
        tw = bbox[2] - bbox[0]
        tx = center_x - (tw // 2)
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                draw.text((tx + dx, top_y + dy), txt, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, top_y), txt, font=font, fill=(255, 255, 255, 255))

    if meme_style == "modern_card":
        banner_h = max(70, int(font_size * 2.2))
        final_img = Image.new("RGBA", (w, h + banner_h), (255, 255, 255, 255))
        final_img.paste(img, (0, banner_h))
        draw = ImageDraw.Draw(final_img)
        card_font = get_custom_font("modern", max(18, font_size - 10))
        caption = f"{top_text} {bottom_text}".strip()
        cbox = draw.textbbox((0, 0), caption, font=card_font)
        cw, ch = cbox[2] - cbox[0], cbox[3] - cbox[1]
        draw.text(((w - cw) // 2, (banner_h - ch) // 2), caption, font=card_font, fill=(15, 23, 42, 255))
    else:
        final_img = img
        draw = ImageDraw.Draw(final_img)
        if top_text:
            draw_bordered_text(draw, top_text, w // 2, 15)
        if bottom_text:
            bbox = draw.textbbox((0, 0), bottom_text, font=font)
            bh = bbox[3] - bbox[1]
            draw_bordered_text(draw, bottom_text, w // 2, h - bh - 20)

    uid = str(uuid.uuid4())[:8]
    out_filename = f"meme_{uid}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_filename)
    final_img.convert("RGB").save(out_path, "JPEG", quality=90)

    return jsonify({"success": True, "download_url": f"{request.host_url.rstrip('/')}/download/{out_filename}"})

# ----------------- 5. WALLPAPER RESIZER & FILTER ----------------- #
@app.route("/wallpaper", methods=["POST"])
def make_wallpaper():
    cleanup_old_files()
    preset = request.form.get("preset", "nokia_240").lower()
    fit_mode = request.form.get("fit_mode", "blur_bars")
    filter_style = request.form.get("filter", "none").lower()
    watermark = request.form.get("watermark", "").strip()

    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image uploaded"}), 400

    f = request.files["image"]
    try:
        img = Image.open(f.stream).convert("RGBA")
        img = ImageOps.exif_transpose(img)
    except Exception:
        return jsonify({"success": False, "error": "Invalid image"}), 400

    sizes = {
        "nokia_128": (128, 160),
        "nokia_176": (176, 220),
        "nokia_240": (240, 320),
        "nokia_e71": (320, 240),
        "android_720": (720, 1280),
        "android_1080": (1080, 1920),
        "android_tall": (1080, 2400)
    }
    tw, th = sizes.get(preset, (240, 320))

    if fit_mode == "crop_fill":
        canvas = ImageOps.fit(img, (tw, th), centering=(0.5, 0.5))
    else:
        bg = ImageOps.fit(img, (tw, th), centering=(0.5, 0.5))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=20))
        fg = img.copy()
        fg.thumbnail((tw, th), Image.Resampling.LANCZOS)
        fg_w, fg_h = fg.size
        canvas = bg
        canvas.paste(fg, ((tw - fg_w) // 2, (th - fg_h) // 2), fg)

    if filter_style == "bw":
        canvas = ImageOps.grayscale(canvas).convert("RGBA")
        canvas = ImageEnhance.Contrast(canvas).enhance(1.4)
    elif filter_style == "sepia":
        gray = ImageOps.grayscale(canvas)
        canvas = ImageOps.colorize(gray, "#2e1c0c", "#ffeedd").convert("RGBA")
    elif filter_style == "cyber":
        canvas = ImageEnhance.Contrast(canvas).enhance(1.3)
        canvas = ImageEnhance.Color(canvas).enhance(1.5)

    if watermark:
        draw = ImageDraw.Draw(canvas)
        font_sz = max(10, int(th * 0.025))
        w_font = get_custom_font("modern", font_sz)
        draw.text((10, th - font_sz - 12), watermark, font=w_font, fill=(255, 255, 255, 200))

    uid = str(uuid.uuid4())[:8]
    out_filename = f"wallpaper_{preset}_{uid}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_filename)
    canvas.convert("RGB").save(out_path, "JPEG", quality=92)

    return jsonify({"success": True, "download_url": f"{request.host_url.rstrip('/')}/download/{out_filename}"})

# ----------------- 6. JAVA (.JAR & .JAD) LEECH & DOWNLOAD ----------------- #
@app.route("/jar_fetch", methods=["POST"])
def fetch_jar():
    cleanup_old_files()
    input_url = request.form.get("url", "").strip()
    uid = str(uuid.uuid4())[:8]

    if not input_url:
        return jsonify({"success": False, "error": "No JAR or Phoneky link provided"}), 400

    # 1. Resolve Phoneky link using mobile session
    real_jar_url, page_title = resolve_phoneky_link(input_url)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Accept': '*/*',
        'Referer': 'https://mobile.phoneky.com/'
    }

    try:
        r = requests.get(real_jar_url, headers=headers, stream=True, timeout=45, allow_redirects=True)
        if r.status_code == 200:
            parsed_path = urllib.parse.urlparse(r.url).path
            raw_name = os.path.basename(parsed_path) or f"game_{uid}.jar"
            if not raw_name.endswith('.jar'):
                raw_name += ".jar"

            safe_name = "".join(c for c in raw_name if c.isalnum() or c in ('.', '_', '-'))
            out_jar_filename = f"{uid}_{safe_name}"
            out_jar_path = os.path.join(OUTPUT_DIR, out_jar_filename)

            with open(out_jar_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    f.write(chunk)

            file_size = os.path.getsize(out_jar_path)
            size_kb = round(file_size / 1024, 1)

            # Auto-generate paired .JAD descriptor for itel & Nokia native installer
            game_title = page_title if page_title else safe_name.replace('.jar', '')
            out_jad_filename = out_jar_filename.replace('.jar', '.jad')
            out_jad_path = os.path.join(OUTPUT_DIR, out_jad_filename)

            jar_download_url = f"{request.host_url.rstrip('/')}/download/{out_jar_filename}"

            jad_content = (
                f"MIDlet-Name: {game_title}\n"
                f"MIDlet-Version: 1.0.0\n"
                f"MIDlet-Vendor: PocketVault\n"
                f"MIDlet-Jar-URL: {jar_download_url}\n"
                f"MIDlet-Jar-Size: {file_size}\n"
            )
            with open(out_jad_path, 'w', encoding='utf-8') as jf:
                jf.write(jad_content)

            jad_download_url = f"{request.host_url.rstrip('/')}/download/{out_jad_filename}"

            return jsonify({
                "success": True,
                "title": game_title,
                "size": f"{size_kb} KB",
                "jar_url": jar_download_url,
                "jad_url": jad_download_url
            })
        else:
            return jsonify({"success": False, "error": f"Download server returned HTTP {r.status_code}"}), 400

    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to download JAR: {str(e)}"}), 500

# ----------------- DIRECT FILE DOWNLOAD (WITH PROPER MIME TYPES) ----------------- #
@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    mimetype = None
    if filename.endswith('.jar'):
        mimetype = "application/java-archive"
    elif filename.endswith('.jad'):
        mimetype = "text/vnd.sun.j2me.app-descriptor"
    elif filename.endswith('.3gp'):
        mimetype = "video/3gpp"
    elif filename.endswith('.mp4'):
        mimetype = "video/mp4"
    elif filename.endswith('.mp3'):
        mimetype = "audio/mpeg"
    elif filename.endswith('.png'):
        mimetype = "image/png"
    elif filename.endswith(('.jpg', '.jpeg')):
        mimetype = "image/jpeg"

    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True, mimetype=mimetype)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)