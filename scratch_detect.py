import cv2
from ultralytics import YOLO

model = YOLO('yolov8n.pt')
cap = cv2.VideoCapture('static/uploads/video_utara_80s.mp4')
fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

for sec in [5.0, 35.0, 38.0, 39.0, 40.0, 41.0, 42.0]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
    ret, frame = cap.read()
    if not ret: continue
    frame = cv2.resize(frame, (640, 360))
    res = model(frame, conf=0.12, verbose=False)[0]
    print(f'=== TIME: {sec:.1f}s (640x360) ===')
    for b in res.boxes:
        xyxy = [int(v) for v in b.xyxy[0].tolist()]
        cid = int(b.cls[0])
        conf = float(b.conf[0])
        cname = model.names[cid]
        if xyxy[3] > 170:
            print(f'  {cname} conf={conf:.2f} box={xyxy}')
cap.release()
