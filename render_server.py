import os
import posixpath
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import unquote, urlparse


ROOT = os.path.dirname(os.path.abspath(__file__))
PEOPLE_URL = "http://127.0.0.1:8001"
PARKING_URL = "http://127.0.0.1:8002"
CHUNK_SIZE = 64 * 1024


def start_process(command):
    return subprocess.Popen(command, cwd=ROOT)


def start_workers():
    python = sys.executable
    workers = [
        start_process([
            python, "people_counter.py",
            "--prototxt", "detector/MobileNetSSD_deploy.prototxt",
            "--model", "detector/MobileNetSSD_deploy.caffemodel",
            "--input", "utils/data/tests/test_1.mp4",
        ]),
        start_process([
            python, "parking_counter.py",
            "--input", "utils/data/tests/test_2.mp4",
            "--prototxt", "detector/MobileNetSSD_deploy.prototxt",
            "--model", "detector/MobileNetSSD_deploy.caffemodel",
            "--port", "8002",
        ]),
    ]
    return workers


class RenderHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        path = urlparse(self.path).path
        self.serve_static_file(path, head_only=True)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/video_feed":
            self.proxy_stream(f"{PEOPLE_URL}/video_feed")
            return
        if path == "/parking_feed":
            self.proxy_stream(f"{PARKING_URL}/video_feed")
            return
        if path == "/reservations":
            self.proxy_request(f"{PEOPLE_URL}/reservations")
            return
        self.serve_static_file(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/reservations":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.proxy_request(f"{PEOPLE_URL}/reservations", data=body)
            return
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def proxy_request(self, target_url, data=None):
        headers = {}
        if data is not None:
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
        request = urllib.request.Request(target_url, data=data, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-cache")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.URLError:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error":"upstream unavailable"}')

    def proxy_stream(self, target_url):
        try:
            with urllib.request.urlopen(target_url, timeout=15) as response:
                self.send_response(200)
                self.send_header("Content-Type", response.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=frame"))
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Pragma", "no-cache")
                self.send_cors_headers()
                self.end_headers()
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (urllib.error.URLError, BrokenPipeError, ConnectionResetError):
            return

    def serve_static_file(self, path, head_only=False):
        if path == "/":
            path = "/bus.html"

        relative_path = posixpath.normpath(unquote(path)).lstrip("/")
        file_path = os.path.abspath(os.path.join(ROOT, relative_path))

        if not file_path.startswith(ROOT) or not os.path.isfile(file_path):
            self.send_response(404)
            self.end_headers()
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".mp4": "video/mp4",
        }
        extension = os.path.splitext(file_path)[1].lower()

        self.send_response(200)
        self.send_header("Content-Type", content_types.get(extension, "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        if head_only:
            return

        with open(file_path, "rb") as file:
            self.wfile.write(file.read())

    def log_message(self, format, *args):
        return


def wait_for_workers():
    for url in (f"{PEOPLE_URL}/video_feed", f"{PARKING_URL}/video_feed"):
        for _ in range(30):
            try:
                request = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(request, timeout=1):
                    break
            except Exception:
                time.sleep(1)


def main():
    workers = start_workers()

    def shutdown(*_):
        for worker in workers:
            worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    threading.Thread(target=wait_for_workers, daemon=True).start()
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingTCPServer(("0.0.0.0", port), RenderHandler)
    print(f"[INFO] Render server listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
