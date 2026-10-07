import cv2
import os
import sys

vpath = 'static/uploads/video_dummy.mp4'
if not os.path.exists(vpath):
    print('Not found:', vpath)
    sys.exit(1)

cap = cv2.VideoCapture(vpath)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS)
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Video dummy: {w}x{h}, {fps} FPS, {total_frames} frames ({total_frames/fps:.1f} sec)", flush=True)

from ultralytics import YOLO
model = YOLO('yolov8n.pt')

for f_idx in [0, 45, 90, 135, 180]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if not ret: break
    frame = cv2.resize(frame, (640, 360))
    res = model(frame, conf=0.20, classes=[0, 1, 2, 3, 5, 7], verbose=False)
    boxes = res[0].boxes.xyxy.cpu().numpy()
    classes = res[0].boxes.cls.cpu().numpy().astype(int)
    confs = res[0].boxes.conf.cpu().numpy()
    print(f"\n--- Frame {f_idx} ({len(boxes)} detections) ---", flush=True)
    for b, c, cf in zip(boxes, classes, confs):
        x1, y1, x2, y2 = map(int, b)
        bw = x2 - x1
        bh = y2 - y1
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        c_name = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}.get(c, str(c))
        print(f"  {c_name:<10} conf={cf:.2f} box=[{x1},{y1},{x2},{y2}] cx={cx} cy={cy} bw={bw} bh={bh}", flush=True)

cap.release()
