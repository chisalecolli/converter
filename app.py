import os
import subprocess
import uuid
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)
UPLOAD_DIR = "/tmp/converter"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "PocketVault Converter is running!"})

@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files["file"]
    target_format = request.form.get("format", "mp3").lower()
    resolution = request.form.get("resolution", "176x144")

    # Generate unique filenames
    uid = str(uuid.uuid4())[:8]
    input_ext = os.path.splitext(uploaded_file.filename)[1] or ".tmp"
    input_path = os.path.join(UPLOAD_DIR, f"in_{uid}{input_ext}")
    output_path = os.path.join(UPLOAD_DIR, f"out_{uid}.{target_format}")

    uploaded_file.save(input_path)

    # Build the FFmpeg command
    if target_format == "mp3":
        # Extract MP3 Audio
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            output_path
        ]
    elif target_format == "3gp":
        # Classic 2yxa 3GP for Button/Java phones (H.263 + AMR audio)
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-s", resolution, "-r", "15", "-b:v", "100k",
            "-c:a", "amr_nb", "-ar", "8000", "-ac", "1",
            output_path
        ]
    elif target_format == "mp4":
        # Low data MP4 for Android
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={resolution}", "-c:v", "libx264", "-crf", "28",
            "-c:a", "aac", "-b:a", "64k", "-preset", "veryfast",
            output_path
        ]
    else:
        return jsonify({"error": "Unsupported format"}), 400

    try:
        # Run conversion
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        if os.path.exists(output_path):
            return send_file(output_path, as_attachment=True, download_name=f"converted_{uid}.{target_format}")
        else:
            return jsonify({"error": "Output file not found"}), 500
    except subprocess.CalledProcessError as e:
        return jsonify({"error": "FFmpeg conversion failed", "details": e.stderr.decode()}), 500
    finally:
        # Clean up temporary input file to save space
        if os.path.exists(input_path):
            os.remove(input_path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
