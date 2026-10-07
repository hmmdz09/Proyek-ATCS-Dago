# Sistem Monitoring Cerdas ATCS Simpang Dago (Bandung) 🚦🚗

Sistem cerdas **Area Traffic Control System (ATCS)** untuk pemantauan, pengaturan lampu lalu lintas adaptif, dan penegakan hukum tilang elektronik (ETLE) pada persimpangan **Simpang Dago, Bandung**, didukung oleh Computer Vision (YOLOv8) dan Flask Web Dashboard.

---

## 🌟 Fitur Utama

- **Deteksi & Tracking Kendaraan Real-Time**:
  - Menggunakan model Ultralytics **YOLOv8 Nano** (`yolov8n.pt`) untuk mendeteksi Sepeda Motor, Mobil Pribadi, Bus, dan Truk.
  - Tracker kustom (`SimpleVehicleTracker`) dengan estimasi kecepatan (*speed estimation* km/jam) dan deteksi antrean berhenti.
- **Perhitungan Volume Lalu Lintas & SMP (MKJI / PKJI)**:
  - Konversi Satuan Mobil Penumpang (SMP) otomatis: Motor = 0.25, Mobil = 1.0, Bus/Truk = 1.3.
  - Matriks Asal-Tujuan (Origin-Destination Matrix) dan hukum konservasi arus persimpangan 100% konsisten.
- **Sistem Pengaturan Lampu Adaptif & 4-Fase**:
  - Siklus 80 detik yang tersinkronisasi presisi dengan kondisi riil simpang.
  - Fitur *Early Cut-Off* belok kanan pada lengan selatan.
  - Dukungan *Manual Override* langsung dari Web Dashboard.
- **Tilang Elektronik (ETLE) Terintegrasi**:
  - Deteksi pelanggaran marka *Zebra Cross* (Garis Henti) dan Penyerobotan Trotoar Pejalan Kaki (Pasal 284 & 287 UU No. 22 Tahun 2009).
  - Penyimpanan bukti visual snapshot tangkapan kamera secara otomatis.
- **Multi-Feed CCTV Dashboard**:
  - Antarmuka monitoring terpadu untuk 4 lengan persimpangan (Utara, Timur, Selatan, Barat).
  - Tampilan visual diagram fase, grafik KPI volume, dan tabel log pelanggaran ETLE.

---

## 🛠️ Persyaratan Sistem

- Python 3.9+
- Paket Dependensi:
  ```bash
  pip install flask opencv-python ultralytics numpy
  ```

---

## 🚀 Cara Menjalankan

1. Clone repositori ini:
   ```bash
   git clone https://github.com/hmmdz09/Proyek-ATCS-Dago.git
   cd Proyek-ATCS-Dago
   ```
2. Pastikan file model `yolov8n.pt` tersedia di direktori utama.
3. Jalankan aplikasi Flask:
   ```bash
   python app.py
   ```
4. Buka peramban (browser) di alamat:
   ```
   http://127.0.0.1:5000
   ```

---

## 📂 Struktur Direktori

```
Proyek_ATCS_Dago/
├── app.py                     # Backend server Flask & engine utama ATCS
├── yolov8n.pt                 # Model bobot YOLOv8 Nano
├── inspect_video.py           # Skrip utilitas inspeksi video
├── monitor.py                 # Skrip polling status API
├── scratch_detect.py          # Skrip uji coba deteksi
├── test_status.py             # Skrip uji endpoint status
├── templates/
│   └── index.html             # Tampilan dashboard monitoring ATCS
├── static/
│   ├── script.js              # Logika interaktif frontend
│   ├── style.css              # Styling dashboard
│   └── uploads/               # Aset rekaman CCTV & subfolder evidence ETLE
└── README.md
```

---

## 📜 Lisensi & Atribusi
Dikembangkan untuk keperluan simulasi dan riset sistem transportasi cerdas perkotaan (Smart City & Intelligent Transportation System).
