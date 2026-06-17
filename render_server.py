import json
import os
import posixpath
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import unquote, urlparse

import cv2


ROOT = os.path.dirname(os.path.abspath(__file__))
RESERVATION_PATH = os.path.join(ROOT, "utils/data/reservations.json")
COUNT_STATE = {
    "event": "render_demo",
    "total_enter": 30,
    "total_exit": 0,
    "current_inside": 30,
    "timestamp": "Render demo",
}
PARKING_STATE = {
    "total": 14,
    "parked": 3,
    "available": 11,
    "timestamp": "Render demo",
}
STREAMS = {}


class DemoVideoStream:
    def __init__(self, path, width=640, fps=15, quality=78):
        self.path = os.path.join(ROOT, path)
        self.width = width
        self.frame_delay = 1 / fps
        self.quality = quality
        self.latest_frame = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def get_frame(self):
        with self.lock:
            return self.latest_frame

    def run(self):
        while not self.stop_event.is_set():
            cap = cv2.VideoCapture(self.path)
            if not cap.isOpened():
                time.sleep(1)
                continue

            while not self.stop_event.is_set():
                started_at = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue

                height, width = frame.shape[:2]
                if width > self.width:
                    target_height = int(height * (self.width / width))
                    frame = cv2.resize(frame, (self.width, target_height))

                ok, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), self.quality],
                )
                if ok:
                    with self.lock:
                        self.latest_frame = encoded.tobytes()

                elapsed = time.monotonic() - started_at
                time.sleep(max(0.001, self.frame_delay - elapsed))

            cap.release()


class RenderTCPServer(ThreadingTCPServer):
    allow_reuse_address = True


class RenderHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        path = urlparse(self.path).path
        self.serve_static_file(path, head_only=True)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/video_feed":
            self.stream_video(STREAMS["people"])
            return
        if path == "/parking_feed":
            self.stream_video(STREAMS["parking"])
            return
        if path == "/reservations":
            self.serve_reservations()
            return
        if path == "/utils/data/count_state.json":
            self.send_json(COUNT_STATE)
            return
        if path == "/utils/data/parking_state.json":
            self.send_json(PARKING_STATE)
            return
        self.serve_static_file(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/reservations":
            self.handle_reservation()
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

    def send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def read_reservations(self):
        try:
            with open(RESERVATION_PATH, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {}

    def write_reservations(self, data):
        os.makedirs(os.path.dirname(RESERVATION_PATH), exist_ok=True)
        with open(RESERVATION_PATH, "w", encoding="utf-8") as file:
            json.dump(data, file)

    def serve_reservations(self):
        self.send_json(self.read_reservations())

    def handle_reservation(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}

        time_key = body.get("time")
        action = body.get("action")
        data = self.read_reservations()

        if time_key and action == "add":
            data[time_key] = data.get(time_key, 0) + 1
        elif time_key and action == "remove":
            data.pop(time_key, None)

        self.write_reservations(data)
        self.send_json(data)

    def stream_video(self, stream):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_cors_headers()
        self.end_headers()

        while True:
            frame = stream.get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            try:
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(stream.frame_delay)
            except (BrokenPipeError, ConnectionResetError):
                break

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


def main():
    STREAMS["people"] = DemoVideoStream("utils/data/tests/test_1.mp4", width=640, fps=15)
    STREAMS["parking"] = DemoVideoStream("utils/data/tests/test_2.mp4", width=640, fps=15)

    for stream in STREAMS.values():
        stream.start()

    def shutdown(*_):
        for stream in STREAMS.values():
            stream.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    port = int(os.environ.get("PORT", "10000"))
    server = RenderTCPServer(("0.0.0.0", port), RenderHandler)
    print(f"[INFO] Render demo server listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
