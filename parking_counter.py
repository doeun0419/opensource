"""
parking_counter.py - 주차장 입출차 카운팅 시스템 (최종 완성본)
MOG2 배경차분 + CentroidTracker (버그 수정 및 로직 접합 완료)
한글 렌더링: PIL + NanumGothic
"""
import cv2, numpy as np, time, sys, datetime, subprocess, json, os
from PIL import Image, ImageDraw, ImageFont

INPUT  = 'parking_input.mp4'
OUTPUT = 'parking_output.mp4'

# ── 파라미터 ──────────────────────────────────────────
TOTAL        = 14      # 주차 총 면수
LINE_TOP     = 215     # 상단 감지선 Y (960x540 기준)
LINE_BOT     = 315     # 하단 감지선 Y
SKIP         = 4       # 감지 간격 (프레임)
BAND         = 18      # 감지선 ±허용 폭 (px)
MIN_A        = 1000    # 컨투어 최소 넓이 (px²)
MAX_A        = 30000   # 컨투어 최대 넓이
ROI_Y1       = 170     # 처리 ROI 상단
ROI_Y2       = 380     # 처리 ROI 하단
INIT_PARKED  = 8       # 시작 시 주차 차량 수 (초기값)
FONT_PATH    = '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'
W, H         = 960, 540


