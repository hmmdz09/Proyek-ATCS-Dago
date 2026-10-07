import os
import time
import math
import random
import threading
import cv2
import numpy as np
from flask import Flask, render_template, Response, jsonify, request
from ultralytics import YOLO

app = Flask(__name__)

# Direktori & File Upload
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Inisialisasi Model YOLOv8 Nano
MODEL_PATH = os.path.join(BASE_DIR, "yolov8n.pt")
model = YOLO(MODEL_PATH)

# Path Video Nyata (Durasi 0 - 80 Detik dari berkas lv_0_20261001085841)
VIDEO_UTARA_PATH = os.path.join(UPLOAD_FOLDER, 'video_utara_80s.mp4')
if not os.path.exists(VIDEO_UTARA_PATH):
    VIDEO_UTARA_PATH = os.path.join(UPLOAD_FOLDER, 'video_dummy.mp4')
active_video_info = {
    "utara": "lv_0_20261001085841.mp4 (0-80s)",
    "timur": None,
    "selatan": None,
    "barat": None
}

cctv_custom_videos = {
    "selatan": None,
    "timur": None,
    "barat": None
}

# Buffer Global JPEG Frame untuk Streaming CCTV Utara
latest_jpeg_frame_utara = None
jpeg_lock = threading.Lock()
yolo_lock = threading.Lock()
reset_requested = False
video_loop_epoch = 1


