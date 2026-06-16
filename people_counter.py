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
import json
import csv
import cv2
import os
import posixpath
import socketserver
from http.server import BaseHTTPRequestHandler
import urllib.error
import urllib.request
from urllib.parse import unquote, urlparse

# execution start time
start_time = time.time()
# setup logger
logging.basicConfig(level = logging.INFO, format = "[INFO] %(message)s")
logger = logging.getLogger(__name__)
# initiate features config.
with open("utils/config.json", "r") as file:
    config = json.load(file)

COUNT_STATE_PATH = "utils/data/count_state.json"
RESERVATION_PATH = "utils/data/reservations.json"
latest_web_frame = None
latest_web_frame_lock = threading.Lock()
reservation_lock = threading.Lock()

def read_reservations():
    try:
        with open(RESERVATION_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def write_reservations(data):
    os.makedirs(os.path.dirname(RESERVATION_PATH), exist_ok=True)
    with open(RESERVATION_PATH, "w") as f:
        json.dump(data, f)

def parse_arguments():
    # function to parse the arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--prototxt", required=False,
        help="path to Caffe 'deploy' prototxt file")
    ap.add_argument("-m", "--model", required=True,
        help="path to Caffe pre-trained model")
    ap.add_argument("-i", "--input", type=str,
        help="path to optional input video file")
    ap.add_argument("-o", "--output", type=str,
        help="path to optional output video file")
    # confidence default 0.4
    ap.add_argument("-c", "--confidence", type=float, default=0.12,
        help="minimum probability to filter weak detections")
    ap.add_argument("-s", "--skip-frames", type=int, default=2,
        help="# of skip frames between detections")
    ap.add_argument("--no-window", action="store_true",
        help="don't open the OpenCV desktop window; serve the browser view only")
    ap.add_argument("--no-loop", action="store_true",
        help="stop when the input video ends instead of looping it")
    args = vars(ap.parse_args())
    return args

def log_data(move_in, in_time, move_out, out_time):
    # function to log the counting data
    data = [move_in, in_time, move_out, out_time]
    # transpose the data to align the columns properly
    export_data = zip_longest(*data, fillvalue = '')

    with open('utils/data/logs/counting_data.csv', 'w', newline = '') as myfile:
        wr = csv.writer(myfile, quoting = csv.QUOTE_ALL)
        if myfile.tell() == 0: # check if header rows are already existing
            wr.writerow(("Move In", "In Time", "Move Out", "Out Time"))
            wr.writerows(export_data)

def write_count_state(event, total_enter, total_exit, current_inside, timestamp):
    # write the latest count so the static web page can poll it without a backend
    payload = {
        "event": event,
        "total_enter": total_enter,
        "total_exit": total_exit,
        "current_inside": current_inside,
        "timestamp": timestamp,
    }
    os.makedirs(os.path.dirname(COUNT_STATE_PATH), exist_ok=True)
    with open(COUNT_STATE_PATH, "w") as file:
        json.dump(payload, file)

class StreamingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/video_feed":
            self.stream_video()
            return
        if path == "/reservations":
            self.serve_reservations()
            return
        self.serve_static_file(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/reservations":
            self.handle_reservation()
            return
        self.send_response(404)
        self.end_headers()

    def serve_reservations(self):
        with reservation_lock:
            data = read_reservations()
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def handle_reservation(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        time_key = body.get("time")
        action = body.get("action")

        with reservation_lock:
            data = read_reservations()
            if action == "add":
                data[time_key] = data.get(time_key, 0) + 1
            elif action == "remove":
                data.pop(time_key, None)
            write_reservations(data)

        response = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def stream_video(self):
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            with latest_web_frame_lock:
                frame = latest_web_frame

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

    def serve_static_file(self, path):
        if path == "/":
            path = "/bus.html"

        relative_path = posixpath.normpath(unquote(path)).lstrip("/")
        root = os.getcwd()
        file_path = os.path.abspath(os.path.join(root, relative_path))

        if not file_path.startswith(root) or not os.path.isfile(file_path):
            self.send_response(404)
            self.end_headers()
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".mp4": "video/mp4",
        }
        extension = os.path.splitext(file_path)[1].lower()

        self.send_response(200)
        self.send_header("Content-Type", content_types.get(extension, "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        with open(file_path, "rb") as file:
            self.wfile.write(file.read())


def start_web_stream_server(port=8001):
    def run_server():
        try:
            server = StreamingServer(("", port), StreamingHandler)
            logger.info("Web page: http://localhost:%s/bus.html", port)
            logger.info("Web video stream: http://localhost:%s/video_feed", port)
            server.serve_forever()
        except OSError as error:
            logger.warning("Web video stream server failed: %s", error)

    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()

def update_web_frame(frame):
    global latest_web_frame
    success, encoded = cv2.imencode(".jpg", frame)
    if not success:
        return

    with latest_web_frame_lock:
        latest_web_frame = encoded.tobytes()

def post_count_update(event, total_enter, total_exit, current_inside, timestamp):
    # function to post counting events to a web service
    if not config.get("Web_Update"):
        return

    webhook_url = config.get("Web_Update_URL")
    if not webhook_url:
        logger.warning("Web update is enabled but Web_Update_URL is empty.")
        return

    payload = {
        "event": event,
        "total_enter": total_enter,
        "total_exit": total_exit,
        "current_inside": current_inside,
        "timestamp": timestamp,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        timeout = config.get("Web_Update_Timeout", 2)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                logger.warning("Web update failed with status %s.", response.status)
    except (urllib.error.URLError, TimeoutError) as error:
        logger.warning("Web update failed: %s", error)

def send_count_update(event, total_enter, total_exit, current_inside, timestamp):
    # send web updates in a background thread so video processing keeps running
    if not config.get("Web_Update"):
        return

    update_thread = threading.Thread(
        target=post_count_update,
        args=(event, total_enter, total_exit, current_inside, timestamp)
    )
    update_thread.daemon = True
    update_thread.start()

def people_counter():
    # main function for people_counter.py
    args = parse_arguments()
    start_web_stream_server()
    # initialize the list of class labels MobileNet SSD was trained to detect
    CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
        "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
        "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
        "sofa", "train", "tvmonitor"]

    # load our serialized model from disk
    net = cv2.dnn.readNetFromCaffe(args["prototxt"], args["model"])

    # if a video path was not supplied, grab a reference to the ip camera
    if not args.get("input", False):
        logger.info("Starting the live stream..")
        vs = VideoStream(config["url"]).start()
        time.sleep(2.0)

    # otherwise, grab a reference to the video file
    else:
        logger.info("Starting the video..")
        vs = cv2.VideoCapture(args["input"])

    # initialize the video writer (we'll instantiate later if need be)
    writer = None

    # initialize the frame dimensions (we'll set them as soon as we read
    # the first frame from the video)
    W = None
    H = None
    LINE_Y = None

    # instantiate our centroid tracker, then initialize a list to store
    # each of our dlib correlation trackers, followed by a dictionary to
    # map each unique object ID to a TrackableObject
    ct = CentroidTracker(maxDisappeared=25, maxDistance=110)
    trackableObjects = {}

    # initialize the total number of frames processed thus far, along
    # with the total number of objects that have moved either up or down
    totalFrames = 0
    totalDown = 0
    totalUp = 0
    # initialize empty lists to store the counting data
    total = []
    move_out = []
    move_in =[]
    out_time = []
    in_time = []
    write_count_state("init", totalDown, totalUp, 0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    # start the frames per second throughput estimator
    fps = FPS().start()

    if config["Thread"]:
        vs = thread.ThreadingClass(config["url"])

    # loop over frames from the video stream
    while True:
        # grab the next frame and handle if we are reading from either
        # VideoCapture or VideoStream
        frame = vs.read()
        frame = frame[1] if args.get("input", False) else frame

        # if we are viewing a video and we did not grab a frame then we
        # have reached the end of the video
        if args["input"] is not None and frame is None:
            if args.get("no_loop"):
                break
            # loop the clip so the web server keeps serving; reset the
            # counters/tracker so each loop starts fresh (the video visibly
            # restarts, so the count restarting is intuitive)
            vs.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ct = CentroidTracker(maxDisappeared=25, maxDistance=110)
            trackableObjects = {}
            totalDown = 0
            totalUp = 0
            total = []
            move_in = []
            move_out = []
            in_time = []
            out_time = []
            write_count_state("init", totalDown, totalUp, 0,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            continue

        # resize the frame to have a maximum width of 500 pixels
        # (the less data we have, the faster we can process it)
        frame = imutils.resize(frame, width = 500)

        # if the frame dimensions are empty, set them
        if W is None or H is None:
            (H, W) = frame.shape[:2]
            LINE_Y = int(H * 0.68)

        # if we are supposed to be writing a video to disk, initialize
        # the writer
        if args["output"] is not None and writer is None:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(args["output"], fourcc, 30,
                (W, H), True)

        # run the object detector on EVERY frame and collect person boxes.
        # (Top-down footage is hard for MobileNet-SSD, so detecting every
        # frame — instead of every N frames with a tracker filling gaps —
        # gives far better recall and cleaner trajectories for line crossing.)
        status = "Detecting"
        rects = []

        # convert the frame to a blob and pass it through the network
        blob = cv2.dnn.blobFromImage(frame, 0.007843, (W, H), 127.5)
        net.setInput(blob)
        detections = net.forward()

        # loop over the detections
        for i in np.arange(0, detections.shape[2]):
            # extract the confidence (i.e., probability)
            confidence = detections[0, 0, i, 2]

            # filter out weak detections by requiring a minimum confidence
            if confidence > args["confidence"]:
                # extract the index of the class label
                idx = int(detections[0, 0, i, 1])

                # if the class label is not a person, ignore it
                if CLASSES[idx] != "person":
                    continue

                # compute the (x, y)-coordinates of the bounding box and
                # add them to the rectangles list for the centroid tracker
                box = detections[0, 0, i, 3:7] * np.array([W, H, W, H])
                (startX, startY, endX, endY) = box.astype("int")
                rects.append((startX, startY, endX, endY))

        # draw a horizontal line in the center of the frame -- once an
        # object crosses this line we will determine whether they were
        # moving 'up' or 'down'
        cv2.line(frame, (0, LINE_Y), (W, LINE_Y), (0, 0, 0), 3)
        cv2.putText(frame, "-Prediction border - Entrance-", (10, H - ((i * 20) + 200)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        # use the centroid tracker to associate the (1) old object
        # centroids with (2) the newly computed object centroids
        objects = ct.update(rects)

        # loop over the tracked objects
        for (objectID, centroid) in objects.items():
            # check to see if a trackable object exists for the current
            # object ID
            to = trackableObjects.get(objectID, None)

            # if there is no existing trackable object, create one and
            # record which side of the line it first appeared on
            if to is None:
                to = TrackableObject(objectID, centroid)
                to.side = 1 if centroid[1] > LINE_Y else -1

            # otherwise, look for an actual line crossing. A small margin
            # keeps jitter right at the line from double-counting. Crossing
            # to the right = Enter, crossing to the left = Exit. We flip the
            # side each time, so a person walking back and forth is counted
            # on every crossing.
            else:
                to.centroids.append(centroid)
                cur_y = centroid[1]
                margin = 6

                # was above the line, now crossed downward -> Enter
                if to.side == -1 and cur_y > LINE_Y + margin:
                    to.side = 1
                    totalDown += 1
                    date_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    move_in.append(totalDown)
                    in_time.append(date_time)
                    current_inside = len(move_in) - len(move_out)
                    total = [current_inside]
                    write_count_state("enter", totalDown, totalUp, current_inside, date_time)
                    send_count_update("enter", totalDown, totalUp, current_inside, date_time)
                    # if the people limit exceeds over threshold, show an on-screen alert
                    if sum(total) >= config["Threshold"]:
                        cv2.putText(frame, "-ALERT: People limit exceeded-", (10, frame.shape[0] - 80),
                            cv2.FONT_HERSHEY_COMPLEX, 0.5, (0, 0, 255), 2)

                # was below the line, now crossed upward -> Exit
                elif to.side == 1 and cur_y < LINE_Y - margin:
                    to.side = -1
                    totalUp += 1
                    date_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    move_out.append(totalUp)
                    out_time.append(date_time)
                    current_inside = len(move_in) - len(move_out)
                    total = [current_inside]
                    write_count_state("exit", totalDown, totalUp, current_inside, date_time)
                    send_count_update("exit", totalDown, totalUp, current_inside, date_time)

            # store the trackable object in our dictionary
            trackableObjects[objectID] = to

            # draw both the ID of the object and the centroid of the
            # object on the output frame
            text = "ID {}".format(objectID)
            cv2.putText(frame, text, (centroid[0] - 10, centroid[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            cv2.circle(frame, (centroid[0], centroid[1]), 4, (255, 255, 255), -1)

        # construct a tuple of information we will be displaying on the frame
        info_status = [
        ("Exit", totalUp),
        ("Enter", totalDown),
        ("Status", status),
        ]

        info_total = [
        ("Total people inside", ', '.join(map(str, total))),
        ]

        # display the output
        for (i, (k, v)) in enumerate(info_status):
            text = "{}: {}".format(k, v)
            cv2.putText(frame, text, (10, H - ((i * 20) + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        for (i, (k, v)) in enumerate(info_total):
            text = "{}: {}".format(k, v)
            cv2.putText(frame, text, (265, H - ((i * 20) + 60)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # initiate a simple log to save the counting data
        if config["Log"]:
            log_data(move_in, in_time, move_out, out_time)

        # check to see if we should write the frame to disk
        if writer is not None:
            writer.write(frame)

        update_web_frame(frame)

        # show the output frame (skip the desktop window in --no-window mode,
        # e.g. when you only want the browser view at http://localhost:8001)
        if not args.get("no_window"):
            cv2.imshow("Real-Time Monitoring/Analysis Window", frame)
            key = cv2.waitKey(1) & 0xFF
            # if the `q` key was pressed, break from the loop
            if key == ord("q"):
                break
        # increment the total number of frames processed thus far and
        # then update the FPS counter
        totalFrames += 1
        fps.update()

        # initiate the timer
        if config["Timer"]:
            # automatic timer to stop the live stream (set to 8 hours/28800s)
            end_time = time.time()
            num_seconds = (end_time - start_time)
            if num_seconds > 28800:
                break

    # stop the timer and display FPS information
    fps.stop()
    logger.info("Elapsed time: {:.2f}".format(fps.elapsed()))
    logger.info("Approx. FPS: {:.2f}".format(fps.fps()))

    # release the camera device/resource (issue 15)
    if config["Thread"]:
        vs.release()

    # close any open windows
    cv2.destroyAllWindows()

# initiate the scheduler
if config["Scheduler"]:
    # runs at every day (09:00 am)
    schedule.every().day.at("09:00").do(people_counter)
    while True:
        schedule.run_pending()
else:
    people_counter()