# ── CentroidTracker (기존 로직 유지) ──────────────────
class CentroidTracker:
    def __init__(self, max_disappeared=50, max_distance=65):
        self.next_id = 0
        self.objects = {}
        self.disappeared = {}
        self.max_d = max_disappeared
        self.max_dist = max_distance

    def register(self, c):
        self.objects[self.next_id] = c
        self.disappeared[self.next_id] = 0
        self.next_id += 1

    def deregister(self, oid):
        del self.objects[oid]
        del self.disappeared[oid]

    def update(self, rects):
        if not rects:
            for oid in list(self.disappeared):
                self.disappeared[oid] += 1
                if self.disappeared[oid] > self.max_d:
                    self.deregister(oid)
            return self.objects
        inp = np.array([((r[0]+r[2])//2, (r[1]+r[3])//2) for r in rects], dtype=float)
        if not self.objects:
            for c in inp: self.register(c)
        else:
            oids = list(self.objects.keys())
            obj  = np.array(list(self.objects.values()), dtype=float)
            D    = np.linalg.norm(obj[:, None] - inp[None], axis=2)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            ur, uc = set(), set()
            for r, c in zip(rows, cols):
                if r in ur or c in uc or D[r, c] > self.max_dist: continue
                oid = oids[r]
                self.objects[oid] = inp[c]
                self.disappeared[oid] = 0
                ur.add(r); uc.add(c)
            for r in set(range(D.shape[0])) - ur:
                self.disappeared[oids[r]] += 1
                if self.disappeared[oids[r]] > self.max_d:
                    self.deregister(oids[r])
            for c in set(range(D.shape[1])) - uc:
                self.register(inp[c])
        return self.objects


# ── TrackableVehicle (counted 플래그 접합) ───────────
class TrackableVehicle:
    def __init__(self, oid, c):
        self.id = oid
        self.centroids = [c]
        self.counted = False  # 락(Lock) 메커니즘을 위한 중복 카운트 방지 플래그


# ── 한글 텍스트 렌더링 ───────────────────────────────
def load_fonts():
    fonts = {}
    for name, size in [('title',16), ('label',14), ('val',32), ('small',12), ('mid',18)]:
        try:
            fonts[name] = ImageFont.truetype(FONT_PATH, size)
        except IOError:
            fonts[name] = ImageFont.load_default() # 폰트 유실 대비 예외 처리
    return fonts

FONTS = load_fonts()

def put_kr(frame, text, pos, font_key='label', color=(255,255,255)):
    """OpenCV frame에 한글 텍스트를 PIL로 렌더링"""
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    draw.text(pos, text, font=FONTS[font_key], fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


# ── 점선 그리기 ──────────────────────────────────────
def draw_dashed(frame, pt1, pt2, color, thick=2, dash=15, gap=7):
    x1,y1 = pt1; x2,y2 = pt2
    L = np.hypot(x2-x1, y2-y1)
    if L == 0: return
    dx = (x2-x1)/L; dy = (y2-y1)/L; pos = 0
    while pos < L:
        xs = int(x1+dx*pos); ys = int(y1+dy*pos)
        xe = int(x1+dx*min(pos+dash, L)); ye = int(y1+dy*min(pos+dash, L))
        cv2.line(frame, (xs,ys), (xe,ye), color, thick)
        pos += dash + gap


# ── 정보 패널 ─────────────────────────────────────────
def draw_panel(frame, total, parked, available, te, tx):
    ph = 80
    ov = frame.copy()
    cv2.rectangle(ov, (0,0), (W, ph), (15,15,15), -1)
    cv2.addWeighted(ov, 0.75, frame, 0.25, 0, frame)

    # 타이틀 & 시각 (영어 → cv2)
    cv2.putText(frame, "PARKING MANAGEMENT SYSTEM",
                (10, 20), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255,220,60), 1)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    cv2.putText(frame, ts, (W-80, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190,190,190), 1)

    # 3개 블록: 한글 라벨 + 숫자
    blocks = [
        ("전체 주차면", f"{total}",     (210,210,210)),
        ("현재 주차",  f"{parked}",    (80,200,255)),
        ("빈  자  리", f"{available}", (80,255,80) if available > 0 else (60,60,255)),
    ]
    bw = W // 3
    for i, (label, val, color) in enumerate(blocks):
        bx = i * bw
        # 한글 라벨
        frame = put_kr(frame, label, (bx+10, 30), 'label', (170,170,170))
        # 숫자 (크게, cv2)
        cv2.putText(frame, val, (bx+bw//2-20, 72),
                    cv2.FONT_HERSHEY_DUPLEX, 1.2, color, 2)

    # 구분선
    for i in range(1,3):
        cv2.line(frame, (bw*i, 28), (bw*i, ph-5), (80,80,80), 1)

    # 입/출차 누계 (우하단, 한글)
    frame = put_kr(frame, f"입차 누계: {te}대", (W-175, H-42), 'label', (80,255,80))
    frame = put_kr(frame, f"출차 누계: {tx}대", (W-175, H-22), 'label', (80,180,255))

    # 만차 경고
    if available == 0 and int(time.time()*2) % 2 == 0:
        cv2.rectangle(frame, (0,0), (W, ph), (0,0,200), 4)
        frame = put_kr(frame, "!! 만  차 !!", (W//2-60, ph-25), 'mid', (0,0,255))

    return frame


# ── 메인 ─────────────────────────────────────────────
def main():
    cap = cv2.VideoCapture(INPUT)
    FPS = cap.get(cv2.CAP_PROP_FPS)
    TF  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

    # ffmpeg 파이프로 H.264 mp4 출력
    ffcmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{W}x{H}', '-pix_fmt', 'bgr24', '-r', str(FPS),
        '-i', 'pipe:0',
        '-vcodec', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '23', '-preset', 'fast', OUTPUT
    ]
    ffproc = subprocess.Popen(ffcmd, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    fgbg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=40, detectShadows=True)
    kc   = cv2.getStructuringElement(cv2.MORPH_RECT, (9,9))
    ko   = cv2.getStructuringElement(cv2.MORPH_RECT, (5,5))

    # 배경 학습 (초기 60프레임)
    print("[INFO] 배경 모델 학습 중...")
    for _ in range(min(60, TF)):
        ret, f = cap.read()
        if ret:
            fgbg.apply(cv2.resize(f, (W,H)), learningRate=0.05)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    ct        = CentroidTracker()
    trackable = {}
    te        = 0          # 입차 누계
    tx        = 0          # 출차 누계
    parked    = INIT_PARKED
    tf_count  = 0
    last_rects = []
    log_rows   = []

    print(f"[INFO] 처리 시작 (총 {TF}프레임, {FPS:.0f}fps, 해상도 {W}x{H})")
    t0 = time.time()

    while True:
        ret, frame_orig = cap.read()
        if not ret: break

        frame   = cv2.resize(frame_orig, (W, H))
        fgmask  = fgbg.apply(frame, learningRate=0.002)

        # SKIP 프레임마다 차량 감지
        if tf_count % SKIP == 0:
            fgmask[fgmask == 127] = 0          # 그림자 제거
            roi = np.zeros_like(fgmask)
            roi[ROI_Y1:ROI_Y2] = fgmask[ROI_Y1:ROI_Y2]
            m = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, kc)
            m = cv2.morphologyEx(m,   cv2.MORPH_OPEN,  ko)
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            rects = []
            for c in cnts:
                a = cv2.contourArea(c)
                if a < MIN_A or a > MAX_A: continue
                x, y, w, h = cv2.boundingRect(c)
                if 0.4 <= w/max(h,1) <= 5.0:
                    rects.append((x, y, x+w, y+h))
                last_rects = rects

        # Centroid 추적 및 입출차 판단
        objects = ct.update(last_rects)

        for (oid, centroid) in objects.items():
            tv = trackable.get(oid)
            if tv is None:
                tv = TrackableVehicle(oid, centroid)
                trackable[oid] = tv
            else:
                # direction 계산 및 이동 경로 축적
                y_hist    = [c[1] for c in tv.centroids]
                direction = centroid[1] - np.mean(y_hist)
                tv.centroids.append(centroid)

                cx, cy = int(centroid[0]), int(centroid[1])

                # 📍 [버그수정 접합] 아직 카운트되지 않은 유니크 ID 차량만 판단 (Lock 메커니즘)
                if not tv.counted:
                    ev = None
                    
                    # 상단 감지선 혹은 하단 감지선 밴드 내에 걸쳤을 때
                    if abs(cy - LINE_TOP) < BAND or abs(cy - LINE_BOT) < BAND:
                        # 📍 [방향성 수정] y축 증가(아래로 이동) = 입차(enter)
                        if direction > 1.2:   
                            ev = "enter"
                        # 📍 [방향성 수정] y축 감소(위로 이동) = 출차(exit)
                        elif direction < -1.2: 
                            ev = "exit"

                    if ev == "enter":
                        te += 1
                        parked = min(parked+1, TOTAL)
                        tv.counted = True # 해당 차량 ID 주차장 탈출or완전진입 전까지 카운트 락
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        log_rows.append({"event":"입차","id":oid,"time":ts,"parked":parked})
                        print(f"  [{ts}] 입차 V{oid:02d} → 주차:{parked}/{TOTAL}  빈:{TOTAL-parked}")
                        
                    elif ev == "exit":
                        tx += 1
                        parked = max(parked-1, 0)
                        tv.counted = True # 중복 카운트 락
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        log_rows.append({"event":"출차","id":oid,"time":ts,"parked":parked})
                        print(f"  [{ts}] 출차 V{oid:02d} → 주차:{parked}/{TOTAL}  빈:{TOTAL-parked}")

            trackable[oid] = tv

        available = max(TOTAL - parked, 0)

        # ── 시각화 ───────────────────────────────────
        # 상단 감지선 (청록 점선)
        draw_dashed(frame, (0, LINE_TOP), (W, LINE_TOP), (0,220,220), thick=2)
        frame = put_kr(frame, "▶ 입출차 감지선 (상단)", (5, LINE_TOP-18), 'small', (0,220,220))

        # 하단 감지선 (주황 점선)
        draw_dashed(frame, (0, LINE_BOT), (W, LINE_BOT), (0,165,255), thick=2)
        frame = put_kr(frame, "▶ 입출차 감지선 (하단)", (5, LINE_BOT-18), 'small', (0,165,255))

        # 감지 박스 (노랑)
        for (x1,y1,x2,y2) in last_rects:
            cv2.rectangle(frame, (x1,y1), (x2,y2), (255,200,0), 1)

        # 추적 중심점 & ID
        for (oid, c) in objects.items():
            cx, cy = int(c[0]), int(c[1])
            in_zone = (cy < LINE_TOP) or (cy > LINE_BOT)
            col = (80,255,80) if in_zone else (255,255,255)
            cv2.circle(frame, (cx,cy), 4, col, -1)
            cv2.putText(frame, f"V{oid}", (cx-10, cy-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)

        # 정보 패널 (한글)
        frame = draw_panel(frame, TOTAL, parked, available, te, tx)

        # ffmpeg로 프레임 전송
        ffproc.stdin.write(frame.tobytes())

        if tf_count % 200 == 0:
            elapsed = time.time() - t0
            eta = (TF-tf_count)/(tf_count/elapsed) if tf_count > 0 else 0
            print(f"  진행: {tf_count/TF*100:.1f}% | 주차:{parked}/{TOTAL} | ETA:{eta:.0f}s")

        tf_count += 1

    cap.release()
    ffproc.stdin.close()
    ffproc.wait()

    # 로그 저장
    os.makedirs("utils/data/logs", exist_ok=True)
    with open("utils/data/logs/parking_log.json","w",encoding="utf-8") as f:
        json.dump(log_rows, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f"\n{'='*52}")
    print(f"  처리 완료  |  소요 시간: {elapsed:.1f}초")
    print(f"  입차 누계  : {te}대")
    print(f"  출차 누계  : {tx}대")
    print(f"  최종 주차  : {parked} / {TOTAL}")
    print(f"  남은 자리  : {TOTAL - parked}")
    print(f"  출력 영상  : {OUTPUT}")
    print(f"{'='*52}")

if __name__ == "__main__":
    main()
