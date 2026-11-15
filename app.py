import os
import re
import io
import json
import time
import zipfile
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, quote

import requests
from flask import Flask, render_template, request, jsonify, Response, send_file
import tempfile
import yt_dlp
from pathlib import Path

app = Flask(__name__)
HEADERS = {"User-Agent": "SOLA-DOWNLOAD/1.0 (Scratch project downloader)"}
CACHE = {}
CACHE_LOCK = threading.Lock()
CACHE_TTL = 300
MAX_ASSETS = 1000
MAX_ASSET_BYTES = 30 * 1024 * 1024

def fetch(url, timeout=20):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r

def project_id(url):
    if not isinstance(url, str):
        return None
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https") or p.hostname not in ("scratch.mit.edu", "www.scratch.mit.edu"):
        return None
    m = re.fullmatch(r"/projects/(\d+)/?", p.path)
    return m.group(1) if m else None

def metadata(pid):
    now = time.monotonic()
    with CACHE_LOCK:
        cached = CACHE.get(pid)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]
    r = fetch(f"https://api.scratch.mit.edu/projects/{pid}", 15)
    data = r.json()
    if not data.get("is_published", True):
        raise PermissionError("非公開作品はダウンロードできないよ。")
    with CACHE_LOCK:
        if len(CACHE) > 250:
            CACHE.clear()
        CACHE[pid] = (time.monotonic(), data)
    return data

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.post("/api/info")
def info():
    pid = project_id((request.get_json(silent=True) or {}).get("url", ""))
    if not pid:
        return jsonify(error="Scratchの作品URLを入力してね。例：https://scratch.mit.edu/projects/123456789/"), 400
    try:
        data = metadata(pid)
        return jsonify(id=pid, title=data.get("title") or f"Scratch-{pid}", author=(data.get("author") or {}).get("username", "不明"), thumbnail=(data.get("images") or {}).get("282x218", ""))
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify(error="作品が見つからないよ。公開されているか確認してね。"), 404
        return jsonify(error="Scratchの作品情報を取得できなかったよ。再試行してね。"), 502
    except (requests.RequestException, ValueError, TypeError):
        return jsonify(error="Scratchの作品情報を取得できなかったよ。再試行してね。"), 502

def get_asset(name):
    r = fetch(f"https://assets.scratch.mit.edu/internalapi/asset/{name}/get/", 25)
    if len(r.content) > MAX_ASSET_BYTES:
        raise ValueError("素材が大きすぎるよ。")
    return name, r.content

