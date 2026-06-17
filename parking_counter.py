"""
parking_counter.py - 주차장 점유 감지 시스템 (웹 실시간 스트림 버전)
방식: MobileNet SSD 차량 감지 + 주차 구역 점유 카운팅
      (멈춰 있는 차도 감지하므로 "현재 주차/빈자리"를 정확히 측정)
- 처리된 프레임을 MJPEG(/video_feed)로 실시간 스트리밍 (기본 포트 8002)
- 주차 현황은 utils/data/parking_state.json 에 기록 → 웹(bus.html)이 폴링
- 한글 렌더링: PIL (Windows 맑은 고딕 / Linux 나눔 / macOS 자동 탐색)
"""
import cv2, numpy as np, time, datetime, json, os, argparse, threading, sys
from collections import deque
from PIL import Image, ImageDraw, ImageFont
import socketserver
from http.server import BaseHTTPRequestHandler

W, H = 960, 540

# ── 파라미터 (영상에 맞춰 조정) ───────────────────────
TOTAL_SLOTS = 14          # 주차 총 면수
# 주차 구역: 감지된 차량의 "중심점"이 이 사각형 안에 있으면 주차로 간주.
# (앞쪽 주행로 / 상단 배경의 차는 자동 제외 → 960x540 기준 좌표)
ZONE_X1, ZONE_X2 = 95, 905
ZONE_Y1, ZONE_Y2 = 195, 340
SKIP = 4                  # 감지 간격 (프레임)
CONFIDENCE = 0.35         # SSD 최소 신뢰도
SMOOTH_WINDOW = 15        # 점유 수 평활(최근 감지 사이클 중앙값) 윈도우

PARKING_STATE_PATH = "utils/data/parking_state.json"
CLASSES = ["background","aeroplane","bicycle","bird","boat","bottle","bus","car",
           "cat","chair","cow","diningtable","dog","horse","motorbike","person",
           "pottedplant","sheep","sofa","train","tvmonitor"]
VEHICLE_CLASSES = {"car", "bus"}


# ── 한글 폰트 경로 자동 탐색 (OS별) ──────────────────
def _find_font():
    candidates = [
        "C:/Windows/Fonts/malgunbd.ttf",                          # Windows 맑은 고딕 Bold
        "C:/Windows/Fonts/malgun.ttf",                            # Windows 맑은 고딕
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",    # Linux 나눔
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",             # macOS
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

FONT_PATH = _find_font()


def load_fonts():
    fonts = {}
    for name, size in [('title',16), ('label',14), ('val',32), ('small',12), ('mid',18)]:
        try:
            if FONT_PATH is None:
                raise IOError
            fonts[name] = ImageFont.truetype(FONT_PATH, size)
        except IOError:
            fonts[name] = ImageFont.load_default()
    return fonts

FONTS = load_fonts()

def put_kr(frame, text, pos, font_key='label', color=(255,255,255)):
    """OpenCV frame에 한글 텍스트를 PIL로 렌더링"""
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    draw.text(pos, text, font=FONTS[font_key], fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


# ── 웹 스트리밍 서버 (MJPEG) ─────────────────────────
latest_frame = None
latest_frame_lock = threading.Lock()
WEB_JPEG_QUALITY = 75


def update_web_frame(frame):
    global latest_frame
    success, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), WEB_JPEG_QUALITY]
    )
    if not success:
        return
    with latest_frame_lock:
        latest_frame = encoded.tobytes()


class StreamingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/video_feed":
            self.stream_video()
            return
        self.send_response(404)
        self.end_headers()

    def stream_video(self):
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            with latest_frame_lock:
                frame = latest_frame
            if frame is None:
                time.sleep(0.1)
                continue
            try:
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                break

    def log_message(self, format, *args):
        return


def start_web_stream_server(port):
    def run_server():
        try:
            server = StreamingServer(("", port), StreamingHandler)
            print(f"[INFO] 주차장 영상 스트림: http://localhost:{port}/video_feed")
            server.serve_forever()
        except OSError as error:
            print(f"[WARN] 스트림 서버 시작 실패: {error}")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()


