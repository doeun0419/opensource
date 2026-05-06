from tracker.centroidtracker import CentroidTracker
from tracker.trackableobject import TrackableObject
from imutils.video import VideoStream
from itertools import zip_longest
from imutils.video import FPS
from utils import thread
import numpy as np
import threading
import argparse
import datetime
import schedule
import logging
import imutils
import time
import dlib
import json
import csv
import cv2
import urllib.error
import urllib.request
from flask import Flask, render_template, jsonify

# --- Flask 설정 ---
app = Flask(__name__)
counting_stats = {
    "total_enter": 0,
    "total_exit": 0,
    "current_inside": 0,
    "status": "Waiting"
}

@app.route('/')
def index():
    return render_template('bus.html')

@app.route('/data')
def get_data():
    return jsonify(counting_stats)

# --- 메인 로직 ---
logging.basicConfig(level = logging.INFO, format = "[INFO] %(message)s")
logger = logging.getLogger(__name__)

with open("utils/config.json", "r") as file:
    config = json.load(file)

def parse_arguments():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--prototxt", required=False, help="path to Caffe 'deploy' prototxt file")
    ap.add_argument("-m", "--model", required=True, help="path to Caffe pre-trained model")
    ap.add_argument("-i", "--input", type=str, help="path to optional input video file")
    ap.add_argument("-c", "--confidence", type=float, default=0.4)
    ap.add_argument("-s", "--skip-frames", type=int, default=30)
    return vars(ap.parse_args())

def people_counter():
    global counting_stats
    args = parse_arguments()
    CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"]
    net = cv2.dnn.readNetFromCaffe(args["prototxt"], args["model"])

    if not args.get("input", False):
        vs = VideoStream(config["url"]).start()
        time.sleep(2.0)
    else:
        vs = cv2.VideoCapture(args["input"])

    W, H = None, None
    ct = CentroidTracker(maxDisappeared=40, maxDistance=50)
    trackers, trackableObjects = [], {}
    totalFrames, totalDown, totalUp = 0, 0, 0

    while True:
        frame = vs.read()
        frame = frame[1] if args.get("input", False) else frame
        if frame is None: break

        frame = imutils.resize(frame, width=500)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if W is None or H is None: (H, W) = frame.shape[:2]

        status = "Waiting"
        rects = []

        if totalFrames % args["skip_frames"] == 0:
            status = "Detecting"
            trackers = []
            blob = cv2.dnn.blobFromImage(frame, 0.007843, (W, H), 127.5)
            net.setInput(blob)
            detections = net.forward()
            for i in np.arange(0, detections.shape[2]):
                if detections[0, 0, i, 2] > args["confidence"]:
                    if CLASSES[int(detections[0, 0, i, 1])] == "person":
                        box = detections[0, 0, i, 3:7] * np.array([W, H, W, H])
                        (startX, startY, endX, endY) = box.astype("int")
                        tracker = dlib.correlation_tracker()
                        tracker.start_track(rgb, dlib.rectangle(startX, startY, endX, endY))
                        trackers.append(tracker)
        else:
            for tracker in trackers:
                status = "Tracking"
                tracker.update(rgb)
                pos = tracker.get_position()
                rects.append((int(pos.left()), int(pos.top()), int(pos.right()), int(pos.bottom())))

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

        # 데이터 업데이트
        counting_stats.update({
            "total_enter": totalDown,
            "total_exit": totalUp,
            "current_inside": max(0, totalDown - totalUp),
            "status": status
        })
        totalFrames += 1

if __name__ == '__main__':
    t = threading.Thread(target=people_counter)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=10000)
