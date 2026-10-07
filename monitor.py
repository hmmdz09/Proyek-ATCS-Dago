import urllib.request
import json
import time

for _ in range(35):
    try:
        with urllib.request.urlopen('http://127.0.0.1:5000/api/status') as resp:
            data = json.loads(resp.read().decode())
            sec = data.get('current_video_sec', 0)
            tot = data['kpi']['pelanggaran']['total_terjaring']
            count = len(data['daftar_pelanggaran'])
            utara_brk = data['kpi']['pelanggaran']['breakdown']['utara']
            is_green = data['kpi']['timers']['breakdown']['utara']['is_lurus_green']
            timer_u = data['kpi']['timers']['breakdown']['utara']['timer_lurus']
            print(f"Sec: {sec:.1f}s | Pelanggaran: {tot} (Zebra:{utara_brk['zebra']}, Trot:{utara_brk['trotoar']}) | Green:{is_green} ({timer_u}s)", flush=True)
            if sec >= 48.0 and utara_brk['trotoar'] == 1 and is_green:
                print(">>> SUCCESS: Detik 48 caught trotoar, and green light reached!", flush=True)
                break
    except Exception as e:
        print("Error:", e, flush=True)
    time.sleep(2.0)