@app.get("/api/download/<pid>")
def download(pid):
    if not pid.isdigit():
        return jsonify(error="無効な作品IDだよ。"), 400
    try:
        md = metadata(pid)
        token = md.get("project_token") or ""
        url = f"https://projects.scratch.mit.edu/{pid}"
        if token:
            url += f"?token={quote(str(token))}"
        data = fetch(url, 45).content
        project = json.loads(data)
        assets = set()
        for target in project.get("targets", []):
            for item in target.get("costumes", []) + target.get("sounds", []):
                name = item.get("md5ext")
                if name and re.fullmatch(r"[0-9a-fA-F]{32}\.[A-Za-z0-9]+", name):
                    assets.add(name)
        if len(assets) > MAX_ASSETS:
            raise ValueError("素材の数が多すぎるよ。")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr("project.json", data)
            with ThreadPoolExecutor(max_workers=8) as pool:
                for name, content in pool.map(get_asset, sorted(assets)):
                    z.writestr(name, content)
        title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", md.get("title") or f"Scratch-{pid}").strip(" .")[:100] or f"Scratch-{pid}"
        payload = buf.getvalue()
        return Response(payload, headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(title + '.sb3')}",
            "Content-Length": str(len(payload)),
            "Cache-Control": "no-store"
        })
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify(error="作品または素材が見つからなかったよ。"), 404
        return jsonify(error="Scratchからの取得に失敗したよ。少し待って再試行してね。"), 502
    except (requests.RequestException, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        return jsonify(error="作品ファイルを作成できなかったよ。Scratch側の制限や一時的な通信障害の可能性があるよ。"), 502

VIDEO_HOSTS = {
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"},
    "niconico": {"nicovideo.jp", "www.nicovideo.jp", "nico.ms"}
}
MAX_VIDEO_BYTES = 250 * 1024 * 1024

def video_url(url, service):
    if service not in VIDEO_HOSTS or not isinstance(url, str):
        raise ValueError("対応していないサービスだよ。")
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname not in VIDEO_HOSTS[service]:
        raise ValueError("正しい動画URLを入力してね。")
    if service == "youtube" and not (
        re.fullmatch(r"/watch", parsed.path) and "v=" in parsed.query
        or re.fullmatch(r"/shorts/[A-Za-z0-9_-]+/?", parsed.path)
        or parsed.hostname == "youtu.be" and re.fullmatch(r"/[A-Za-z0-9_-]+/?", parsed.path)
    ):
        raise ValueError("YouTubeの動画URLを入力してね。")
    if service == "niconico" and not (
        re.fullmatch(r"/watch/(?:sm|nm|so)\d+/?", parsed.path)
        or parsed.hostname == "nico.ms" and re.fullmatch(r"/(?:sm|nm|so)\d+/?", parsed.path)
    ):
        raise ValueError("ニコニコ動画のURLを入力してね。")
    return parsed.geturl()

def video_opts():
    return {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "ignoreerrors": False, "skip_download": True,
        "socket_timeout": 18, "retries": 1,
        "extractor_retries": 1,
        "format": "best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]",
    }

@app.post("/api/video/info")
def video_info():
    payload = request.get_json(silent=True) or {}
    try:
        service = payload.get("service")
        url = video_url(payload.get("url", ""), service)
        with yt_dlp.YoutubeDL(video_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return jsonify(error="ライブ配信には対応していないよ。"), 400
        return jsonify(
            title=info.get("title") or "動画",
            author=info.get("uploader") or "不明",
            thumbnail=info.get("thumbnail") or "",
            duration=info.get("duration"),
            service=service,
            url=url
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except yt_dlp.utils.DownloadError as e:
        app.logger.warning("Video info extractor failed for %s: %s", service, str(e)[:1200])
        return jsonify(error="動画情報を取得できなかったよ。RenderのLogsで「Video info extractor failed」を確認してね。"), 502
    except Exception:
        app.logger.exception("Video info failed")
        return jsonify(error="動画情報を取得できなかったよ。"), 502

@app.post("/api/video/download")
def video_download():
    payload = request.get_json(silent=True) or {}
    try:
        url = video_url(payload.get("url", ""), payload.get("service"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        with tempfile.TemporaryDirectory() as temp:
            options = video_opts()
            options.update({
                "skip_download": False,
                "outtmpl": str(Path(temp) / "%(id)s.%(ext)s"),
                "max_filesize": MAX_VIDEO_BYTES,
                "overwrites": False,
                "nopart": True,
            })
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info or info.get("is_live"):
                    return jsonify(error="この動画はダウンロードできないよ。"), 400
            files = [p for p in Path(temp).iterdir() if p.is_file() and p.suffix.lower() in (".mp4", ".webm", ".mkv")]
            if not files:
                return jsonify(error="対応形式の動画ファイルを取得できなかったよ。"), 502
            file = max(files, key=lambda p: p.stat().st_size)
            if file.stat().st_size > MAX_VIDEO_BYTES:
                return jsonify(error="250MB以下の動画に対応しているよ。"), 413
            title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", info.get("title") or "video").strip(" .")[:100] or "video"
            content = file.read_bytes()
            return send_file(io.BytesIO(content), mimetype="application/octet-stream", as_attachment=True,
                             download_name=title + file.suffix)
    except yt_dlp.utils.DownloadError as e:
        app.logger.warning("Video download extractor failed: %s", str(e)[:1200])
        return jsonify(error="動画を取得できなかったよ。RenderのLogsで「Video download extractor failed」を確認してね。"), 502
    except Exception:
        app.logger.exception("Video download failed")
        return jsonify(error="動画のダウンロードに失敗したよ。"), 502

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