def write_parking_state(total, parked, available):
    payload = {
        "total": total,
        "parked": parked,
        "available": available,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(os.path.dirname(PARKING_STATE_PATH), exist_ok=True)
    with open(PARKING_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


# ── 차량 감지 ─────────────────────────────────────────
def detect_vehicles(net, frame, confidence):
    """프레임에서 차량 박스 목록 반환: [(cx, cy, x1, y1, x2, y2), ...]"""
    blob = cv2.dnn.blobFromImage(frame, 0.007843, (W, H), 127.5)
    net.setInput(blob)
    detections = net.forward()
    cars = []
    for i in range(detections.shape[2]):
        conf = detections[0, 0, i, 2]
        if conf <= confidence:
            continue
        label = CLASSES[int(detections[0, 0, i, 1])]
        if label not in VEHICLE_CLASSES:
            continue
        x1, y1, x2, y2 = (detections[0, 0, i, 3:7] * np.array([W, H, W, H])).astype(int)
        cars.append(((x1 + x2) // 2, (y1 + y2) // 2, x1, y1, x2, y2))
    return cars


def in_zone(cx, cy):
    return ZONE_X1 <= cx <= ZONE_X2 and ZONE_Y1 <= cy <= ZONE_Y2


# ── 정보 패널 ─────────────────────────────────────────
def draw_panel(frame, total, parked, available):
    ph = 80
    ov = frame.copy()
    cv2.rectangle(ov, (0,0), (W, ph), (15,15,15), -1)
    cv2.addWeighted(ov, 0.75, frame, 0.25, 0, frame)

    cv2.putText(frame, "PARKING MANAGEMENT SYSTEM",
                (10, 20), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255,220,60), 1)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    cv2.putText(frame, ts, (W-80, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190,190,190), 1)

    blocks = [
        ("전체 주차면", f"{total}",     (210,210,210)),
        ("현재 주차",  f"{parked}",    (80,200,255)),
        ("빈  자  리", f"{available}", (80,255,80) if available > 0 else (60,60,255)),
    ]
    bw = W // 3
    for i, (label, val, color) in enumerate(blocks):
        bx = i * bw
        frame = put_kr(frame, label, (bx+10, 30), 'label', (170,170,170))
        cv2.putText(frame, val, (bx+bw//2-20, 72),
                    cv2.FONT_HERSHEY_DUPLEX, 1.2, color, 2)

    for i in range(1,3):
        cv2.line(frame, (bw*i, 28), (bw*i, ph-5), (80,80,80), 1)

    occ = int(round(parked / total * 100)) if total else 0
    frame = put_kr(frame, f"점유율: {occ}%", (W-150, H-26), 'label', (220,220,220))

    if available == 0 and int(time.time()*2) % 2 == 0:
        cv2.rectangle(frame, (0,0), (W, ph), (0,0,200), 4)
        frame = put_kr(frame, "!! 만  차 !!", (W//2-60, ph-25), 'mid', (0,0,255))

    return frame


def draw_overlay(frame, cars, parked, available):
    # 주차 구역 외곽선
    cv2.rectangle(frame, (ZONE_X1, ZONE_Y1), (ZONE_X2, ZONE_Y2), (0,200,200), 1)
    frame_local = frame
    # 차량 박스: 구역 안(주차)=초록, 밖(주행/배경)=회색
    for (cx, cy, x1, y1, x2, y2) in cars:
        parked_car = in_zone(cx, cy)
        col = (80, 230, 80) if parked_car else (120, 120, 120)
        cv2.rectangle(frame_local, (x1, y1), (x2, y2), col, 2)
        cv2.circle(frame_local, (cx, cy), 3, col, -1)
    frame_local = draw_panel(frame_local, TOTAL_SLOTS, parked, available)
    return frame_local


# ── 인자 파싱 ─────────────────────────────────────────
def parse_arguments():
    ap = argparse.ArgumentParser(description="주차장 점유 감지 (웹 실시간 스트림)")
    ap.add_argument("-i", "--input", type=str,
                    default="utils/data/tests/parking_test.mp4",
                    help="입력 영상 경로 (기본: utils/data/tests/parking_test.mp4)")
    ap.add_argument("-p", "--prototxt", type=str,
                    default="detector/MobileNetSSD_deploy.prototxt",
                    help="Caffe prototxt 경로")
    ap.add_argument("-m", "--model", type=str,
                    default="detector/MobileNetSSD_deploy.caffemodel",
                    help="Caffe 모델 경로")
    ap.add_argument("--total", type=int, default=TOTAL_SLOTS,
                    help=f"주차 총 면수 (기본: {TOTAL_SLOTS})")
    ap.add_argument("-c", "--confidence", type=float, default=CONFIDENCE,
                    help=f"SSD 최소 신뢰도 (기본: {CONFIDENCE})")
    ap.add_argument("-s", "--skip-frames", type=int, default=SKIP,
                    help=f"감지 간격 프레임 수 (기본: {SKIP})")
    ap.add_argument("--jpeg-quality", type=int, default=75,
                    help="웹 MJPEG 스트림 JPEG 품질 (기본: 75)")
    ap.add_argument("--analysis-interval", type=float, default=0,
                    help="DNN 감지 실행 간격(초). 0이면 skip-frames 기준 사용")
    ap.add_argument("--port", type=int, default=8002,
                    help="MJPEG 스트림 서버 포트 (기본: 8002)")
    ap.add_argument("--window", action="store_true",
                    help="OpenCV 미리보기 창을 띄움")
    ap.add_argument("--no-window", action="store_true",
                    help="deprecated; 웹 화면만 띄우는 것이 기본값")
    ap.add_argument("--no-loop", action="store_true",
                    help="영상 끝에서 반복 재생하지 않고 종료")
    return vars(ap.parse_args())


# ── 메인 ─────────────────────────────────────────────
def main():
    global WEB_JPEG_QUALITY
    global TOTAL_SLOTS
    args = parse_arguments()
    TOTAL_SLOTS = args["total"]
    args["skip_frames"] = max(1, args["skip_frames"])
    args["analysis_interval"] = max(0, args["analysis_interval"])
    WEB_JPEG_QUALITY = max(35, min(95, args["jpeg_quality"]))
    INPUT = args["input"]

    if not os.path.isfile(INPUT):
        print(f"[ERROR] 입력 영상을 찾을 수 없습니다: {INPUT}")
        print("        테스트 영상을 해당 경로에 넣거나 --input 으로 경로를 지정하세요.")
        sys.exit(1)

    net = cv2.dnn.readNetFromCaffe(args["prototxt"], args["model"])
    start_web_stream_server(args["port"])

    cap = cv2.VideoCapture(INPUT)
    counts = deque(maxlen=SMOOTH_WINDOW)
    last_cars = []
    parked = 0
    tf_count = 0
    last_analysis_at = 0
    has_analysis_result = False

    write_parking_state(TOTAL_SLOTS, 0, TOTAL_SLOTS)
    print(f"[INFO] 처리 시작 (구역 x[{ZONE_X1},{ZONE_X2}] y[{ZONE_Y1},{ZONE_Y2}], 총 {TOTAL_SLOTS}면)")
    if args["window"] and not args["no_window"]:
        print("[INFO] 종료하려면 미리보기 창에서 q 를 누르세요.")
    else:
        print("[INFO] 웹 화면으로만 실행 중입니다. 미리보기 창은 --window 옵션으로 켤 수 있습니다.")

    while True:
        ret, frame_orig = cap.read()
        if not ret:
            if args["no_loop"]:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            last_analysis_at = 0
            has_analysis_result = False
            continue

        frame = cv2.resize(frame_orig, (W, H))

        # 지정한 간격마다 감지 → 점유 수 평활
        now_monotonic = time.monotonic()
        if args["analysis_interval"] > 0:
            should_detect = (
                not has_analysis_result or
                now_monotonic - last_analysis_at >= args["analysis_interval"]
            )
        else:
            should_detect = tf_count % args["skip_frames"] == 0

        if should_detect:
            last_cars = detect_vehicles(net, frame, args["confidence"])
            raw_parked = sum(1 for (cx, cy, *_) in last_cars if in_zone(cx, cy))
            counts.append(raw_parked)
            parked = int(round(float(np.median(counts))))
            parked = max(0, min(parked, TOTAL_SLOTS))
            # 점유 수가 바뀔 때마다 현황 기록 → 웹 카드가 영상에 그려진 값과 항상 일치
            write_parking_state(TOTAL_SLOTS, parked, max(TOTAL_SLOTS - parked, 0))
            last_analysis_at = now_monotonic
            has_analysis_result = True

        available = max(TOTAL_SLOTS - parked, 0)

        frame = draw_overlay(frame, last_cars, parked, available)
        update_web_frame(frame)

        if args["window"] and not args["no_window"]:
            cv2.imshow("Parking Management System", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break

        tf_count += 1

    cap.release()
    if args["window"] and not args["no_window"]:
        cv2.destroyAllWindows()
    write_parking_state(TOTAL_SLOTS, parked, max(TOTAL_SLOTS - parked, 0))

    print(f"\n{'='*52}")
    print(f"  처리 종료  |  최종 주차: {parked}/{TOTAL_SLOTS}  빈자리: {max(TOTAL_SLOTS-parked,0)}")
    print(f"{'='*52}")


if __name__ == "__main__":
    main()