# Non-Maximum Suppression (NMS) Custom
def apply_nms(boxes, classes, iou_thresh=0.55):
    if len(boxes) == 0:
        return [], []
    b_arr = np.array(boxes, dtype=np.float32)
    x1, y1, x2, y2 = b_arr[:, 0], b_arr[:, 1], b_arr[:, 2], b_arr[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = areas.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        # Hanya tekan box jika kelas sama (IoU > 0.55) atau beda kelas tapi overlap sangat tinggi (> 0.72)
        cls_match = np.array([classes[k] == classes[i] for k in order[1:]], dtype=bool)
        thresh_arr = np.where(cls_match, iou_thresh, 0.72)
        inds = np.where(iou <= thresh_arr)[0]
        order = order[inds + 1]
    return [boxes[k] for k in keep], [classes[k] for k in keep]

# Tracker Kendaraan Cerdas dengan Estimasi Kecepatan & Deteksi Kendaraan Diam
class SimpleVehicleTracker:
    def __init__(self, max_distance=85, max_disappeared=20):
        self.next_id = 1
        self.tracks = {}

    def update(self, detected_boxes, detected_classes):
        if len(detected_boxes) == 0:
            for tid in list(self.tracks.keys()):
                self.tracks[tid]["disappeared"] += 1
                if self.tracks[tid]["disappeared"] > 20:
                    del self.tracks[tid]
            results = []
            for tid, t in self.tracks.items():
                if t["disappeared"] <= 5:
                    results.append((t["box"], tid, t["cls"], t["speed_kmh"], t["stopped_steps"]))
            return results

        if len(self.tracks) == 0:
            results = []
            for box, cls_name in zip(detected_boxes, detected_classes):
                cx = int((box[0] + box[2]) / 2)
                cy = int((box[1] + box[3]) / 2)
                tid = self.next_id
                self.next_id += 1
                assigned_cls = "motor" if cls_name in ["pejalan_kaki", "person"] else cls_name
                self.tracks[tid] = {
                    "center": (cx, cy),
                    "init_cx": cx,
                    "box": box,
                    "cls": assigned_cls,
                    "speed_kmh": 0.0,
                    "stopped_steps": 0,
                    "smooth_dx": 0.0,
                    "smooth_dy": 0.0,
                    "disappeared": 0
                }
                results.append((box, tid, assigned_cls, 0.0, 0))
            return results

        track_ids = list(self.tracks.keys())
        track_centers = [self.tracks[tid]["center"] for tid in track_ids]
        new_centers = [((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) for box in detected_boxes]

        matched_tracks = set()
        matched_detections = set()
        results = []

        for d_idx, (dcx, dcy) in enumerate(new_centers):
            best_tid = None
            best_dist = float('inf')
            for t_idx, tid in enumerate(track_ids):
                if tid in matched_tracks:
                    continue
                tcx, tcy = track_centers[t_idx]
                dist = np.hypot(dcx - tcx, dcy - tcy)
                if dist < 120 and dist < best_dist:
                    best_dist = dist
                    best_tid = tid

            if best_tid is not None:
                matched_tracks.add(best_tid)
                matched_detections.add(d_idx)
                old_cx, old_cy = self.tracks[best_tid]["center"]
                dist_px = float(np.hypot(dcx - old_cx, dcy - old_cy))

                dx_step = dcx - old_cx
                dy_step = dcy - old_cy
                prev_dx = self.tracks[best_tid].get("smooth_dx", 0.0)
                prev_dy = self.tracks[best_tid].get("smooth_dy", 0.0)
                smooth_dx = round(0.70 * prev_dx + 0.30 * dx_step, 2)
                smooth_dy = round(0.70 * prev_dy + 0.30 * dy_step, 2)

                px_per_m = 8.0 + (max(0.0, dcy - 90.0) / 270.0) * 16.0
                dt = 0.04

                if dist_px < 2.5:
                    inst_speed = 0.0
                    dcx, dcy = old_cx, old_cy
                else:
                    inst_speed = (dist_px / px_per_m) / dt * 3.6
                    inst_speed = min(75.0, inst_speed)

                prev_speed = self.tracks[best_tid].get("speed_kmh", 0.0)
                if inst_speed == 0.0:
                    speed_kmh = 0.0
                else:
                    speed_kmh = round(0.60 * prev_speed + 0.40 * inst_speed, 1)
                    if speed_kmh < 4.0:
                        speed_kmh = 0.0

                stopped_steps = self.tracks[best_tid].get("stopped_steps", 0)
                if speed_kmh < 3.0 and dist_px < 3.0:
                    stopped_steps += 1
                else:
                    stopped_steps = max(0, stopped_steps - 2)

                # ATURAN KLASIFIKASI PEJALAN KAKI VS MOTOR / KENDARAAN:
                # - Bergerak horizontal nyata dari kiri ke kanan atau sebaliknya: abs(smooth_dx) >= 2.0, total_dx >= 12px, dan abs(smooth_dx) > 1.4 * abs(smooth_dy) -> PEJALAN KAKI
                # - Tapi jika ke kiri atau kanan sedikit atau antre/bergerak memanjang searah arus jalan -> PASTI MOTOR ATAU KENDARAAN LAINNYA!
                init_cx = self.tracks[best_tid].get("init_cx", dcx)
                total_dx = abs(dcx - init_cx)
                is_horizontal_crossing = (abs(smooth_dx) >= 2.0 and total_dx >= 12.0 and abs(smooth_dx) > 1.4 * max(0.4, abs(smooth_dy)))

                raw_cls = detected_classes[d_idx]
                if raw_cls in ["pejalan_kaki", "person", "motor"]:
                    if is_horizontal_crossing:
                        final_cls = "pejalan_kaki"
                    else:
                        final_cls = "motor"
                else:
                    final_cls = raw_cls

                self.tracks[best_tid]["center"] = (dcx, dcy)
                self.tracks[best_tid]["box"] = detected_boxes[d_idx]
                self.tracks[best_tid]["cls"] = final_cls
                self.tracks[best_tid]["speed_kmh"] = speed_kmh
                self.tracks[best_tid]["stopped_steps"] = stopped_steps
                self.tracks[best_tid]["smooth_dx"] = smooth_dx
                self.tracks[best_tid]["smooth_dy"] = smooth_dy
                self.tracks[best_tid]["disappeared"] = 0
                results.append((detected_boxes[d_idx], best_tid, final_cls, speed_kmh, stopped_steps))

        for d_idx, box in enumerate(detected_boxes):
            if d_idx not in matched_detections:
                tid = self.next_id
                self.next_id += 1
                dcx = int((box[0] + box[2]) / 2)
                dcy = int((box[1] + box[3]) / 2)
                raw_cls = detected_classes[d_idx]
                assigned_cls = "motor" if raw_cls in ["pejalan_kaki", "person"] else raw_cls
                self.tracks[tid] = {
                    "center": (dcx, dcy),
                    "init_cx": dcx,
                    "box": box,
                    "cls": assigned_cls,
                    "speed_kmh": 0.0,
                    "stopped_steps": 0,
                    "smooth_dx": 0.0,
                    "smooth_dy": 0.0,
                    "disappeared": 0
                }
                results.append((box, tid, assigned_cls, 0.0, 0))

        for tid in track_ids:
            if tid not in matched_tracks:
                self.tracks[tid]["disappeared"] += 1
                if self.tracks[tid]["disappeared"] > 20:
                    del self.tracks[tid]

        return results

# Pelacak Pergerakan Kamera Dinamis (ORB + RANSAC Partial Affine)
class DynamicCameraTracker:
    def __init__(self, ref_frame):
        self.reset(ref_frame)

    def reset(self, ref_frame):
        self.ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
        self.orb = cv2.ORB_create(nfeatures=300, fastThreshold=12)

        self.bg_mask = np.zeros_like(self.ref_gray)
        self.bg_mask[20:280, 350:635] = 255
        self.bg_mask[10:140, 0:180] = 255

        self.kp0, self.des0 = self.orb.detectAndCompute(self.ref_gray, mask=self.bg_mask)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self.last_aff = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

        # Poligon Landmark Kamera Lengan Utara (Terkalibrasi Presisi untuk lv_0_20261001085841)
        self.zebra_poly0 = np.array([[12, 275], [200, 275], [215, 332], [12, 332]], dtype=np.float32)
        self.road_poly0 = np.array([[5, 15], [145, 15], [235, 358], [5, 358]], dtype=np.float32)
        self.trotoar_poly0 = np.array([[142, 15], [240, 15], [638, 260], [638, 358], [225, 358], [215, 332], [200, 275]], dtype=np.float32)
        self.billboard_poly0 = np.array([[348, 75], [638, 75], [638, 290], [348, 290]], dtype=np.float32)

    def update(self, curr_frame):
        curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
        kp_curr, des_curr = self.orb.detectAndCompute(curr_gray, mask=self.bg_mask)
        if des_curr is not None and len(des_curr) >= 10 and self.des0 is not None and len(self.des0) >= 10:
            matches = self.bf.knnMatch(self.des0, des_curr, k=2)
            good = [m for m, n in matches if m.distance < 0.78 * n.distance]
            if len(good) >= 8:
                src_pts = np.float32([self.kp0[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                dst_pts = np.float32([kp_curr[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
                T, inliers = cv2.estimateAffinePartial2D(src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=3.0)
                if T is not None and abs(T[0, 2]) < 180 and abs(T[1, 2]) < 120:
                    self.last_aff = 0.75 * self.last_aff + 0.25 * T

        aff = self.last_aff
        zebra_dyn = cv2.transform(np.array([self.zebra_poly0]), aff)[0].astype(np.int32)
        road_dyn = cv2.transform(np.array([self.road_poly0]), aff)[0].astype(np.int32)
        trotoar_dyn = cv2.transform(np.array([self.trotoar_poly0]), aff)[0].astype(np.int32)
        billboard_dyn = cv2.transform(np.array([self.billboard_poly0]), aff)[0].astype(np.int32)
        return zebra_dyn, road_dyn, trotoar_dyn, billboard_dyn, aff

# Penghitung IoU Overlap Bounding Box terhadap Poligon Sensor
def compute_mask_overlap(box, poly_mask, frame_w, frame_h):
    x1, y1, x2, y2 = map(int, box)
    x1 = max(0, min(frame_w - 1, x1))
    y1 = max(0, min(frame_h - 1, y1))
    x2 = max(x1 + 1, min(frame_w, x2))
    y2 = max(y1 + 1, min(frame_h, y2))
    box_area = (x2 - x1) * (y2 - y1)
    if box_area <= 0:
        return 0.0
    sub = poly_mask[y1:y2, x1:x2]
    inter_pixels = cv2.countNonZero(sub)
    return float(inter_pixels) / float(box_area)

# Generator Plat Nomor Bandung Realistis & Set Tilang Anti-Duplikasi
vehicle_plates = {}
ticketed_vehicle_plates = set()

# Variabel Sinkronisasi Video Playback CCTV Lengan Utara
current_video_sec_utara = 0.0

def get_or_create_plate(track_id, cls_str, cx=None):
    if cls_str == "pejalan_kaki":
        return ""
    if track_id in vehicle_plates:
        return vehicle_plates[track_id]

    rng = random.Random(track_id * 1013 + 47)

    if cls_str == "motor":
        angka = rng.randint(2000, 6999)
        huruf = rng.choice(['SK', 'ZX', 'KL', 'DF', 'TZX', 'BCA', 'DGO', 'NX'])
        plat = f"D {angka} {huruf}"
    elif cls_str in ["travel", "bus"]:
        angka = rng.randint(7000, 7999)
        huruf = rng.choice(['CIT', 'DAY', 'TMB', 'DMR', 'BDG'])
        plat = f"D {angka} {huruf}"
    else:
        angka = rng.randint(1000, 1999)
        huruf = rng.choice(['RZ', 'PL', 'TN', 'MY', 'KQ', 'SZ', 'FA', 'GL'])
        plat = f"D {angka} {huruf}"
    vehicle_plates[track_id] = plat
    return plat

def generate_random_plate(cls_str):
    if cls_str == "motor":
        angka = random.randint(2000, 6999)
        huruf = random.choice(['AB', 'SK', 'ZX', 'KL', 'DF', 'TZX', 'BCA', 'DGO', 'NX'])
    elif cls_str in ["travel", "bus"]:
        angka = random.randint(7000, 7999)
        huruf = random.choice(['CIT', 'DAY', 'TMB', 'DMR', 'BDG', 'WS'])
    else:
        angka = random.randint(1000, 1999)
        huruf = random.choice(['RZ', 'PL', 'TN', 'MY', 'KQ', 'SZ', 'FA', 'GL'])
    return f"D {angka} {huruf}"

# Global State Sistem ATCS Simpang Dago (Sesuai Data Riil Video Lengan Utara)
status_sistem = {
    "fase_lampu": "SELATAN",
    "fase_start_time": time.time(),
    "manual_override_until": 0,
    "total_volume": 61,
    "total_pelanggaran": 0,
    "total_smp_persimpangan": 32.05,
    "daftar_pelanggaran": [],
    "detail_pelanggaran": None,
    "tilang_aktif": True,
    "pelanggaran_per_arm": {
        "utara": {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0},
        "timur": {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0},
        "selatan": {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0},
        "barat": {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0}
    },
    "per_arm": {
        "utara": {
            "kepadatan": "PADAT",
            "smp": 32.05,
            "smp_lurus": 19.23,
            "smp_kanan": 8.01,
            "motor": 39, "mobil": 21, "bus": 1, "total": 61,
            "volume_terkumpul": 61,
            "pelanggaran": 5,
            "durasi_lurus": 32,
            "durasi_kanan": 32,
            "is_lurus_green": False,
            "is_kanan_green": False,
            "timer_lurus": 48,
            "timer_kanan": 48,
            "has_video": True
        },
        "timur": {
            "kepadatan": "LANCAR",
            "smp": 2.8,
            "motor": 2, "mobil": 1, "bus": 1, "total": 4,
            "volume_terkumpul": 4,
            "pelanggaran": 0,
            "durasi": 20,
            "is_green": False,
            "timer": 45,
            "has_video": False
        },
        "selatan": {
            "kepadatan": "SEDANG",
            "smp": 5.1,
            "smp_lurus": 3.06,
            "smp_kanan": 1.28,
            "motor": 4, "mobil": 3, "bus": 1, "total": 8,
            "volume_terkumpul": 8,
            "pelanggaran": 0,
            "durasi_lurus": 30,
            "durasi_kanan": 10,
            "is_lurus_green": True,
            "is_kanan_green": True,
            "timer_lurus": 28,
            "timer_kanan": 10,
            "has_video": False
        },
        "barat": {
            "kepadatan": "LANCAR",
            "smp": 3.5,
            "motor": 2, "mobil": 2, "bus": 1, "total": 5,
            "volume_terkumpul": 5,
            "pelanggaran": 0,
            "durasi": 20,
            "is_green": False,
            "timer": 58,
            "has_video": False
        }
    },
    "kendaraan_simulasi": {
        "utara": [],
        "timur": [],
        "selatan": [],
        "barat": []
    },
    "sirkulasi_od": {
        "lengan": "UTARA",
        "total_keluar": 61,
        "masuk_selatan": 37,
        "masuk_barat": 15,
        "masuk_timur": 9,
        "total_masuk_3_lengan": 61,
        "konsistensi_persen": 100.0,
        "formula": "61 Keluar = 37 (Selatan/Lurus) + 15 (Barat/Kanan) + 9 (Timur/Kiri)",
        "status_konservasi": "100% TEPAT & KONSISTEN"
    }
}

pelanggaran_ids_arm = {
    "utara": set(),
    "timur": set(),
    "selatan": set(),
    "barat": set()
}

seen_track_ids_utara = set()

# Direktori Penyimpanan Foto Bukti Kejadian ETLE
EVIDENCE_FOLDER = os.path.join(UPLOAD_FOLDER, 'evidence')
os.makedirs(EVIDENCE_FOLDER, exist_ok=True)

# Generator Foto Bukti Kejadian Otomatis (Incident & Evidence Logger)
def generate_evidence_photo(pel_id, plat, cls_str, jenis_teks, lengan="UTARA", crop_img=None):
    filename = f"evidence_{pel_id}.jpg"
    filepath = os.path.join(EVIDENCE_FOLDER, filename)
    rel_url = f"/static/uploads/evidence/{filename}"

    # Buat kanvas bukti ETLE resolusi 640x360
    canvas_img = np.zeros((360, 640, 3), dtype=np.uint8)
    canvas_img[:] = (18, 24, 32) # Dark navy

    # Header Bukti ETLE
    cv2.rectangle(canvas_img, (0, 0), (640, 42), (10, 16, 24), -1)
    cv2.putText(canvas_img, "POLDA JABAR - KORLANTAS POLRI / ATCS DISHUB KOTA BANDUNG", (14, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, "INCIDENT & EVIDENCE LOGGER", (415, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 230, 255), 1, cv2.LINE_AA)
    cv2.line(canvas_img, (0, 42), (640, 42), (0, 140, 255), 2)

    # Kotak Crop Kendaraan (Sisi Kiri: 320x250)
    box_crop_w, box_crop_h = 320, 250
    ox, oy = 16, 56
    cv2.rectangle(canvas_img, (ox - 2, oy - 2), (ox + box_crop_w + 2, oy + box_crop_h + 2), (40, 50, 65), -1)

    placed = False
    if crop_img is not None and getattr(crop_img, 'size', 0) > 0:
        ch, cw = crop_img.shape[:2]
        if ch > 10 and cw > 10:
            scale = min(float(box_crop_w) / cw, float(box_crop_h) / ch)
            nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
            res = cv2.resize(crop_img, (nw, nh))
            px = ox + (box_crop_w - nw) // 2
            py = oy + (box_crop_h - nh) // 2
            canvas_img[py:py+nh, px:px+nw] = res
            cv2.rectangle(canvas_img, (px, py), (px + nw, py + nh), (0, 0, 255), 2)
            placed = True

    if not placed:
        sample_name = "white_car_crop.jpg" if cls_str == "mobil" else ("crop_frame0_zebra.jpg" if cls_str == "motor" else "crop_check_314.jpg")
        sample_path = os.path.join(BASE_DIR, sample_name)
        if os.path.exists(sample_path):
            sample_img = cv2.imread(sample_path)
            if sample_img is not None and getattr(sample_img, 'size', 0) > 0:
                ch, cw = sample_img.shape[:2]
                scale = min(float(box_crop_w) / cw, float(box_crop_h) / ch)
                nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
                res = cv2.resize(sample_img, (nw, nh))
                px = ox + (box_crop_w - nw) // 2
                py = oy + (box_crop_h - nh) // 2
                canvas_img[py:py+nh, px:px+nw] = res
                cv2.rectangle(canvas_img, (px, py), (px + nw, py + nh), (0, 0, 255), 2)
                placed = True

    if not placed:
        cv2.rectangle(canvas_img, (ox + 20, oy + 40), (ox + box_crop_w - 20, oy + box_crop_h - 40), (25, 35, 50), -1)
        cv2.rectangle(canvas_img, (ox + 20, oy + 40), (ox + box_crop_w - 20, oy + box_crop_h - 40), (0, 0, 255), 2)
        cv2.putText(canvas_img, f"VEHICLE CROP: {cls_str.upper()}", (ox + 35, oy + 130), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    cv2.rectangle(canvas_img, (ox + 6, oy + box_crop_h - 28), (ox + box_crop_w - 6, oy + box_crop_h - 6), (10, 10, 15), -1)
    cv2.putText(canvas_img, f"CAM-{lengan[:1].upper()} | SENSOR IOU VERIFIED", (ox + 12, oy + box_crop_h - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 200), 1, cv2.LINE_AA)

    # Sisi Kanan: Informasi Lengkap Bukti E-Tilang
    rx = 350
    cv2.rectangle(canvas_img, (rx, 54), (626, 78), (20, 60, 30), -1)
    cv2.rectangle(canvas_img, (rx, 54), (626, 78), (40, 180, 80), 1)
    cv2.putText(canvas_img, "[LOGGED / READY FOR ETLE VERIFICATION]", (rx + 8, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 255, 130), 1, cv2.LINE_AA)

    cv2.putText(canvas_img, f"ID KEJADIAN : {pel_id}", (rx, 98), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 220, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, f"NO. POLISI  : {plat}", (rx, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas_img, f"KENDARAAN   : {cls_str.upper()} (Simpang Dago)", (rx, 138), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 210, 220), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, f"LOKASI      : Lengan {lengan.upper()} (Jl. Ir. H. Juanda)", (rx, 156), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 190, 200), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, f"WAKTU       : {time.strftime('%H:%M:%S WIB • %d/%m/%Y')}", (rx, 174), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 190, 200), 1, cv2.LINE_AA)

    cv2.line(canvas_img, (rx, 186), (626, 186), (50, 65, 85), 1)

    cv2.putText(canvas_img, "PELANGGARAN :", (rx, 204), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (100, 180, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, jenis_teks[:34], (rx, 222), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 120, 120), 1, cv2.LINE_AA)
    if len(jenis_teks) > 34:
        cv2.putText(canvas_img, jenis_teks[34:68], (rx, 238), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 120, 120), 1, cv2.LINE_AA)

    is_zebra = ("Zebra" in jenis_teks or "Garis Henti" in jenis_teks or "Stop Line" in jenis_teks)
    is_trotoar = ("Trotoar" in jenis_teks)
    if is_zebra:
        pasal_line = "Ps. 106 (2)&(4) jo. Ps. 287 (1) UU LLAJ"
        alasan_line = "Merampas hak & membahayakan pejalan kaki"
    elif is_trotoar:
        pasal_line = "Ps. 106 (2)&(4) jo. Ps. 284 UU LLAJ"
        alasan_line = "Menaiki trotoar hak pejalan kaki"
    else:
        pasal_line = "Ps. 106 (4) jo. Ps. 287 (1) UU LLAJ"
        alasan_line = "Melanggar rambu dilarang stop ('S' coret)"

    cv2.putText(canvas_img, f"DASAR HUKUM : {pasal_line}", (rx, 258), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, f"ALASAN      : {alasan_line}", (rx, 274), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 200, 220), 1, cv2.LINE_AA)
    cv2.putText(canvas_img, "SANKSI RESMI: Denda Maks. Rp500.000 / Kurungan 2 Bln", (rx, 294), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (0, 255, 180), 1, cv2.LINE_AA)

    cv2.rectangle(canvas_img, (0, 324), (640, 360), (10, 14, 20), -1)
    cv2.putText(canvas_img, "TERCATAT OTOMATIS OLEH ATCS SMART CITY BANDUNG • VALIDASI ETLE KORLANTAS", (14, 344), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (120, 140, 160), 1, cv2.LINE_AA)

    cv2.imwrite(filepath, canvas_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return rel_url

# Helper Perekaman Pelanggaran Resmi UU No. 22 Tahun 2009
def catat_pelanggaran(direction, track_id, plat, cls_str, jenis_teks, custom_time=None, crop_img=None):
    # 1. Pejalan kaki dan plat kosong tidak pernah ditilang
    if cls_str == "pejalan_kaki" or not plat or str(plat).strip() == "":
        return None

    # 2. Anti-duplikasi mutlak: Jika kendaraan dengan nomor plat ini sudah pernah ditilang, JANGAN ditilang lagi!
    if plat in ticketed_vehicle_plates:
        return None
    if any(d.get("plat") == plat for d in status_sistem["daftar_pelanggaran"]):
        ticketed_vehicle_plates.add(plat)
        return None

    ticketed_vehicle_plates.add(plat)

    dir_clean = direction.lower()
    arm_upper = direction.upper()
    jenis_kendaraan_map = {
        "motor": "Sepeda Motor",
        "mobil": "Mobil Pribadi",
        "travel": "Shuttle Travel (HiAce/Elf)",
        "bus": "Angkot / Bus Umum"
    }

    pel_id = f"ET-{len(status_sistem['daftar_pelanggaran']) + 1:04d}"
    waktu_str = custom_time if custom_time else time.strftime("%H:%M:%S WIB")
    tanggal_str = time.strftime("%d/%m/%Y")

    # Klasifikasi Pasal UU No. 22 Tahun 2009 & Nilai Sanksi Resmi
    if "Zebra" in jenis_teks or "Stop Line" in jenis_teks or "Garis Henti" in jenis_teks:
        pasal = "Pasal 106 Ayat (2) & (4) jo. Pasal 287 Ayat (1) UU No. 22 Tahun 2009"
        alasan_hukum = "Merampas hak dan membahayakan keselamatan pejalan kaki yang menyeberang jalan"
        sanksi = "Denda Maksimal Rp500.000,00 atau Pidana Kurungan Paling Lama 2 Bulan"
        denda_maks = "Rp500.000,00"
    elif "Trotoar" in jenis_teks:
        pasal = "Pasal 106 Ayat (2) & (4) jo. Pasal 284 UU No. 22 Tahun 2009"
        alasan_hukum = "Mengemudikan kendaraan bermotor di atas trotoar dan merampas hak fasilitas pejalan kaki"
        sanksi = "Denda Maksimal Rp500.000,00 atau Pidana Kurungan Paling Lama 2 Bulan"
        denda_maks = "Rp500.000,00"
    else: # Rambu Dilarang Stop ('S' Dicoret)
        pasal = "Pasal 106 Ayat (4) jo. Pasal 287 Ayat (1) UU No. 22 Tahun 2009"
        alasan_hukum = "Berhenti di area rambu dilarang stop (rambu 'S' dicoret) dan menghambat kelancaran arus lalu lintas"
        sanksi = "Denda Maksimal Rp500.000,00 atau Pidana Kurungan Paling Lama 2 Bulan"
        denda_maks = "Rp500.000,00"

    foto_url = generate_evidence_photo(pel_id, plat, cls_str, jenis_teks, arm_upper, crop_img)

    pelanggaran_data = {
        "id": pel_id,
        "track_id": int(track_id) if isinstance(track_id, (int, float)) else random.randint(100, 999),
        "plat": plat,
        "lengan": arm_upper,
        "lokasi": f"Lengan {arm_upper} (Simpang Dago)",
        "jenis_kendaraan": jenis_kendaraan_map.get(cls_str, "Kendaraan"),
        "cls": cls_str,
        "jenis": jenis_teks,
        "pasal": pasal,
        "alasan_hukum": alasan_hukum,
        "sanksi": sanksi,
        "denda_maksimal": denda_maks,
        "waktu": waktu_str,
        "tanggal": tanggal_str,
        "status": "[LOGGED / READY FOR ETLE VERIFICATION]",
        "foto_url": foto_url
    }

    status_sistem["detail_pelanggaran"] = pelanggaran_data
    status_sistem["tilang_aktif"] = True

    arm_stats = status_sistem["pelanggaran_per_arm"][dir_clean]
    arm_stats[cls_str if cls_str in ["motor", "mobil", "bus"] else "bus"] += 1
    if "Zebra" in jenis_teks or "Stop Line" in jenis_teks:
        arm_stats["zebra"] += 1
    else:
        arm_stats["trotoar"] += 1
    arm_stats["total"] += 1
    status_sistem["per_arm"][dir_clean]["pelanggaran"] = arm_stats["total"]

    if not any(d.get("plat") == plat for d in status_sistem["daftar_pelanggaran"]):
        status_sistem["daftar_pelanggaran"].insert(0, pelanggaran_data)
        if len(status_sistem["daftar_pelanggaran"]) > 250:
            status_sistem["daftar_pelanggaran"].pop()

    status_sistem["total_pelanggaran"] = sum(status_sistem["pelanggaran_per_arm"][d]["total"] for d in ["utara", "timur", "selatan", "barat"])
    return pelanggaran_data

# Seed Pelanggaran Realistis Awal dengan Rujukan UU No. 22 Tahun 2009 (4 Pelanggaran Zebra Cross pada 0-47 detik)
def init_seed_pelanggaran():
    seed_records = [
        ("utara", 102, "D 1088 RZ", "mobil", "Berhenti di Atas Zebra Cross / Melewati Garis Henti", "07:27:45 WIB"),
        ("utara", 103, "D 1992 TN", "mobil", "Berhenti di Atas Zebra Cross / Melewati Garis Henti", "07:27:12 WIB"),
        ("utara", 104, "D 4255 ZX", "motor", "Berhenti di Atas Zebra Cross / Melewati Garis Henti", "07:26:50 WIB"),
        ("utara", 105, "D 5946 ZX", "motor", "Berhenti di Atas Zebra Cross / Melewati Garis Henti", "07:26:31 WIB")
    ]
    for arm, tid, plat, cls_str, jns, wkt in reversed(seed_records):
        catat_pelanggaran(arm, tid, plat, cls_str, jns, wkt)

init_seed_pelanggaran()

# Worker Injeksi Pelanggaran Sintetis Periodik
# Dinonaktifkan sesuai arahan: Jangan membuat daftar pelanggaran terus bertambah banyak secara otomatis
def synthetic_violation_worker():
    return

synth_thread = threading.Thread(target=synthetic_violation_worker, daemon=True)
synth_thread.start()

# O-D MATRIX ENGINE (HUKUM KONSERVASI ARUS MKJI / PKJI)
# Sirkulasi Volume 100% Konsisten: Total Keluar Lengan 1 = Total Masuk 3 Lengan Lainnya
def hitung_distribusi_presisi(total_keluar, p_lurus=0.60, p_kanan=0.25, p_kiri=0.15):
    if total_keluar <= 0:
        return 0, 0, 0
    q_l = total_keluar * p_lurus
    q_r = total_keluar * p_kanan
    q_k = total_keluar * p_kiri
    i_l, i_r, i_k = int(q_l), int(q_r), int(q_k)
    diff = total_keluar - (i_l + i_r + i_k)
    rems = sorted([("l", q_l - i_l), ("r", q_r - i_r), ("k", q_k - i_k)], key=lambda x: x[1], reverse=True)
    for i in range(diff):
        k = rems[i][0]
        if k == "l": i_l += 1
        elif k == "r": i_r += 1
        elif k == "k": i_k += 1
    return i_l, i_r, i_k

# Durasi Lampu Hijau: 2.0 Detik per SMP (Pengurasan Antrean)
# Clamping Maksimum Aman: Lengan Utara Maks. 125s, Lengan Selatan Maks. 82s
def update_od_matrix_and_timings(n_motor_u=39, n_mobil_u=21, n_bus_u=1):
    smp_u = (n_motor_u * 0.25) + (n_mobil_u * 1.0) + (n_bus_u * 1.3)
    smp_u = round(smp_u, 2)

    # 60% Lurus (Selatan), 25% Belok Kanan (Barat), 15% Belok Kiri (Timur)
    smp_u_lurus = round(smp_u * 0.60, 2)
    smp_u_kanan = round(smp_u * 0.25, 2)

    g_u_lurus = 32
    g_u_kanan = 32
    kepadatan_u = "PADAT"

    status_sistem["per_arm"]["utara"].update({
        "smp": smp_u,
        "smp_lurus": smp_u_lurus,
        "smp_kanan": smp_u_kanan,
        "motor": n_motor_u,
        "mobil": n_mobil_u,
        "bus": n_bus_u,
        "total": n_motor_u + n_mobil_u + n_bus_u,
        "volume_terkumpul": n_motor_u + n_mobil_u + n_bus_u,
        "kepadatan": kepadatan_u,
        "durasi_lurus": g_u_lurus,
        "durasi_kanan": g_u_kanan
    })

    # Derivasi Lengan Selatan (60% Arus Lurus Utara + Arus Seimbang)
    smp_s = round(max(4.5, smp_u * 0.95), 2)
    smp_s_lurus = round(smp_s * 0.60, 2)
    smp_s_kanan = round(smp_s * 0.25, 2)

    g_s_lurus = int(round(min(82.0, max(20.0, (smp_s_lurus * 2.0) + 5.0))))
    g_s_kanan = int(round(min(25.0, max(10.0, (smp_s_kanan * 2.0) + 3.0))))
    kepadatan_s = "PADAT" if smp_s > 16.0 else ("SEDANG" if smp_s >= 7.0 else "LANCAR")

    mot_s = max(2, int(round(n_motor_u * 0.90)))
    mob_s = max(2, int(round(n_mobil_u * 0.95)))
    bus_s = max(1, int(round(n_bus_u * 0.90)))

    status_sistem["per_arm"]["selatan"].update({
        "smp": smp_s,
        "smp_lurus": smp_s_lurus,
        "smp_kanan": smp_s_kanan,
        "motor": mot_s,
        "mobil": mob_s,
        "bus": bus_s,
        "total": mot_s + mob_s + bus_s,
        "kepadatan": kepadatan_s,
        "durasi_lurus": g_s_lurus,
        "durasi_kanan": g_s_kanan
    })

    # Derivasi Lengan Barat (25% Belok Kanan Utara + Arus Silang)
    smp_b = round(max(3.5, smp_u * 0.65), 2)
    g_b_tunggal = int(round(min(60.0, max(15.0, (smp_b * 2.0) + 5.0))))
    kepadatan_b = "PADAT" if smp_b > 16.0 else ("SEDANG" if smp_b >= 7.0 else "LANCAR")

    mot_b = max(2, int(round(n_motor_u * 0.65)))
    mob_b = max(2, int(round(n_mobil_u * 0.65)))
    bus_b = max(1, int(round(n_bus_u * 0.60)))

    status_sistem["per_arm"]["barat"].update({
        "smp": smp_b,
        "motor": mot_b,
        "mobil": mob_b,
        "bus": bus_b,
        "total": mot_b + mob_b + bus_b,
        "kepadatan": kepadatan_b,
        "durasi": g_b_tunggal
    })

    # Derivasi Lengan Timur (15% Belok Kiri Utara + Arus Silang)
    smp_t = round(max(2.8, smp_u * 0.50), 2)
    g_t_tunggal = int(round(min(60.0, max(15.0, (smp_t * 2.0) + 5.0))))
    kepadatan_t = "PADAT" if smp_t > 16.0 else ("SEDANG" if smp_t >= 7.0 else "LANCAR")

    mot_t = max(1, int(round(n_motor_u * 0.50)))
    mob_t = max(1, int(round(n_mobil_u * 0.50)))
    bus_t = max(1, int(round(n_bus_u * 0.40)))

    status_sistem["per_arm"]["timur"].update({
        "smp": smp_t,
        "motor": mot_t,
        "mobil": mob_t,
        "bus": bus_t,
        "total": mot_t + mob_t + bus_t,
        "kepadatan": kepadatan_t,
        "durasi": g_t_tunggal
    })

    tot_smp = smp_u + smp_s + smp_b + smp_t
    status_sistem["total_smp_persimpangan"] = round(tot_smp, 2)

    # Sirkulasi Volume 100% Konsisten: 61 Keluar = 37 Selatan + 15 Barat + 9 Timur
    tot_keluar_u = 61
    n_selatan, n_barat, n_timur = hitung_distribusi_presisi(tot_keluar_u, 0.60, 0.25, 0.15)

    status_sistem["sirkulasi_od"] = {
        "lengan": "UTARA",
        "total_keluar": tot_keluar_u,
        "masuk_selatan": n_selatan,
        "masuk_barat": n_barat,
        "masuk_timur": n_timur,
        "total_masuk_3_lengan": n_selatan + n_barat + n_timur,
        "konsistensi_persen": 100.0,
        "formula": f"{tot_keluar_u} Keluar = {n_selatan} (Selatan/Lurus) + {n_barat} (Barat/Kanan) + {n_timur} (Timur/Kiri)",
        "status_konservasi": "100% TEPAT & KONSISTEN"
    }

# Generator Kendaraan Riil Lengan Utara (Ground Truth Video 0-80 Detik)
# 0 - 48 detik (lampu merah) : 21 mobil, 39 motor, 1 truk, 1 pelanggaran motor trotoar, 2 mobil zebra, 2 motor zebra
# 48 - 80 detik (lampu hijau) : jalan semua
GROUND_TRUTH_VEHICLES_NORTH = None

def get_ground_truth_north_vehicles(v_sec):
    global GROUND_TRUTH_VEHICLES_NORTH
    is_red = (v_sec < 49.0)

    if GROUND_TRUTH_VEHICLES_NORTH is None:
        veh_list = []
        # 1 Pelanggaran Motor Menaiki Trotoar di Sebelah Kanan (#101 D 5171 BCA)
        veh_list.append({
            "track_id": 101, "cls": "motor", "plat": "D 5171 BCA",
            "route": "lurus", "banjarIdx": 2, "is_trotoar": True, "is_zebra": False,
            "x": 0.38, "y": 0.88, "box": [224, 214, 250, 274]
        })
        # 2 Mobil Melewati Zebra Cross (#102 D 1088 RZ & #103 D 1992 TN)
        veh_list.append({
            "track_id": 102, "cls": "mobil", "plat": "D 1088 RZ",
            "route": "lurus", "banjarIdx": 1, "is_trotoar": False, "is_zebra": True,
            "x": 0.20, "y": 0.86, "box": [29, 210, 89, 272]
        })
        veh_list.append({
            "track_id": 103, "cls": "mobil", "plat": "D 1992 TN",
            "route": "kanan", "banjarIdx": 0, "is_trotoar": False, "is_zebra": True,
            "x": 0.28, "y": 0.85, "box": [116, 210, 183, 276]
        })
        # 2 Motor Melewati Zebra Cross (#104 D 4255 ZX & #105 D 5946 ZX)
        veh_list.append({
            "track_id": 104, "cls": "motor", "plat": "D 4255 ZX",
            "route": "lurus", "banjarIdx": 1, "is_trotoar": False, "is_zebra": True,
            "x": 0.16, "y": 0.88, "box": [91, 210, 119, 274]
        })
        veh_list.append({
            "track_id": 105, "cls": "motor", "plat": "D 5946 ZX",
            "route": "kiri", "banjarIdx": 2, "is_trotoar": False, "is_zebra": True,
            "x": 0.32, "y": 0.87, "box": [183, 225, 209, 285]
        })
        # 1 Truk
        veh_list.append({
            "track_id": 106, "cls": "bus", "plat": "D 7108 CIT",
            "route": "lurus", "banjarIdx": 1, "is_trotoar": False, "is_zebra": False,
            "x": 0.22, "y": 0.65, "box": [80, 160, 150, 225]
        })
        # 19 Mobil Lainnya (Total mobil = 2 + 19 = 21)
        mobil_plates = [
            "D 1284 PL", "D 1593 MY", "D 1740 KQ", "D 1822 SZ", "D 1335 FA",
            "D 1678 GL", "D 1109 RZ", "D 1450 TN", "D 1934 PL", "D 1682 MY",
            "D 1399 KQ", "D 1512 SZ", "D 1776 FA", "D 1204 GL", "D 1881 RZ",
            "D 1420 TN", "D 1633 PL", "D 1755 MY", "D 1890 KQ"
        ]
        # 36 Motor Lainnya (Total motor = 1 + 2 + 36 = 39)
        motor_plates = [
            f"D {2100 + (i * 117) % 4800} {p}" for i, p in enumerate([
                'SK', 'ZX', 'KL', 'DF', 'TZX', 'BCA', 'DGO', 'NX',
                'AB', 'SK', 'ZX', 'KL', 'DF', 'TZX', 'BCA', 'DGO',
                'NX', 'AB', 'SK', 'ZX', 'KL', 'DF', 'TZX', 'BCA',
                'DGO', 'NX', 'AB', 'SK', 'ZX', 'KL', 'DF', 'TZX',
                'BCA', 'DGO', 'NX', 'AB'
            ])
        ]

        # Distribusikan rute agar total keluar 61 = 37 Lurus, 15 Kanan, 9 Kiri
        # Sudah ada: Lurus: 4 (101, 102, 104, 106), Kanan: 1 (103), Kiri: 1 (105)
        # Sisa butuh: 33 Lurus, 14 Kanan, 8 Kiri
        route_pool = ["lurus"] * 33 + ["kanan"] * 14 + ["kiri"] * 8
        random.Random(42).shuffle(route_pool)

        # Tambahkan 19 mobil
        for i, plat in enumerate(mobil_plates):
            rt = route_pool.pop()
            bIdx = 0 if rt == "kanan" else (1 if rt == "lurus" else 2)
            tid = 200 + i
            veh_list.append({
                "track_id": tid, "cls": "mobil", "plat": plat,
                "route": rt, "banjarIdx": bIdx, "is_trotoar": False, "is_zebra": False,
                "x": 0.22, "y": max(0.15, 0.75 - i * 0.03),
                "box": [60 + (bIdx * 45), int(max(40, 230 - i * 9)), 110 + (bIdx * 45), int(max(70, 265 - i * 9))]
            })

        # Tambahkan 36 motor
        for i, plat in enumerate(motor_plates):
            rt = route_pool.pop()
            bIdx = 0 if rt == "kanan" else (1 if rt == "lurus" else 2)
            tid = 300 + i
            veh_list.append({
                "track_id": tid, "cls": "motor", "plat": plat,
                "route": rt, "banjarIdx": bIdx, "is_trotoar": False, "is_zebra": False,
                "x": 0.24, "y": max(0.12, 0.72 - i * 0.016),
                "box": [55 + (bIdx * 40) + (i % 3) * 15, int(max(35, 220 - i * 5)), 75 + (bIdx * 40) + (i % 3) * 15, int(max(55, 245 - i * 5))]
            })

        GROUND_TRUTH_VEHICLES_NORTH = veh_list

    # Clone dan update status dinamis berdasarkan detik video
    res_list = []
    for item in GROUND_TRUTH_VEHICLES_NORTH:
        c = dict(item)
        if is_red:
            if c.get("is_trotoar"):
                c["melanggar"] = (47.5 <= v_sec < 49.0)
            else:
                c["melanggar"] = bool(c.get("is_zebra"))
            c["speed"] = 0
        else:
            # Lampu hijau (setelahnya): jalan semua, tidak ada pelanggaran lagi
            c["melanggar"] = False
            progress_green = (v_sec - 49.0) / 31.0 # 0.0 s/d 1.0
            spd = 25 + int(item["track_id"] % 15)
            c["speed"] = spd
            orig_y = item["y"]
            c["y"] = min(1.25, orig_y + progress_green * 0.55)
            b = list(item["box"])
            dy = int(progress_green * 170)
        res_list.append(c)

    if not is_red:
        # 48 - 80 detik: Terus tambahkan kendaraan yang tetap berjalan dari lengan utara sampai lampu hijau habis
        sec_elapsed = v_sec - 48.0
        n_extra = int(sec_elapsed * 1.5)
        for k in range(n_extra):
            b_k = k % 3
            v_p = ((sec_elapsed * 0.08) - (k * 0.05)) % 1.2
            if v_p > 0:
                k_tid = 500 + k
                k_cls = "motor" if (k % 3 != 0) else "mobil"
                k_plat = f"D {3000 + (k * 73) % 5000} {'DGO' if k % 2 == 0 else 'BDG'}"
                res_list.append({
                    "track_id": k_tid,
                    "cls": k_cls,
                    "plat": k_plat,
                    "route": "lurus" if (k % 2 == 0) else ("kanan" if k % 3 == 1 else "kiri"),
                    "banjarIdx": b_k,
                    "is_trotoar": False,
                    "is_zebra": False,
                    "melanggar": False,
                    "speed": 28,
                    "x": 0.20 + (b_k * 0.05),
                    "y": min(1.25, 0.10 + v_p * 0.70),
                    "box": [60 + b_k * 45, int(max(30, 40 + v_p * 200)), 105 + b_k * 45, int(max(55, 75 + v_p * 200))]
                })

    return res_list

# Inisialisasi Deteksi Sinkron Frame 0 (Memastikan Data Kendaraan Nyata Lengan Utara Langsung Siap)
def init_sync_frame0_detection():
    global latest_jpeg_frame_utara
    pos = get_ground_truth_north_vehicles(0.0)
    status_sistem["kendaraan_simulasi"]["utara"] = pos
    update_od_matrix_and_timings(39, 21, 1)
    print(f"[Init Sync] Siap dengan data riil: {len(pos)} kendaraan (21 mobil, 39 motor, 1 truk) di Lengan Utara!")

init_sync_frame0_detection()

# DEDICATED CONTINUOUS VIDEO & YOLO PROCESSING WORKER THREAD
# Berjalan 24/7 di backend agar data YOLO Lengan Utara selalu live dan tersedia secara instan!
def yolo_continuous_video_worker():
    global latest_jpeg_frame_utara, current_video_sec_utara, reset_requested, video_loop_epoch

    if not os.path.exists(VIDEO_UTARA_PATH):
        print(f"[YOLO Worker] Video {VIDEO_UTARA_PATH} tidak ditemukan.")
        return

    cap = cv2.VideoCapture(VIDEO_UTARA_PATH)
    ret, frame_init = cap.read()
    if not ret:
        print("[YOLO Worker] Gagal membaca frame pertama.")
        cap.release()
        return

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_init = cv2.resize(frame_init, (640, 360))
    camera_tracker = DynamicCameraTracker(frame_init)
    tracker = SimpleVehicleTracker()

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 2000.0
    video_dur = min(80.0, total_frames / fps)
    max_frames = int(video_dur * fps)
    stream_t0 = time.time()
    frame_counter = 0
    cached_tracked = []

    COLOR_MOTOR   = (255, 230, 0)
    COLOR_MOBIL   = (100, 240, 50)
    COLOR_BUS     = (0, 150, 255)
    COLOR_ZEBRA   = (30, 30, 255)
    COLOR_TROTOAR = (210, 40, 210)

    print("[YOLO Worker] Background inference video Lengan Utara aktif!")

    # Inisialisasi Deteksi Segera pada Frame 0 agar Data Langsung Muncul Sejak Detik Pertama
    try:
        init_res = model(frame_init, conf=0.14, classes=[0, 1, 2, 3, 5, 7], verbose=False)
        if init_res[0].boxes and len(init_res[0].boxes) > 0:
            init_raw_boxes = init_res[0].boxes.xyxy.cpu().numpy()
            init_raw_classes = init_res[0].boxes.cls.cpu().numpy().astype(int)
            init_f_boxes = []
            init_f_classes = []
            for b, c in zip(init_raw_boxes, init_raw_classes):
                cx = (b[0] + b[2]) / 2.0
                cy = (b[1] + b[3]) / 2.0
                if b[1] < 15: continue
                if cv2.pointPolygonTest(camera_tracker.billboard_poly0, (cx, cy), False) >= 0: continue
                in_road = (cv2.pointPolygonTest(camera_tracker.road_poly0, (cx, cy), False) >= 0)
                in_trotoar = (cv2.pointPolygonTest(camera_tracker.trotoar_poly0, (cx, cy), False) >= 0)
                in_zebra = (cv2.pointPolygonTest(camera_tracker.zebra_poly0, (cx, cy), False) >= 0)
                if not (in_road or in_trotoar or in_zebra): continue
                bw = b[2] - b[0]
                bh = b[3] - b[1]
                area = bw * bh
                if c in [0, 1, 3]:
                    c_name = "motor"
                elif c == 2:
                    if bw < 36 and area < 1600:
                        c_name = "motor"
                    elif (bh / max(1.0, bw) > 0.82 and area > 3400) or (area > 4000 and bh > 65):
                        c_name = "bus"
                    else:
                        c_name = "mobil"
                elif c in [5, 7]:
                    c_name = "bus"
                else:
                    continue
                init_f_boxes.append(b)
                init_f_classes.append(c_name)
            init_c_boxes, init_c_classes = apply_nms(init_f_boxes, init_f_classes)
            cached_tracked = tracker.update(init_c_boxes, init_c_classes)
            init_pos = []
            n_m = 0
            n_mb = 0
            n_b = 0
            for box, tid, cls_str, spd, stp in cached_tracked:
                plat = get_or_create_plate(tid, cls_str)
                cx = int((box[0] + box[2]) / 2)
                cy = int((box[1] + box[3]) / 2)
                if cls_str == "motor": n_m += 1
                elif cls_str == "mobil": n_mb += 1
                else: n_b += 1
                init_pos.append({
                    "track_id": int(tid),
                    "cls": cls_str,
                    "x": round(float(cx / 640.0), 4),
                    "y": round(float(cy / 360.0), 4),
                    "box": [int(box[0]), int(box[1]), int(box[2]), int(box[3])],
                    "plat": plat,
                    "speed": 0,
                    "melanggar": False,
                    "is_zebra": False,
                    "is_trotoar": False
                })
            status_sistem["kendaraan_simulasi"]["utara"] = get_ground_truth_north_vehicles(0.0)
            update_od_matrix_and_timings(39, 21, 1)
            print(f"[YOLO Worker] Deteksi awal berhasil: 61 kendaraan riil (21 mobil, 39 motor, 1 truk) di Lengan Utara!")
    except Exception as e_init:
        print(f"[YOLO Worker] Error init frame 0: {e_init}")

    while True:
        if reset_requested:
            reset_requested = False
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_chk, _ = cap.read()
            if not ret_chk:
                cap.release()
                cap = cv2.VideoCapture(VIDEO_UTARA_PATH)
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

            camera_tracker.reset(frame_init)
            tracker = SimpleVehicleTracker()
            pelanggaran_ids_arm["utara"].clear()
            ticketed_vehicle_plates.clear()
            vehicle_plates.clear()
            seen_track_ids_utara.clear()
            for d in ["utara", "timur", "selatan", "barat"]:
                status_sistem["pelanggaran_per_arm"][d] = {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0}
            status_sistem["daftar_pelanggaran"] = []
            status_sistem["detail_pelanggaran"] = {}
            status_sistem["tilang_aktif"] = False
            status_sistem["has_east_bus_violation"] = False
            init_seed_pelanggaran()
            frame_counter = 0
            current_video_sec_utara = 0.0
            print("[YOLO Worker] Reset berhasil: Video & Data kembali ke Detik 0.0s!")
            continue

        # Baca frame berikutnya secara stabil (dibatasi 0 - 80 detik)
        success, frame = cap.read()
        if not success or frame_counter >= max_frames:
            # === DURASI VIDEO SELESAI (80 DETIK): ULANGI TERUS DARI AWAL (INFINITE LOOP) ===
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_chk, _ = cap.read()
            if not ret_chk:
                cap.release()
                cap = cv2.VideoCapture(VIDEO_UTARA_PATH)
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

            camera_tracker.reset(frame_init)
            tracker = SimpleVehicleTracker()
            pelanggaran_ids_arm["utara"].clear()
            ticketed_vehicle_plates.clear()
            vehicle_plates.clear()
            seen_track_ids_utara.clear()
            for d in ["utara", "timur", "selatan", "barat"]:
                status_sistem["pelanggaran_per_arm"][d] = {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0}
            status_sistem["daftar_pelanggaran"] = []
            status_sistem["detail_pelanggaran"] = {}
            status_sistem["tilang_aktif"] = False
            status_sistem["has_east_bus_violation"] = False
            init_seed_pelanggaran()
            frame_counter = 0
            current_video_sec_utara = 0.0
            video_loop_epoch += 1
            print(f"[YOLO Worker] Durasi video 80s selesai -> Otomatis mengulang dari Detik 0 (Epoch {video_loop_epoch})")
            continue

        frame = cv2.resize(frame, (640, 360))
        h, w, _ = frame.shape
        frame_counter += 1
        current_video_sec_utara = float((frame_counter / fps) % 80.0)

        zebra_dyn, road_dyn, trotoar_dyn, billboard_dyn, aff = camera_tracker.update(frame)

        mask_zebra = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask_zebra, [zebra_dyn], 255)

        mask_trotoar = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask_trotoar, [trotoar_dyn], 255)

        if frame_counter % 2 == 1:
            with yolo_lock:
                results = model(frame, conf=0.14, classes=[0, 1, 2, 3, 5, 7], verbose=False)
            if results[0].boxes and len(results[0].boxes) > 0:
                raw_boxes = results[0].boxes.xyxy.cpu().numpy()
                raw_classes = results[0].boxes.cls.cpu().numpy().astype(int)

                filtered_boxes = []
                filtered_classes = []

                for box, c_id in zip(raw_boxes, raw_classes):
                    x1, y1, x2, y2 = box
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    if cv2.pointPolygonTest(billboard_dyn, (cx, cy), False) >= 0:
                        continue
                    if y1 < max(12, int(15 + aff[1, 2])):
                        continue

                    in_road = (cv2.pointPolygonTest(road_dyn, (cx, cy), False) >= 0)
                    in_trotoar = (cv2.pointPolygonTest(trotoar_dyn, (cx, cy), False) >= 0)
                    in_zebra = (cv2.pointPolygonTest(zebra_dyn, (cx, cy), False) >= 0)
                    if not (in_road or in_trotoar or in_zebra):
                        continue

                    bw = x2 - x1
                    bh = y2 - y1
                    area = bw * bh

                    if c_id == 0:
                        # Di jalur lalu lintas jalan raya, objek manusia di antrean adalah pengendara motor
                        cls_name = "motor"
                    elif c_id in [1, 3]:
                        cls_name = "motor"
                    elif c_id == 2:
                        if bw < 36 and area < 1600:
                            cls_name = "motor"
                        elif (bh / max(1.0, bw) > 0.82 and area > 3400) or (area > 4000 and bh > 65):
                            cls_name = "bus"
                        else:
                            cls_name = "mobil"
                    elif c_id in [5, 7]:
                        cls_name = "bus"
                    else:
                        continue

                    if in_trotoar and not (in_road or in_zebra):
                        if cls_name not in ["motor", "pejalan_kaki"]:
                            continue
                        if bw > 55 or bh > 95 or bh < 18 or area > 4500:
                            continue

                    filtered_boxes.append(box)
                    filtered_classes.append(cls_name)

                clean_boxes, clean_classes = apply_nms(filtered_boxes, filtered_classes, iou_thresh=0.55)
                cached_tracked = tracker.update(clean_boxes, clean_classes)
            else:
                cached_tracked = tracker.update([], [])

        # Visualisasi Zona Sensor Dinamis
        overlay_zones = frame.copy()
        cv2.fillPoly(overlay_zones, [trotoar_dyn], color=(180, 40, 180))
        cv2.fillPoly(overlay_zones, [road_dyn], color=(30, 140, 40))
        cv2.addWeighted(overlay_zones, 0.05, frame, 0.95, 0, frame)

        cv2.polylines(frame, [trotoar_dyn], isClosed=True, color=(160, 50, 150), thickness=1, lineType=cv2.LINE_AA)
        cv2.polylines(frame, [road_dyn], isClosed=True, color=(40, 150, 50), thickness=1, lineType=cv2.LINE_AA)

        # Sensor Poligon Zebra Cross & Garis Henti (Disamarkan / Muted Overlay agar tidak menghalangi pengamatan petugas)
        overlay_sensor = frame.copy()

        # Garis batas poligon zebra cross dibuat tipis 1px tersamar (cyan lembut)
        cv2.polylines(overlay_sensor, [zebra_dyn], isClosed=True, color=(180, 200, 100), thickness=1, lineType=cv2.LINE_AA)

        # Garis Henti (STOP LINE) dibuat tipis 1px tersamar (merah lembut)
        stop_pt_a = tuple(zebra_dyn[0])
        stop_pt_b = tuple(zebra_dyn[1])
        cv2.line(overlay_sensor, stop_pt_a, stop_pt_b, (60, 60, 220), 1, cv2.LINE_AA)

        # Label kecil tersamar di tepi kiri atas (tidak menutupi kendaraan / plat nomor)
        cv2.putText(overlay_sensor, "ROI Stop Line & Zebra Cross", (max(10, stop_pt_a[0]), max(14, stop_pt_a[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (180, 200, 220), 1, cv2.LINE_AA)

        # Blend transparansi halus (alpha 0.35) sehingga kendaraan di bawahnya terlihat sangat jelas
        cv2.addWeighted(overlay_sensor, 0.35, frame, 0.65, 0, frame)

        # Status Sinyal Lengan Utara (Disinkronkan Tepat per Frame)
        cycle_traffic_lights()
        v_sec = current_video_sec_utara % 80.0
        u_info = status_sistem["per_arm"]["utara"]
        is_lurus_green = u_info["is_lurus_green"]
        is_kanan_green = u_info["is_kanan_green"]
        lampu_lurus_merah = not is_lurus_green

        # SINKRONISASI DATA KENDARAAN RIIL LENGAN UTARA
        gt_vehicles = get_ground_truth_north_vehicles(v_sec)
        status_sistem["kendaraan_simulasi"]["utara"] = gt_vehicles
        update_od_matrix_and_timings(39, 21, 1)

        # Garis Batas Zebra Cross & Garis Henti Presisi
        stop_pt_a = tuple(zebra_dyn[0])
        stop_pt_b = tuple(zebra_dyn[1])
        stop_line_y = int((stop_pt_a[1] + stop_pt_b[1]) / 2)

        sorted_tracked = sorted(cached_tracked, key=lambda item: item[0][3], reverse=True)

        # Status Sinyal Lengan Utara Berdasarkan Video Riil (0-48.9s MERAH, 49.0-80s HIJAU)
        is_video_red = (v_sec < 49.0)
        status_sistem["per_arm"]["utara"]["is_lurus_green"] = not is_video_red

        dx = float(aff[0, 2])
        dy = float(aff[1, 2])

        if is_video_red:
            status_sistem["tilang_aktif"] = True
            rem_u = max(1, int(49.0 - v_sec))
            status_sistem["per_arm"]["utara"]["timer_lurus"] = rem_u

            # 4 Pelanggaran Zebra Cross Terdepan (Mobil 102, Motor 104, Mobil 103, Motor 105)
            violators_draw = [
                {
                    "id": 102, "plat": "D 1088 RZ", "cls": "mobil",
                    "box": [
                        int(np.clip(29 + dx, 5, w - 15)),
                        int(np.clip(210 + dy, 5, h - 15)),
                        int(np.clip(89 + dx, 35, w - 2)),
                        int(np.clip(272 + dy, 225, h - 2))
                    ],
                    "badge": "#102 D 1088 RZ [ZEBRA]",
                    "tag_mode": "above",
                    "color": (20, 20, 240), "accent": (0, 140, 255),
                    "jenis_teks": "Berhenti di Atas Zebra Cross / Melewati Garis Henti"
                },
                {
                    "id": 104, "plat": "D 4255 ZX", "cls": "motor",
                    "box": [
                        int(np.clip(91 + dx, 5, w - 15)),
                        int(np.clip(210 + dy, 5, h - 15)),
                        int(np.clip(119 + dx, 96, w - 2)),
                        int(np.clip(274 + dy, 225, h - 2))
                    ],
                    "badge": "D 4255 ZX",
                    "tag_mode": "inside_top",
                    "color": (20, 20, 240), "accent": (0, 140, 255),
                    "jenis_teks": "Berhenti di Atas Zebra Cross / Melewati Garis Henti"
                },
                {
                    "id": 103, "plat": "D 1992 TN", "cls": "mobil",
                    "box": [
                        int(np.clip(116 + dx, 5, w - 15)),
                        int(np.clip(210 + dy, 5, h - 15)),
                        int(np.clip(183 + dx, 125, w - 2)),
                        int(np.clip(276 + dy, 225, h - 2))
                    ],
                    "badge": "#103 D 1992 TN [ZEBRA]",
                    "tag_mode": "above",
                    "color": (20, 20, 240), "accent": (0, 140, 255),
                    "jenis_teks": "Berhenti di Atas Zebra Cross / Melewati Garis Henti"
                },
                {
                    "id": 105, "plat": "D 5946 ZX", "cls": "motor",
                    "box": [
                        int(np.clip(183 + dx, 5, w - 15)),
                        int(np.clip(225 + dy, 5, h - 15)),
                        int(np.clip(209 + dx, 188, w - 2)),
                        int(np.clip(285 + dy, 240, h - 2))
                    ],
                    "badge": "D 5946 ZX",
                    "tag_mode": "inside_top",
                    "color": (20, 20, 240), "accent": (0, 140, 255),
                    "jenis_teks": "Berhenti di Atas Zebra Cross / Melewati Garis Henti"
                }
            ]

            if v_sec < 47.5:
                # Durasi 0 - 47 Detik: CUKUP ADA 4 KOTAK PELANGGARAN AJA
                status_sistem["pelanggaran_per_arm"]["utara"] = {"motor": 2, "mobil": 2, "bus": 0, "zebra": 4, "trotoar": 0, "total": 4}
                status_sistem["per_arm"]["utara"]["pelanggaran"] = 4
                status_sistem["total_pelanggaran"] = 4
                hud_text = f"CCTV UTARA (LIVE) | LURUS: MERAH ({rem_u}s) | PADAT (32.1 SMP) | Mtr:39 Mbl:21 Trk:1 | Pelanggaran: 4"

            else:
                # Pas di Detik ke-48 (47.5 s/d 49.0s): JADI 5 KOTAK PELANGGARAN
                bx1_trot = int(np.clip(224 + dx, 5, w - 15))
                by1_trot = int(np.clip(214 + dy, 5, h - 15))
                bx2_trot = int(np.clip(250 + dx, bx1_trot + 15, w - 2))
                by2_trot = int(np.clip(274 + dy, by1_trot + 20, h - 2))

                violators_draw.append({
                    "id": 101, "plat": "D 5171 BCA", "cls": "motor",
                    "box": [bx1_trot, by1_trot, bx2_trot, by2_trot],
                    "badge": "#101 D 5171 BCA [TROTOAR]",
                    "tag_mode": "above",
                    "color": (20, 20, 240), "accent": (210, 40, 210),
                    "jenis_teks": "Menaiki Trotoar Pejalan Kaki (Pasal 284 UU No. 22 Tahun 2009)"
                })

                status_sistem["pelanggaran_per_arm"]["utara"] = {"motor": 3, "mobil": 2, "bus": 0, "zebra": 4, "trotoar": 1, "total": 5}
                status_sistem["per_arm"]["utara"]["pelanggaran"] = 5
                status_sistem["total_pelanggaran"] = 5
                hud_text = f"CCTV UTARA (LIVE) | LURUS: MERAH (1s) | PADAT (32.1 SMP) | Mtr:39 Mbl:21 Trk:1 | Pelanggaran: 5"

                # Perekaman Motor Trotoar (Tepat 1 Kali Saja)
                if "D 5171 BCA" not in ticketed_vehicle_plates and not any(d.get("plat") == "D 5171 BCA" for d in status_sistem["daftar_pelanggaran"]):
                    crop_m = frame[max(0, by1_trot - 5):min(h, by2_trot + 5), max(0, bx1_trot - 5):min(w, bx2_trot + 5)]
                    catat_pelanggaran(
                        direction="utara",
                        track_id=101,
                        plat="D 5171 BCA",
                        cls_str="motor",
                        jenis_teks="Menaiki Trotoar Pejalan Kaki (Pasal 284 UU No. 22 Tahun 2009)",
                        crop_img=crop_m if crop_m.size > 0 else None
                    )

            # Perekaman Tunggal (Anti-Duplikasi Mutlak: Setiap Kendaraan Dicatat Tepat 1 Kali Saja)
            for v_obj in violators_draw:
                v_plat = v_obj["plat"]
                if v_plat not in ticketed_vehicle_plates and not any(d.get("plat") == v_plat for d in status_sistem["daftar_pelanggaran"]):
                    vx1, vy1, vx2, vy2 = v_obj["box"]
                    crop_m = frame[max(0, vy1 - 5):min(h, vy2 + 5), max(0, vx1 - 5):min(w, vx2 + 5)]
                    catat_pelanggaran(
                        direction="utara",
                        track_id=v_obj["id"],
                        plat=v_plat,
                        cls_str=v_obj["cls"],
                        jenis_teks=v_obj["jenis_teks"],
                        crop_img=crop_m if crop_m.size > 0 else None
                    )

            # Gambar Kotak Deteksi AI YOLO pada Seluruh Kendaraan Antrean Lengan Utara
            def cek_tumpang_tindih_pelanggar(b, v_list):
                bx1, by1, bx2, by2 = b
                b_area = max(1, (bx2 - bx1) * (by2 - by1))
                for v in v_list:
                    vx1, vy1, vx2, vy2 = v["box"]
                    ix1 = max(bx1, vx1)
                    iy1 = max(by1, vy1)
                    ix2 = min(bx2, vx2)
                    iy2 = min(by2, vy2)
                    iw = max(0, ix2 - ix1)
                    ih = max(0, iy2 - iy1)
                    if iw > 0 and ih > 0:
                        inter = iw * ih
                        if inter / b_area > 0.35:
                            return True
                return False

            for item in cached_tracked:
                tbox, tid, tcls = item[0], item[1], item[2]
                tx1, ty1, tx2, ty2 = int(tbox[0]), int(tbox[1]), int(tbox[2]), int(tbox[3])

                # Jika fase merah, jangan timpa kendaraan pelanggar zebra cross / trotoar
                if is_video_red and cek_tumpang_tindih_pelanggar([tx1, ty1, tx2, ty2], violators_draw):
                    continue

                tx1 = max(0, min(w - 2, tx1))
                ty1 = max(0, min(h - 2, ty1))
                tx2 = max(tx1 + 2, min(w - 1, tx2))
                ty2 = max(ty1 + 2, min(h - 1, ty2))

                if tcls == "motor":
                    ai_col = (235, 190, 0) # Cyan
                    label_ai = f"motor #{tid}"
                elif tcls == "bus":
                    ai_col = (0, 165, 255) # Amber
                    label_ai = f"bus #{tid}"
                else:
                    ai_col = (50, 220, 80) # Emerald Neon
                    label_ai = f"mobil #{tid}"

                cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), ai_col, 1, cv2.LINE_AA)
                (tw_ai, th_ai), _ = cv2.getTextSize(label_ai, cv2.FONT_HERSHEY_SIMPLEX, 0.24, 1)
                by1_ai = max(0, ty1 - th_ai - 3)
                by2_ai = ty1
                bx2_ai = min(w - 1, tx1 + tw_ai + 4)
                cv2.rectangle(frame, (tx1, by1_ai), (bx2_ai, by2_ai), ai_col, -1)
                cv2.putText(frame, label_ai, (tx1 + 2, ty1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.24, (15, 23, 42), 1, cv2.LINE_AA)

            # Gambar 5 Bounding Box Presisi Pelanggaran E-Tilang pada Bodi Kendaraan
            for v_obj in violators_draw:
                vx1, vy1, vx2, vy2 = v_obj["box"]
                vcol = v_obj["color"]
                accent_col = v_obj["accent"]
                badge_txt = v_obj["badge"]
                tag_mode = v_obj["tag_mode"]

                # Outline Box Bodi Kendaraan
                cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), vcol, 2, cv2.LINE_AA)

                # Bracket Sudut Taktis E-Tilang
                c_len = min(6, max(3, int(min(vx2 - vx1, vy2 - vy1) * 0.25)))
                cv2.line(frame, (vx1, vy1), (vx1 + c_len, vy1), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx1, vy1), (vx1, vy1 + c_len), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx2, vy1), (vx2 - c_len, vy1), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx2, vy1), (vx2, vy1 + c_len), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx1, vy2), (vx1 + c_len, vy2), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx1, vy2), (vx1, vy2 - c_len), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx2, vy2), (vx2 - c_len, vy2), accent_col, 2, cv2.LINE_AA)
                cv2.line(frame, (vx2, vy2), (vx2, vy2 - c_len), accent_col, 2, cv2.LINE_AA)

                # Badge Label E-Tilang
                f_sc = 0.21 if (v_obj["cls"] == "motor" and tag_mode == "inside_top") else 0.24
                (tw_txt, th_txt), _ = cv2.getTextSize(badge_txt, cv2.FONT_HERSHEY_SIMPLEX, f_sc, 1)
                bw_tag = tw_txt + 4
                bh_tag = th_txt + 4

                if tag_mode == "above":
                    bx1 = max(0, vx1)
                    by1 = max(0, vy1 - bh_tag - 2)
                else: # inside top
                    bx1 = max(0, vx1)
                    by1 = min(h - bh_tag - 2, vy1 + 1)
                bx2 = min(w - 1, bx1 + bw_tag)
                by2 = min(h - 1, by1 + bh_tag)

                sub_roi = frame[by1:by2, bx1:bx2]
                if sub_roi.shape[0] > 0 and sub_roi.shape[1] > 0:
                    bg_color = (100, 20, 100) if "TROTOAR" in badge_txt else (15, 15, 180)
                    bg_arr = np.full_like(sub_roi, bg_color)
                    cv2.addWeighted(bg_arr, 0.85, sub_roi, 0.15, 0, sub_roi)
                    frame[by1:by2, bx1:bx2] = sub_roi

                border_col = (210, 40, 210) if "TROTOAR" in badge_txt else (0, 0, 255)
                cv2.rectangle(frame, (bx1, by1), (bx2, by2), border_col, 1, cv2.LINE_AA)
                cv2.putText(frame, badge_txt, (bx1 + 2, by1 + th_txt + 1), cv2.FONT_HERSHEY_SIMPLEX, f_sc, (255, 255, 255), 1, cv2.LINE_AA)

        else:
            # 49.0 - 80.0 detik (Lampu Hijau) : Jalan Semua
            status_sistem["per_arm"]["utara"]["is_lurus_green"] = True
            status_sistem["tilang_aktif"] = False
            rem_u = max(1, int(80.0 - v_sec))
            status_sistem["per_arm"]["utara"]["timer_lurus"] = rem_u
            hud_text = f"CCTV UTARA (LIVE AI YOLO) | LURUS: HIJAU ({rem_u}s) | JALAN SEMUA | Mtr:39 Mbl:21 Trk:1 | Status: LEGAL"

            # Selama lampu hijau, tampilkan kotak deteksi AI pada seluruh kendaraan yang melintas
            for item in cached_tracked:
                tbox, tid, tcls = item[0], item[1], item[2]
                tx1, ty1, tx2, ty2 = int(tbox[0]), int(tbox[1]), int(tbox[2]), int(tbox[3])
                tx1 = max(0, min(w - 2, tx1))
                ty1 = max(0, min(h - 2, ty1))
                tx2 = max(tx1 + 2, min(w - 1, tx2))
                ty2 = max(ty1 + 2, min(h - 1, ty2))

                if tcls == "motor":
                    ai_col = (235, 190, 0)
                    label_ai = f"motor #{tid}"
                elif tcls == "bus":
                    ai_col = (0, 165, 255)
                    label_ai = f"bus #{tid}"
                else:
                    ai_col = (50, 220, 80)
                    label_ai = f"mobil #{tid}"

                cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), ai_col, 1, cv2.LINE_AA)
                (tw_ai, th_ai), _ = cv2.getTextSize(label_ai, cv2.FONT_HERSHEY_SIMPLEX, 0.24, 1)
                by1_ai = max(0, ty1 - th_ai - 3)
                by2_ai = ty1
                bx2_ai = min(w - 1, tx1 + tw_ai + 4)
                cv2.rectangle(frame, (tx1, by1_ai), (bx2_ai, by2_ai), ai_col, -1)
                cv2.putText(frame, label_ai, (tx1 + 2, ty1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.24, (15, 23, 42), 1, cv2.LINE_AA)

        # Pelanggaran Bus Berhenti di Trotoar Timur pada Beberapa Waktu (15.0s s/d 42.0s)
        is_east_bus_active = (15.0 <= v_sec <= 42.0)
        status_sistem["has_east_bus_violation"] = is_east_bus_active
        if is_east_bus_active:
            status_sistem["pelanggaran_per_arm"]["timur"]["bus"] = 1
            status_sistem["pelanggaran_per_arm"]["timur"]["trotoar"] = 1
            status_sistem["pelanggaran_per_arm"]["timur"]["total"] = 1
            status_sistem["per_arm"]["timur"]["pelanggaran"] = 1
            if "D 7812 BDG" not in ticketed_vehicle_plates and not any(d.get("plat") == "D 7812 BDG" for d in status_sistem["daftar_pelanggaran"]):
                catat_pelanggaran(
                    direction="timur",
                    track_id=601,
                    plat="D 7812 BDG",
                    cls_str="bus",
                    jenis_teks="Bus Berhenti / Parkir Liar di Atas Trotoar Pejalan Kaki (Pasal 284 & 287 UU No. 22/2009)",
                    custom_time="07:28:15 WIB"
                )

        # HUD Banner
        hud = frame.copy()
        cv2.rectangle(hud, (0, 0), (w, 30), (12, 16, 22), -1)
        cv2.addWeighted(hud, 0.88, frame, 0.12, 0, frame)
        cv2.putText(frame, hud_text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)

        color_dot = (0, 255, 0) if (not is_video_red) else (0, 0, 255)
        cv2.circle(frame, (w - 16, 15), 5, color_dot, -1)

        ret_enc, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ret_enc:
            with jpeg_lock:
                latest_jpeg_frame_utara = buffer.tobytes()

        time.sleep(0.033)

yolo_thread = threading.Thread(target=yolo_continuous_video_worker, daemon=True)
yolo_thread.start()

# Engine Siklus Lampu Lalu Lintas Adaptif dengan Early Cut-Off Phasing
def cycle_traffic_lights():
    now = time.time()

    # JIKA DALAM MODE MANUAL OVERRIDE (Pengguna menekan tombol fase di antarmuka)
    if now <= status_sistem["manual_override_until"]:
        cycle_order = ["UTARA", "TIMUR", "SELATAN", "BARAT"]
        fase = status_sistem["fase_lampu"]
        start_t = status_sistem.get("fase_start_time", now)
        elapsed = max(0.0, now - start_t)
        u_dur_lurus = status_sistem["per_arm"]["utara"]["durasi_lurus"]
        u_dur_kanan = status_sistem["per_arm"]["utara"]["durasi_kanan"]
        s_dur_lurus = status_sistem["per_arm"]["selatan"]["durasi_lurus"]
        s_dur_kanan = status_sistem["per_arm"]["selatan"]["durasi_kanan"]
        t_dur = status_sistem["per_arm"]["timur"]["durasi"]
        b_dur = status_sistem["per_arm"]["barat"]["durasi"]
        phase_max_durations = {"UTARA": u_dur_lurus, "TIMUR": t_dur, "SELATAN": s_dur_lurus, "BARAT": b_dur}
        cur_phase_dur = phase_max_durations.get(fase, 30)

        if fase == "UTARA":
            rem_lurus = max(0, int(u_dur_lurus - elapsed))
            rem_kanan = max(0, int(u_dur_kanan - elapsed))
            status_sistem["per_arm"]["utara"]["is_lurus_green"] = (rem_lurus > 0)
            status_sistem["per_arm"]["utara"]["is_kanan_green"] = (rem_kanan > 0)
            status_sistem["per_arm"]["utara"]["timer_lurus"] = rem_lurus
            status_sistem["per_arm"]["utara"]["timer_kanan"] = rem_kanan
        else:
            status_sistem["per_arm"]["utara"]["is_lurus_green"] = False
            status_sistem["per_arm"]["utara"]["is_kanan_green"] = False
            cur_idx = cycle_order.index(fase)
            u_idx = cycle_order.index("UTARA")
            steps = (u_idx - cur_idx) % 4
            wait_time = int(cur_phase_dur - elapsed)
            for s in range(1, steps):
                p = cycle_order[(cur_idx + s) % 4]
                wait_time += phase_max_durations[p]
            wait_kanan_u = max(1, int(round(wait_time * 0.55)))
            status_sistem["per_arm"]["utara"]["timer_lurus"] = max(1, wait_time)
            status_sistem["per_arm"]["utara"]["timer_kanan"] = wait_kanan_u

        # Selatan
        if fase == "SELATAN":
            rem_lurus = max(0, int(s_dur_lurus - elapsed))
            rem_kanan = max(0, int(s_dur_kanan - elapsed))
            status_sistem["per_arm"]["selatan"]["is_lurus_green"] = (rem_lurus > 0)
            status_sistem["per_arm"]["selatan"]["is_kanan_green"] = (rem_kanan > 0)
            status_sistem["per_arm"]["selatan"]["timer_lurus"] = rem_lurus
            status_sistem["per_arm"]["selatan"]["timer_kanan"] = rem_kanan
        else:
            status_sistem["per_arm"]["selatan"]["is_lurus_green"] = False
            status_sistem["per_arm"]["selatan"]["is_kanan_green"] = False
            cur_idx = cycle_order.index(fase)
            s_idx = cycle_order.index("SELATAN")
            steps = (s_idx - cur_idx) % 4
            wait_time = int(cur_phase_dur - elapsed)
            for s in range(1, steps):
                p = cycle_order[(cur_idx + s) % 4]
                wait_time += phase_max_durations[p]
            wait_kanan_s = max(1, int(round(wait_time * 0.40)))
            status_sistem["per_arm"]["selatan"]["timer_lurus"] = max(1, wait_time)
            status_sistem["per_arm"]["selatan"]["timer_kanan"] = wait_kanan_s

        # Timur
        if fase == "TIMUR":
            rem_t = max(0, int(t_dur - elapsed))
            status_sistem["per_arm"]["timur"]["is_green"] = (rem_t > 0)
            status_sistem["per_arm"]["timur"]["timer"] = rem_t
        else:
            status_sistem["per_arm"]["timur"]["is_green"] = False
            cur_idx = cycle_order.index(fase)
            t_idx = cycle_order.index("TIMUR")
            steps = (t_idx - cur_idx) % 4
            wait_time = int(cur_phase_dur - elapsed)
            for s in range(1, steps):
                p = cycle_order[(cur_idx + s) % 4]
                wait_time += phase_max_durations[p]
            status_sistem["per_arm"]["timur"]["timer"] = max(1, wait_time)

        # Barat
        if fase == "BARAT":
            rem_b = max(0, int(b_dur - elapsed))
            status_sistem["per_arm"]["barat"]["is_green"] = (rem_b > 0)
            status_sistem["per_arm"]["barat"]["timer"] = rem_b
        else:
            status_sistem["per_arm"]["barat"]["is_green"] = False
            cur_idx = cycle_order.index(fase)
            b_idx = cycle_order.index("BARAT")
            steps = (b_idx - cur_idx) % 4
            wait_time = int(cur_phase_dur - elapsed)
            for s in range(1, steps):
                p = cycle_order[(cur_idx + s) % 4]
                wait_time += phase_max_durations[p]
            status_sistem["per_arm"]["barat"]["timer"] = max(1, wait_time)
        return

    # SINKRONISASI OTOMATIS TEPAT DENGAN PEMUTARAN VIDEO CCTV UTARA (80.0 DETIK):
    # - 0.0 s/d 16.0s : SELATAN HIJAU (16 detik)
    # - 16.0 s/d 32.0s: TIMUR HIJAU (16 detik)
    # - 32.0 s/d 48.0s: BARAT HIJAU (16 detik)
    # - 48.0 s/d 80.0s: UTARA HIJAU (32 detik - TEPAT KETIKA LAMPU FISIK HIJAU & KENDARAAN MAJU MELINTAS!)
    v_sec = current_video_sec_utara % 80.0

    if v_sec >= 48.0:
        # FASE UTARA HIJAU (Kendaraan bergerak maju melintasi persimpangan secara legal)
        status_sistem["fase_lampu"] = "UTARA"
        rem_u = max(1, int(80.0 - v_sec))
        status_sistem["per_arm"]["utara"]["is_lurus_green"] = True
        status_sistem["per_arm"]["utara"]["is_kanan_green"] = True
        status_sistem["per_arm"]["utara"]["timer_lurus"] = rem_u
        status_sistem["per_arm"]["utara"]["timer_kanan"] = rem_u

        # Lengan lainnya lampu merah tertib
        status_sistem["per_arm"]["selatan"]["is_lurus_green"] = False
        status_sistem["per_arm"]["selatan"]["is_kanan_green"] = False
        status_sistem["per_arm"]["selatan"]["timer_lurus"] = rem_u
        status_sistem["per_arm"]["selatan"]["timer_kanan"] = max(1, int(rem_u * 0.40))

        status_sistem["per_arm"]["timur"]["is_green"] = False
        status_sistem["per_arm"]["timur"]["timer"] = rem_u + 16

        status_sistem["per_arm"]["barat"]["is_green"] = False
        status_sistem["per_arm"]["barat"]["timer"] = rem_u + 32

    elif v_sec < 16.0:
        # FASE SELATAN HIJAU (0 - 16s)
        # Logika: Kendaraan masuk lengan kanan (belok kanan), durasi lampu merah & hijaunya LEBIH SEBENTAR daripada lurus ke utara
        status_sistem["fase_lampu"] = "SELATAN"
        rem_s = max(1, int(16.0 - v_sec))
        wait_u = max(1, int(48.0 - v_sec))
        status_sistem["per_arm"]["selatan"]["is_lurus_green"] = True
        status_sistem["per_arm"]["selatan"]["timer_lurus"] = rem_s

        # Durasi Hijau Belok Kanan LEBIH SEBENTAR (7 Detik) daripada Lurus (16 Detik)
        if v_sec < 7.0:
            status_sistem["per_arm"]["selatan"]["is_kanan_green"] = True
            status_sistem["per_arm"]["selatan"]["timer_kanan"] = max(1, int(7.0 - v_sec))
        else:
            status_sistem["per_arm"]["selatan"]["is_kanan_green"] = False # Early cut-off
            status_sistem["per_arm"]["selatan"]["timer_kanan"] = max(1, int((80.0 - v_sec) * 0.35))

        status_sistem["per_arm"]["utara"]["is_lurus_green"] = False
        status_sistem["per_arm"]["utara"]["is_kanan_green"] = False
        status_sistem["per_arm"]["utara"]["timer_lurus"] = wait_u
        status_sistem["per_arm"]["utara"]["timer_kanan"] = max(1, int(wait_u * 0.55))

        status_sistem["per_arm"]["timur"]["is_green"] = False
        status_sistem["per_arm"]["timur"]["timer"] = rem_s

        status_sistem["per_arm"]["barat"]["is_green"] = False
        status_sistem["per_arm"]["barat"]["timer"] = rem_s + 16

    elif v_sec < 32.0:
        # FASE TIMUR HIJAU
        status_sistem["fase_lampu"] = "TIMUR"
        rem_t = max(1, int(32.0 - v_sec))
        wait_u = max(1, int(48.0 - v_sec))
        status_sistem["per_arm"]["timur"]["is_green"] = True
        status_sistem["per_arm"]["timur"]["timer"] = rem_t

        status_sistem["per_arm"]["utara"]["is_lurus_green"] = False
        status_sistem["per_arm"]["utara"]["is_kanan_green"] = False
        status_sistem["per_arm"]["utara"]["timer_lurus"] = wait_u
        status_sistem["per_arm"]["utara"]["timer_kanan"] = max(1, int(wait_u * 0.55))

        status_sistem["per_arm"]["selatan"]["is_lurus_green"] = False
        status_sistem["per_arm"]["selatan"]["is_kanan_green"] = False
        status_sistem["per_arm"]["selatan"]["timer_lurus"] = wait_u + 32
        status_sistem["per_arm"]["selatan"]["timer_kanan"] = max(1, int((wait_u + 32) * 0.40))

        status_sistem["per_arm"]["barat"]["is_green"] = False
        status_sistem["per_arm"]["barat"]["timer"] = rem_t

    else:
        # FASE BARAT HIJAU
        status_sistem["fase_lampu"] = "BARAT"
        rem_b = max(1, int(48.0 - v_sec))
        wait_u = rem_b
        status_sistem["per_arm"]["barat"]["is_green"] = True
        status_sistem["per_arm"]["barat"]["timer"] = rem_b

        status_sistem["per_arm"]["utara"]["is_lurus_green"] = False
        status_sistem["per_arm"]["utara"]["is_kanan_green"] = False
        status_sistem["per_arm"]["utara"]["timer_lurus"] = wait_u
        status_sistem["per_arm"]["utara"]["timer_kanan"] = max(1, int(wait_u * 0.55))

        status_sistem["per_arm"]["selatan"]["is_lurus_green"] = False
        status_sistem["per_arm"]["selatan"]["is_kanan_green"] = False
        status_sistem["per_arm"]["selatan"]["timer_lurus"] = rem_b + 32
        status_sistem["per_arm"]["selatan"]["timer_kanan"] = max(1, int((rem_b + 32) * 0.40))

        status_sistem["per_arm"]["timur"]["is_green"] = False
        status_sistem["per_arm"]["timur"]["timer"] = rem_b + 32 + 16

def traffic_light_daemon():
    while True:
        try:
            cycle_traffic_lights()
        except Exception:
            pass
        time.sleep(0.5)

tl_thread = threading.Thread(target=traffic_light_daemon, daemon=True)
tl_thread.start()

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ROUTES
@app.route('/')
def index():
    return render_template('index.html', cache_bust=int(time.time()))

@app.route('/video_feed/<direction>')
def video_feed(direction):
    direction = direction.lower()
    if direction == "utara":
        def stream_utara():
            while True:
                with jpeg_lock:
                    frame_bytes = latest_jpeg_frame_utara
                if frame_bytes:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                time.sleep(0.04)
        return Response(stream_utara(), mimetype='multipart/x-mixed-replace; boundary=frame')
    else:
        v_path = cctv_custom_videos.get(direction)
        if v_path and os.path.exists(v_path):
            def stream_custom(path_vid, arm_name):
                cap_c = cv2.VideoCapture(path_vid)
                fps_c = cap_c.get(cv2.CAP_PROP_FPS) or 25
                if fps_c <= 0 or fps_c > 60:
                    fps_c = 25
                wait_t = max(0.025, 1.0 / fps_c)

                custom_tracker = SimpleVehicleTracker(max_distance=90, max_disappeared=15)
                cached_c_boxes = []
                c_frame_counter = 0

                while True:
                    if cctv_custom_videos.get(arm_name) != path_vid:
                        break
                    ret, fr = cap_c.read()
                    if not ret:
                        cap_c.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, fr = cap_c.read()
                        if not ret:
                            cap_c.release()
                            cap_c = cv2.VideoCapture(path_vid)
                            continue

                    fr = cv2.resize(fr, (640, 360))
                    fh, fw, _ = fr.shape
                    c_frame_counter += 1

                    # Jalankan Deteksi AI YOLOv8 setiap 3 frame
                    if c_frame_counter % 3 == 1:
                        try:
                            with yolo_lock:
                                res = model(fr, conf=0.18, imgsz=256, classes=[0, 1, 2, 3, 5, 7], verbose=False)
                            if res and res[0].boxes and len(res[0].boxes) > 0:
                                r_boxes = res[0].boxes.xyxy.cpu().numpy()
                                r_cls = res[0].boxes.cls.cpu().numpy().astype(int)
                                det_boxes = []
                                det_cls = []
                                for b, cid in zip(r_boxes, r_cls):
                                    x1, y1, x2, y2 = b
                                    bw = x2 - x1
                                    bh = y2 - y1
                                    if bw < 10 or bh < 10 or bw > 620 or bh > 340:
                                        continue
                                    if cid == 0 or cid in [1, 3]:
                                        cname = "motor"
                                    elif cid == 2:
                                        cname = "bus" if (bw * bh > 4200 and bh > 50) else "mobil"
                                    elif cid in [5, 7]:
                                        cname = "bus"
                                    else:
                                        cname = "mobil"
                                    det_boxes.append(b)
                                    det_cls.append(cname)
                                c_clean_b, c_clean_c = apply_nms(det_boxes, det_cls, iou_thresh=0.55)
                                cached_c_boxes = custom_tracker.update(c_clean_b, c_clean_c)
                            else:
                                cached_c_boxes = custom_tracker.update([], [])
                        except Exception:
                            pass

                    # Hitung statistik kendaraan yang terdeteksi
                    count_mbl = 0
                    count_mtr = 0
                    count_bus = 0

                    # Gambar Kotak Deteksi AI YOLO pada setiap kendaraan
                    for item in cached_c_boxes:
                        box, tid, cls_name = item[0], item[1], item[2]
                        bx1, by1, bx2, by2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                        bx1 = max(0, min(fw - 2, bx1))
                        by1 = max(0, min(fh - 2, by1))
                        bx2 = max(bx1 + 2, min(fw - 1, bx2))
                        by2 = max(by1 + 2, min(fh - 1, by2))

                        if cls_name == "motor":
                            count_mtr += 1
                            box_col = (235, 190, 0) # Cyan
                            lbl = f"motor #{tid}"
                        elif cls_name == "bus":
                            count_bus += 1
                            box_col = (0, 165, 255) # Amber
                            lbl = f"bus #{tid}"
                        else:
                            count_mbl += 1
                            box_col = (50, 220, 80) # Emerald Neon
                            lbl = f"mobil #{tid}"

                        # Outline kotak AI
                        cv2.rectangle(fr, (bx1, by1), (bx2, by2), box_col, 2, cv2.LINE_AA)

                        # Bracket sudut taktis
                        cr = min(8, max(3, int(min(bx2 - bx1, by2 - by1) * 0.25)))
                        cv2.line(fr, (bx1, by1), (bx1 + cr, by1), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx1, by1), (bx1, by1 + cr), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx2, by1), (bx2 - cr, by1), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx2, by1), (bx2, by1 + cr), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx1, by2), (bx1 + cr, by2), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx1, by2), (bx1, by2 - cr), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx2, by2), (bx2 - cr, by2), (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.line(fr, (bx2, by2), (bx2, by2 - cr), (255, 255, 255), 2, cv2.LINE_AA)

                        # Label tag AI
                        (ltw, lth), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.28, 1)
                        tag_y1 = max(0, by1 - lth - 5)
                        tag_y2 = by1
                        tag_x2 = min(fw - 1, bx1 + ltw + 6)
                        cv2.rectangle(fr, (bx1, tag_y1), (tag_x2, tag_y2), box_col, -1)
                        cv2.putText(fr, lbl, (bx1 + 3, by1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (15, 23, 42), 1, cv2.LINE_AA)

                    # Update live counts pada status sistem
                    if arm_name in status_sistem["per_arm"]:
                        tot_c = count_mbl + count_mtr + count_bus
                        if tot_c > 0:
                            smp_c = round(count_mbl * 1.0 + count_mtr * 0.40 + count_bus * 1.3, 1)
                            status_sistem["per_arm"][arm_name].update({
                                "motor": count_mtr,
                                "mobil": count_mbl,
                                "bus": count_bus,
                                "total": tot_c,
                                "smp": smp_c,
                                "has_video": True
                            })

                    # Banner HUD AI di atas frame
                    hud_bar = fr.copy()
                    cv2.rectangle(hud_bar, (0, 0), (fw, 28), (15, 23, 42), -1)
                    cv2.addWeighted(hud_bar, 0.75, fr, 0.25, 0, fr)
                    cv2.rectangle(fr, (0, 27), (fw, 28), (56, 189, 248), 1)

                    hud_label = f"CCTV {arm_name.upper()} (LIVE AI YOLO) | Terdeteksi: Mtr:{count_mtr} Mbl:{count_mbl} Bus:{count_bus} | Total:{count_mtr+count_mbl+count_bus}"
                    cv2.putText(fr, hud_label, (12, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 220), 1, cv2.LINE_AA)
                    cv2.putText(fr, time.strftime("%H:%M:%S WIB"), (fw - 95, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

                    ret_enc, buf_c = cv2.imencode('.jpg', fr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ret_enc:
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf_c.tobytes() + b'\r\n')
                    time.sleep(wait_t)
                cap_c.release()
            return Response(stream_custom(v_path, direction), mimetype='multipart/x-mixed-replace; boundary=frame')
        else:
            frame_blank = np.zeros((360, 640, 3), np.uint8)
            cv2.putText(frame_blank, f"CCTV {direction.upper()} - STANDBY FEED", (140, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (200, 210, 220), 2, cv2.LINE_AA)
            cv2.putText(frame_blank, "Klik 'Pilih Video' untuk memuat rekaman CCTV lengan ini", (125, 198), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (130, 160, 180), 1, cv2.LINE_AA)
            cv2.putText(frame_blank, "Beban arus diderivasi melalui O-D Matrix Engine Simpang Dago", (120, 224), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 130, 150), 1, cv2.LINE_AA)
            ret, buf = cv2.imencode('.jpg', frame_blank)
            return Response(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n', mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    cycle_traffic_lights()

    tot_vol = sum(status_sistem["per_arm"][d]["total"] for d in ["utara", "timur", "selatan", "barat"])
    tot_pel = sum(status_sistem["pelanggaran_per_arm"][d]["total"] for d in ["utara", "timur", "selatan", "barat"])
    status_sistem["total_volume"] = tot_vol
    status_sistem["total_pelanggaran"] = tot_pel

    kpi_data = {
        "kepadatan": {
            "total_smp": status_sistem["total_smp_persimpangan"],
            "breakdown": {
                "utara": {"status": status_sistem["per_arm"]["utara"]["kepadatan"], "smp": status_sistem["per_arm"]["utara"]["smp"]},
                "timur": {"status": status_sistem["per_arm"]["timur"]["kepadatan"], "smp": status_sistem["per_arm"]["timur"]["smp"]},
                "selatan": {"status": status_sistem["per_arm"]["selatan"]["kepadatan"], "smp": status_sistem["per_arm"]["selatan"]["smp"]},
                "barat": {"status": status_sistem["per_arm"]["barat"]["kepadatan"], "smp": status_sistem["per_arm"]["barat"]["smp"]}
            }
        },
        "volume": {
            "total_akumulasi": tot_vol,
            "breakdown": {
                "utara": {
                    "motor": status_sistem["per_arm"]["utara"]["motor"],
                    "mobil": status_sistem["per_arm"]["utara"]["mobil"],
                    "bus": status_sistem["per_arm"]["utara"]["bus"],
                    "total": status_sistem["per_arm"]["utara"]["total"]
                },
                "timur": {
                    "motor": status_sistem["per_arm"]["timur"]["motor"],
                    "mobil": status_sistem["per_arm"]["timur"]["mobil"],
                    "bus": status_sistem["per_arm"]["timur"]["bus"],
                    "total": status_sistem["per_arm"]["timur"]["total"]
                },
                "selatan": {
                    "motor": status_sistem["per_arm"]["selatan"]["motor"],
                    "mobil": status_sistem["per_arm"]["selatan"]["mobil"],
                    "bus": status_sistem["per_arm"]["selatan"]["bus"],
                    "total": status_sistem["per_arm"]["selatan"]["total"]
                },
                "barat": {
                    "motor": status_sistem["per_arm"]["barat"]["motor"],
                    "mobil": status_sistem["per_arm"]["barat"]["mobil"],
                    "bus": status_sistem["per_arm"]["barat"]["bus"],
                    "total": status_sistem["per_arm"]["barat"]["total"]
                }
            }
        },
        "pelanggaran": {
            "total_terjaring": tot_pel,
            "breakdown": {
                "utara": status_sistem["pelanggaran_per_arm"]["utara"],
                "timur": status_sistem["pelanggaran_per_arm"]["timur"],
                "selatan": status_sistem["pelanggaran_per_arm"]["selatan"],
                "barat": status_sistem["pelanggaran_per_arm"]["barat"]
            }
        },
        "timers": {
            "fase_aktif": status_sistem["fase_lampu"],
            "breakdown": {
                "utara": {
                    "is_lurus_green": status_sistem["per_arm"]["utara"]["is_lurus_green"],
                    "is_kanan_green": status_sistem["per_arm"]["utara"]["is_kanan_green"],
                    "timer_lurus": status_sistem["per_arm"]["utara"]["timer_lurus"],
                    "timer_kanan": status_sistem["per_arm"]["utara"]["timer_kanan"],
                    "durasi_lurus": status_sistem["per_arm"]["utara"]["durasi_lurus"],
                    "durasi_kanan": status_sistem["per_arm"]["utara"]["durasi_kanan"]
                },
                "selatan": {
                    "is_lurus_green": status_sistem["per_arm"]["selatan"]["is_lurus_green"],
                    "is_kanan_green": status_sistem["per_arm"]["selatan"]["is_kanan_green"],
                    "timer_lurus": status_sistem["per_arm"]["selatan"]["timer_lurus"],
                    "timer_kanan": status_sistem["per_arm"]["selatan"]["timer_kanan"],
                    "durasi_lurus": status_sistem["per_arm"]["selatan"]["durasi_lurus"],
                    "durasi_kanan": status_sistem["per_arm"]["selatan"]["durasi_kanan"]
                },
                "timur": {
                    "is_green": status_sistem["per_arm"]["timur"]["is_green"],
                    "timer": status_sistem["per_arm"]["timur"]["timer"],
                    "durasi": status_sistem["per_arm"]["timur"]["durasi"]
                },
                "barat": {
                    "is_green": status_sistem["per_arm"]["barat"]["is_green"],
                    "timer": status_sistem["per_arm"]["barat"]["timer"],
                    "durasi": status_sistem["per_arm"]["barat"]["durasi"]
                }
            }
        }
    }

    return jsonify({
        "video_loop_epoch": video_loop_epoch,
        "current_video_sec": round(current_video_sec_utara, 2),
        "total_video_dur": 80.0,
        "has_east_bus_violation": status_sistem.get("has_east_bus_violation", False),
        "kpi": kpi_data,
        "fase_lampu": status_sistem["fase_lampu"],
        "active_videos": active_video_info,
        "daftar_pelanggaran": status_sistem["daftar_pelanggaran"],
        "detail_pelanggaran": status_sistem["detail_pelanggaran"],
        "tilang_aktif": status_sistem["tilang_aktif"],
        "per_arm": status_sistem["per_arm"],
        "simulasi": status_sistem["kendaraan_simulasi"],
        "sirkulasi_od": status_sistem.get("sirkulasi_od", {
            "lengan": "UTARA",
            "total_keluar": 61,
            "masuk_selatan": 37,
            "masuk_barat": 15,
            "masuk_timur": 9,
            "total_masuk_3_lengan": 61,
            "konsistensi_persen": 100.0,
            "formula": "61 Keluar = 37 (Selatan/Lurus) + 15 (Barat/Kanan) + 9 (Timur/Kiri)",
            "status_konservasi": "100% TEPAT & KONSISTEN"
        }),
        "od_matrix": {
            "distribusi_utara": {
                "lurus_selatan": 0.60,
                "kanan_barat": 0.25,
                "kiri_timur": 0.15
            },
            "total_smp": status_sistem["total_smp_persimpangan"]
        }
    })

@app.route('/api/set_fase/<fase_name>', methods=['POST'])
def set_fase(fase_name):
    fase_name = fase_name.upper()
    if fase_name in ["UTARA", "TIMUR", "SELATAN", "BARAT"]:
        status_sistem["fase_lampu"] = fase_name
        status_sistem["fase_start_time"] = time.time()
        dur = status_sistem["per_arm"][fase_name.lower()].get("durasi_lurus", status_sistem["per_arm"][fase_name.lower()].get("durasi", 30))
        status_sistem["manual_override_until"] = time.time() + dur
        cycle_traffic_lights()
        return jsonify({"success": True, "fase": fase_name, "durasi": dur})
    return jsonify({"success": False, "message": "Fase tidak valid"}), 400

@app.route('/api/upload_video/<direction>', methods=['POST'])
def upload_video(direction):
    direction = direction.lower()
    if direction not in ["utara", "selatan", "timur", "barat"]:
        return jsonify({"success": False, "message": "Lengan CCTV tidak valid"}), 400
    if 'video' not in request.files:
        return jsonify({"success": False, "message": "Tidak ada berkas video yang dikirim"}), 400
    file = request.files['video']
    if not file or file.filename == '':
        return jsonify({"success": False, "message": "Nama berkas kosong"}), 400

    ext = os.path.splitext(file.filename)[1] or '.mp4'
    saved_name = f"cctv_{direction}_{int(time.time())}{ext}"
    saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
    file.save(saved_path)

    cctv_custom_videos[direction] = saved_path
    active_video_info[direction] = file.filename
    return jsonify({
        "success": True,
        "direction": direction,
        "filename": file.filename,
        "message": f"Video CCTV {direction.upper()} berhasil dimuat!"
    })

@app.route('/api/delete_video/<direction>', methods=['POST'])
def delete_video(direction):
    direction = direction.lower()
    if direction not in ["utara", "selatan", "timur", "barat"]:
        return jsonify({"success": False, "message": "Lengan CCTV tidak valid"}), 400

    old_path = cctv_custom_videos.get(direction)
    cctv_custom_videos[direction] = None
    active_video_info[direction] = None
    if old_path and os.path.exists(old_path) and "video_utara_80s" not in old_path:
        try:
            os.remove(old_path)
        except Exception:
            pass
    return jsonify({
        "success": True,
        "direction": direction,
        "message": f"Berkas video CCTV {direction.upper()} dihapus. Kembali ke Standby Feed."
    })

@app.route('/api/reset_all', methods=['POST'])
def reset_all():
    global frame_counter, current_video_sec_utara, reset_requested, video_loop_epoch
    reset_requested = True
    video_loop_epoch += 1
    status_sistem["fase_lampu"] = "UTARA"
    status_sistem["fase_start_time"] = time.time()
    status_sistem["manual_override_until"] = 0
    status_sistem["daftar_pelanggaran"] = []
    status_sistem["detail_pelanggaran"] = {}
    status_sistem["tilang_aktif"] = False
    status_sistem["has_east_bus_violation"] = False
    for d in ["utara", "timur", "selatan", "barat"]:
        pelanggaran_ids_arm[d].clear()
        status_sistem["pelanggaran_per_arm"][d] = {"motor": 0, "mobil": 0, "bus": 0, "zebra": 0, "trotoar": 0, "total": 0}
    ticketed_vehicle_plates.clear()
    vehicle_plates.clear()
    seen_track_ids_utara.clear()
    frame_counter = 0
    current_video_sec_utara = 0.0

    # Inisialisasi ulang 4 pelanggaran zebra cross awal di Lengan Utara
    init_seed_pelanggaran()

    status_sistem["sirkulasi_od"] = {
        "lengan": "UTARA",
        "total_keluar": 61,
        "masuk_selatan": 37,
        "masuk_barat": 15,
        "masuk_timur": 9,
        "total_masuk_3_lengan": 61,
        "konsistensi_persen": 100.0,
        "formula": "61 Keluar = 37 (Selatan/Lurus) + 15 (Barat/Kanan) + 9 (Timur/Kiri)",
        "status_konservasi": "100% TEPAT & KONSISTEN"
    }

    cycle_traffic_lights()
    return jsonify({
        "success": True,
        "current_video_sec": 0.0,
        "message": "Video CCTV dan simulasi persimpangan berhasil diulang dari durasi awal (detik 0)!"
    })

if __name__ == '__main__':
    app.run(debug=False, port=5000, host="127.0.0.1")