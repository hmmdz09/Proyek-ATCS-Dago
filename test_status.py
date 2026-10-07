import urllib.request
import json
import time

for attempt in range(6):
    try:
        with urllib.request.urlopen('http://127.0.0.1:5000/api/status') as resp:
            data = json.loads(resp.read().decode())
            print("Server status 200 OK!")
            print("Total pelanggaran:", data['kpi']['pelanggaran']['total_terjaring'])
            print("Utara breakdown:", data['kpi']['pelanggaran']['breakdown']['utara'])
            print("Daftar pelanggaran count:", len(data['daftar_pelanggaran']))
            for item in data['daftar_pelanggaran']:
                print(f" - {item['id']}: {item['plat']} ({item['jenis_kendaraan']}) -> {item['jenis']}")
            break
    except Exception as e:
        print(f"Attempt {attempt+1} waiting: {e}")
        time.sleep(1.5)
