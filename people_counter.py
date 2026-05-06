from tracker.centroidtracker import CentroidTracker
from tracker.trackableobject import TrackableObject
from imutils.video import VideoStream
import numpy as np
import threading
import argparse
import json
import imutils
import time
import cv2
from flask import Flask, render_template, jsonify

# --- Flask 설정 ---
app = Flask(__name__)
counting_stats = {"total_enter": 0, "total_exit": 0, "current_inside": 0, "status": "Waiting"}

@app.route('/')
def index(): return render_template('bus.html')

@app.route('/data')
def get_data(): return jsonify(counting_stats)

def people_counter():
    global counting_stats
    # --- 설정 파일 로드 ---
    with open("utils/config.json", "r") as file:
        config = json.load(file)
    
    # 모델 경로 (Render Start Command에서 전달받은 인자 사용)
    prototxt = "utils/mobilenet_ssd/deploy.prototxt"
    model = "utils/mobilenet_ssd/mobilenet_iter_73000.caffemodel"
    
    CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"]
    net = cv2.dnn.readNetFromCaffe(prototxt, model)

    vs = VideoStream(config["url"]).start()
    time.sleep(2.0)

    W, H = None, None
    ct = CentroidTracker(maxDisappeared=40, maxDistance=50)
    trackers, trackableObjects = [], {}
    totalFrames, totalDown, totalUp = 0, 0, 0

    while True:
        frame = vs.read()
        if frame is None: break
        frame = imutils.resize(frame, width=500)
        if W is None or H is None: (H, W) = frame.shape[:2]

        rects = []
        # dlib 대신 OpenCV 트래커 리스트 관리 (간소화)
        if totalFrames % 30 == 0:
            trackers = []
            blob = cv2.dnn.blobFromImage(frame, 0.007843, (W, H), 127.5)
            net.setInput(blob)
            detections = net.forward()
            for i in np.arange(0, detections.shape[2]):
                if detections[0, 0, i, 2] > 0.4:
                    if CLASSES[int(detections[0, 0, i, 1])] == "person":
                        box = detections[0, 0, i, 3:7] * np.array([W, H, W, H])
                        rects.append(box.astype("int"))
        
        objects = ct.update(rects)
        for (objectID, centroid) in objects.items():
            to = trackableObjects.get(objectID, None)
            if to is None: to = TrackableObject(objectID, centroid)
            else:
                direction = centroid[1] - np.mean([c[1] for c in to.centroids])
                to.centroids.append(centroid)
                if not to.counted:
                    if direction < 0 and centroid[1] < H // 2:
                        totalUp += 1
                        to.counted = True
                    elif direction > 0 and centroid[1] > H // 2:
                        totalDown += 1
                        to.counted = True
            trackableObjects[objectID] = to

        counting_stats.update({
            "total_enter": totalDown, "total_exit": totalUp,
            "current_inside": max(0, totalDown - totalUp),
            "status": "Running"
        })
        totalFrames += 1

if __name__ == '__main__':
    t = threading.Thread(target=people_counter); t.daemon = True; t.start()
    app.run(host='0.0.0.0', port=10000)
