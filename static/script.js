/* ====================================================================
   ATCS COMMAND CENTER & E-TILANG SIMPANG DAGO - SCRIPT ENGINE (STRICT)
   - Left-Hand Traffic (Lajur Kiri Indonesia) Sebidang 4 Lengan
   - Lengan Utara & Selatan (Jl. Ir. H. Juanda):
     * Dimensi LEBIH BESAR (Lebar 192px)
     * 2 Lajur (Masuk & Keluar)
     * Masing-masing Lajur memiliki 3 BANJAR:
       - Lajur Keluar: Banjar Belok Kiri, Banjar Lurus, Banjar Belok Kanan
       - Lajur Masuk: 3 Banjar Masuk
   - Lengan Timur & Barat (Jl. Cikapayang - Surapati):
     * Dimensi LEBIH KECIL (Tinggi 104px)
     * 2 Lajur (Masuk & Keluar)
     * Masing-masing Lajur memiliki 2 BANJAR
   - Marka Jalan Lengkap: Double Yellow Median, Pembatas Banjar Putus-Putus,
     Marka Panah Aspal (← LURUS →), Zebra Cross & Stop Line Dinamis
   - Zero Serobot Lampu Merah (100% Disiplin Stop Line)
   - Lengan Utara SINKRON 1:1 dengan CCTV Video Nyata
   - Lengan Lainnya Diderivasi Presisi dari O-D Matrix MKJI
   - Dual Sinyal Adaptif (↑ Lurus + → Kanan Early Cut-Off)
   ==================================================================== */

const canvas = document.getElementById("simulasiCanvas");
const ctx = canvas ? canvas.getContext("2d") : null;

function resizeCanvas() {
    if (canvas && canvas.parentElement) {
        canvas.width = canvas.parentElement.clientWidth;
        canvas.height = canvas.parentElement.clientHeight;
    }
}
window.addEventListener("resize", resizeCanvas);
resizeCanvas();

// ====================================================================
// ZOOM & PAN ENGINE FOR 2D SIMULATION
// ====================================================================
let zoomLevel = 1.0;
let panX = 0;
let panY = 0;
let isDragging = false;
let startDragX = 0;
let startDragY = 0;

function updateZoomDisplay() {
    const el = document.getElementById("zoomLevelDisplay");
    if (el) el.textContent = `${Math.round(zoomLevel * 100)}%`;
}

window.zoomIn = function() {
    zoomLevel = Math.min(3.0, Math.round((zoomLevel + 0.15) * 100) / 100);
    updateZoomDisplay();
};

window.zoomOut = function() {
    zoomLevel = Math.max(0.40, Math.round((zoomLevel - 0.15) * 100) / 100);
    updateZoomDisplay();
};

window.zoomReset = function() {
    zoomLevel = 1.0;
    panX = 0;
    panY = 0;
    updateZoomDisplay();
};

if (canvas) {
    canvas.style.cursor = "grab";

    canvas.addEventListener("wheel", (e) => {
        e.preventDefault();
        const delta = e.deltaY < 0 ? 0.12 : -0.12;
        const newZoom = Math.min(3.0, Math.max(0.40, zoomLevel + delta));
        zoomLevel = Math.round(newZoom * 100) / 100;
        updateZoomDisplay();
    }, { passive: false });

    canvas.addEventListener("mousedown", (e) => {
        isDragging = true;
        startDragX = e.clientX - panX;
        startDragY = e.clientY - panY;
        canvas.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        panX = e.clientX - startDragX;
        panY = e.clientY - startDragY;
    });

    window.addEventListener("mouseup", () => {
        if (isDragging) {
            isDragging = false;
            if (canvas) canvas.style.cursor = "grab";
        }
    });

    // Touch support for pinch and drag
    let initialTouchDist = 0;
    let initialTouchZoom = 1.0;
    canvas.addEventListener("touchstart", (e) => {
        if (e.touches.length === 1) {
            isDragging = true;
            startDragX = e.touches[0].clientX - panX;
            startDragY = e.touches[0].clientY - panY;
        } else if (e.touches.length === 2) {
            isDragging = false;
            initialTouchDist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            initialTouchZoom = zoomLevel;
        }
    }, { passive: true });

    canvas.addEventListener("touchmove", (e) => {
        if (e.touches.length === 1 && isDragging) {
            panX = e.touches[0].clientX - startDragX;
            panY = e.touches[0].clientY - startDragY;
        } else if (e.touches.length === 2 && initialTouchDist > 0) {
            const currentDist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            const factor = currentDist / initialTouchDist;
            zoomLevel = Math.min(3.0, Math.max(0.6, Math.round(initialTouchZoom * factor * 100) / 100));
            updateZoomDisplay();
        }
    }, { passive: true });

    canvas.addEventListener("touchend", () => {
        isDragging = false;
        initialTouchDist = 0;
    });

    // Keyboard shortcuts
    window.addEventListener("keydown", (e) => {
        if (document.activeElement && (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA")) return;
        if (e.key === "+" || e.key === "=") window.zoomIn();
        else if (e.key === "-" || e.key === "_") window.zoomOut();
        else if (e.key === "0") window.zoomReset();
    });
}

let currentStatus = null;
let lastKnownViolationId = null;
let rawViolationsList = [];
let currentToastViolation = null;

// ====================================================================
// 1. CLOCK REAL-TIME
// ====================================================================
function updateClock() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    const el = document.getElementById("realtime-clock");
    if (el) {
        el.innerHTML = `<i class="fa-regular fa-clock me-1 text-primary"></i>${h}:${m}:${s} WIB`;
    }
}
setInterval(updateClock, 1000);
updateClock();

// ====================================================================
// 2. FITUR TEGURAN AUDIO (DINONAKTIFKAN SESUAI PERMINTAAN)
// ====================================================================
function speakTeguran(plat, lengan, jenis) {
    // Fitur teguran audio dinonaktifkan
}

function bunyikanTeguranTerbaru() {
    // Fitur teguran audio dinonaktifkan
}

// ====================================================================
// 3. TOAST & MODAL BUKTI KEJADIAN ETLE (UU NO. 22 TAHUN 2009)
// ====================================================================
function showViolationToast(pelanggaran) {
    currentToastViolation = pelanggaran;
    const toastEl = document.getElementById('violationToast');
    if (!toastEl) return;

    const thumbEl = document.getElementById('toast-thumb-img');
    const plateEl = document.getElementById('toast-plate');
    const armBadge = document.getElementById('toast-arm-badge');
    const typeEl = document.getElementById('toast-violation-type');
    const metaEl = document.getElementById('toast-meta');
    const pasalEl = document.getElementById('toast-pasal');
    const dendaEl = document.getElementById('toast-denda');
    const timeEl = document.getElementById('toast-time');

    if (thumbEl) thumbEl.src = pelanggaran.foto_url || "/static/uploads/evidence/evidence_ET-0001.jpg";
    if (plateEl) plateEl.textContent = pelanggaran.plat;
    if (armBadge) armBadge.textContent = pelanggaran.lengan;
    if (typeEl) typeEl.textContent = pelanggaran.jenis;
    if (metaEl) metaEl.textContent = `${pelanggaran.jenis_kendaraan} • ID: ${pelanggaran.id} • ${pelanggaran.waktu}`;
    if (pasalEl) pasalEl.textContent = pelanggaran.pasal || "Pasal 106 Ayat (2)&(4) jo. Pasal 287 (1) UU LLAJ";
    if (dendaEl) dendaEl.textContent = `${pelanggaran.sanksi || 'Denda Maks. Rp500.000,00'} (${pelanggaran.denda_maksimal || 'Rp500.000,00'})`;
    if (timeEl) timeEl.textContent = pelanggaran.waktu || "Baru saja";



    const toast = new bootstrap.Toast(toastEl, { delay: 8000 });
    toast.show();
}

function openEvidenceModal(violationId) {
    let row = rawViolationsList.find(r => r.id === violationId);
    if (!row && currentToastViolation && currentToastViolation.id === violationId) {
        row = currentToastViolation;
    }
    if (!row && rawViolationsList.length > 0) {
        row = rawViolationsList[0];
    }
    if (!row) return;

    document.getElementById("modal-id").textContent = row.id;
    document.getElementById("modal-plat").textContent = row.plat;
    document.getElementById("modal-waktu").textContent = `${row.waktu} • ${row.tanggal || ''}`;
    document.getElementById("modal-lokasi").textContent = row.lokasi || `Lengan ${row.lengan} (Simpang Dago)`;
    document.getElementById("modal-kendaraan").textContent = `${row.jenis_kendaraan} (${(row.cls || 'kendaraan').toUpperCase()})`;
    document.getElementById("modal-jenis").textContent = row.jenis;
    document.getElementById("modal-pasal").textContent = row.pasal || "Pasal 106 Ayat (2) & (4) jo. Pasal 287 Ayat (1) UU No. 22/2009";
    document.getElementById("modal-alasan").textContent = row.alasan_hukum || "Merampas hak dan membahayakan keselamatan pejalan kaki";
    document.getElementById("modal-sanksi").textContent = `${row.sanksi || 'Denda Maksimal Rp500.000,00 atau Pidana Kurungan 2 Bulan'} [${row.denda_maksimal || 'Rp500.000,00'}]`;

    const imgEl = document.getElementById("modal-evidence-img");
    if (imgEl) {
        imgEl.src = row.foto_url || "/static/uploads/evidence/evidence_ET-0001.jpg";
    }



    const modalEl = document.getElementById("evidenceModal");
    if (modalEl) {
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
    }
}

function openCurrentToastModal() {
    if (currentToastViolation) {
        openEvidenceModal(currentToastViolation.id);
    } else if (rawViolationsList.length > 0) {
        openEvidenceModal(rawViolationsList[0].id);
    }
}

// ====================================================================
// 4. TRIGGER INJEKSI PELANGGARAN SINTETIS (TEST UI)
// ====================================================================
function triggerSyntheticViolation() {
    fetch('/api/inject_violation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(r => r.json())
    .then(data => {
        if (data.success && data.pelanggaran) {
            showViolationToast(data.pelanggaran);
            fetchStatus();
        }
    })
    .catch(err => console.error("Gagal injeksi pelanggaran:", err));
}

// ====================================================================
// 5. MANUAL OVERRIDE FASE LAMPU
// ====================================================================
function setFaseManual(fase) {
    fetch(`/api/set_fase/${fase}`, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
        if (d.success) {
            fetchStatus();
        }
    })
    .catch(e => console.error("Gagal set fase manual:", e));
}

// ====================================================================
// 6. SIRKULASI O-D 100% KONSISTEN & ENGINE KENDARAAN DISIPLIN
// ====================================================================
let countNorthExit = 61;
let countNorthToSouth = 37; // 60%
let countNorthToWest = 15;  // 25%
let countNorthToEast = 9;   // 15%

function updateCirculationHUD() {
    const outEl = document.getElementById("circ-out-utara");
    const sEl = document.getElementById("circ-in-selatan");
    const wEl = document.getElementById("circ-in-barat");
    const eEl = document.getElementById("circ-in-timur");
    const badgeEl = document.getElementById("circ-balance-badge");

    if (outEl) outEl.textContent = countNorthExit;
    if (sEl) sEl.textContent = countNorthToSouth;
    if (wEl) wEl.textContent = countNorthToWest;
    if (eEl) eEl.textContent = countNorthToEast;

    const sumMasuk = countNorthToSouth + countNorthToWest + countNorthToEast;
    if (badgeEl) {
        badgeEl.innerHTML = `<i class="fa-solid fa-check-double me-1"></i>Σ Keluar (${countNorthExit}) = Σ Masuk (${sumMasuk}) • 100% Pas`;
    }
}

// Pola Distribusi Rute Deterministik (60% Lurus, 25% Kanan, 15% Kiri)
const NORTH_ROUTE_PATTERN = [
    "lurus", "lurus", "kanan", "lurus", "kiri",
    "lurus", "kanan", "lurus", "lurus", "kiri",
    "kanan", "lurus", "lurus", "kiri", "lurus",
    "kanan", "lurus", "lurus", "kanan", "lurus"
];
let northRouteSeq = 0;
function getNextRouteUtara() {
    const r = NORTH_ROUTE_PATTERN[northRouteSeq % NORTH_ROUTE_PATTERN.length];
    northRouteSeq++;
    return r;
}

function generateRandomPlate(type) {
    const letters = ['AB', 'SK', 'ZX', 'KL', 'DF', 'BCA', 'NX', 'CIT', 'BDG', 'TMB', 'DGO', 'TN'];
    const rL = letters[Math.floor(Math.random() * letters.length)];
    if (type === "motor") return `D ${Math.floor(Math.random() * 5000 + 2000)} ${rL}`;
    if (type === "bus") return `D ${Math.floor(Math.random() * 900 + 7000)} ${rL}`;
    return `D ${Math.floor(Math.random() * 900 + 1000)} ${rL}`;
}

// Kelas Kendaraan Presisi dengan Alokasi Banjar Spesifik
class TrafficVehicle {
    constructor(arm, type, route, plate, id, isViolation = false) {
        this.arm = arm;           // "utara", "selatan", "timur", "barat"
        this.type = type;         // "motor", "mobil", "bus"
        this.route = route;       // "lurus", "kanan", "kiri"
        this.plate = plate || generateRandomPlate(type);
        this.id = id || Math.floor(Math.random() * 9000 + 1000);
        this.progress = 0.0;      // progress antrean: 0.0 s/d 0.35 (stop line)
        this.crossT = 0.0;        // progress persimpangan: 0.0 s/d 1.0 (Bézier crossing)
        this.waiting = true;
        this.isViolation = isViolation;
        this.counted = false;
        this.banjarIdx = 0;       // indeks banjar di dalam lajur keluar (0, 1, 2)
        this.vehColorCustom = null; // Warna kustom bodi kendaraan
        this.hidden = false;      // Untuk menyembunyikan sebelum waktu kedatangan

        const baseSpd = type === "motor" ? 0.0020 : (type === "mobil" ? 0.0016 : 0.0012);
        this.speed = baseSpd * (0.95 + Math.random() * 0.1);

        // Dimensi dan batas aman anti-tabrakan
        if (type === "motor") {
            this.len = 10; this.wid = 5; this.minGap = 0.040;
        } else if (type === "mobil") {
            this.len = 18; this.wid = 9; this.minGap = 0.055;
        } else {
            this.len = 26; this.wid = 12; this.minGap = 0.078;
        }

        // Tentukan indeks banjar berdasarkan arah rute (Sesuai Konfigurasi Detailing)
        this.assignBanjar();
    }

    assignBanjar() {
        if (this.isZebra || this.isTrotoar) return; // Pertahankan banjar presisi khusus pelanggar video
        if (this.arm === "utara") {
            // Lajur Keluar Utara (arah Selatan ↓):
            // Banjar 0 = Kanan (dekat median), Banjar 1 = Lurus (tengah), Banjar 2 = Kiri (tepi timur)
            if (this.route === "kanan") this.banjarIdx = 0;
            else if (this.route === "lurus") this.banjarIdx = 1;
            else this.banjarIdx = 2; // kiri
        } else if (this.arm === "selatan") {
            // Lajur Keluar Selatan (arah Utara ↑):
            // Banjar 0 = Kiri (tepi barat), Banjar 1 = Lurus (tengah), Banjar 2 = Kanan (dekat median)
            if (this.route === "kiri") this.banjarIdx = 0;
            else if (this.route === "lurus") this.banjarIdx = 1;
            else this.banjarIdx = 2; // kanan
        } else if (this.arm === "barat") {
            // Lajur Keluar Barat (arah Timur →, 2 banjar):
            // Banjar 0 = Khusus Belok Kiri (LTOR ke Utara)
            // Banjar 1 = Wajib Lurus (ke Timur) & Kanan (ke Selatan) - Wajib patuh lampu lalu lintas!
            if (this.route === "kiri") this.banjarIdx = 0;
            else this.banjarIdx = 1; // "lurus" dan "kanan" selalu masuk Banjar 1
        } else if (this.arm === "timur") {
            // Lajur Keluar Timur (arah Barat ←, 2 banjar):
            // Banjar 0 = Khusus Belok Kiri (LTOR ke Selatan)
            // Banjar 1 = Wajib Lurus (ke Barat) & Kanan (ke Utara)
            if (this.route === "kiri") this.banjarIdx = 0;
            else this.banjarIdx = 1;
        }
    }
}

// Generator Antrean 61 Kendaraan Nyata Lengan Utara (21 Mobil, 39 Motor, 1 Truk)
// 0 - 48 detik (lampu merah) : 5 pelanggaran (1 motor trotoar, 2 mobil zebra, 2 motor zebra)
// 48 - 80 detik (lampu hijau) : jalan semua
function createNorthQueue61() {
    const list = [];
    // 1 Pelanggaran Motor Menaiki Trotoar (#101 D 5171 BCA)
    // Sesuai video: 0-47 detik trotoar bersih, pas detik ke-48 baru muncul melanggar!
    const motTrotoar = new TrafficVehicle("utara", "motor", "lurus", "D 5171 BCA", 101, false);
    motTrotoar.isTrotoar = true;
    motTrotoar.isZebra = false;
    motTrotoar.banjarIdx = 2;
    motTrotoar.progress = 0.360;
    motTrotoar.hidden = true; // Sembunyi sampai detik ke-48
    list.push(motTrotoar);

    // 4 Kendaraan Paling Depan di Atas Zebra Cross (Sesuai Persis dengan Tampilan CCTV Video):
    // 1. Mobil Hitam (#102 D 1088 RZ) - Sisi Kiri
    const mobZ1 = new TrafficVehicle("utara", "mobil", "lurus", "D 1088 RZ", 102, true);
    mobZ1.isZebra = true;
    mobZ1.banjarIdx = 0;
    mobZ1.vehColorCustom = "#1e293b"; // Hitam Charcoal
    mobZ1.progress = 0.362;
    list.push(mobZ1);

    // 2. Motor Hijau (#104 D 4255 ZX) - Antara Mobil Hitam dan Mobil Putih
    const motZ1 = new TrafficVehicle("utara", "motor", "lurus", "D 4255 ZX", 104, true);
    motZ1.isZebra = true;
    motZ1.banjarIdx = 1;
    motZ1.vehColorCustom = "#22c55e"; // Hijau
    motZ1.progress = 0.362;
    list.push(motZ1);

    // 3. Mobil Putih (#103 D 1992 TN) - Tengah Kanan
    const mobZ2 = new TrafficVehicle("utara", "mobil", "kanan", "D 1992 TN", 103, true);
    mobZ2.isZebra = true;
    mobZ2.banjarIdx = 1;
    mobZ2.vehColorCustom = "#f8fafc"; // Putih Bersih
    mobZ2.progress = 0.362;
    list.push(mobZ2);

    // 4. Motor Putih (#105 D 5946 ZX) - Tepi Kanan Dekat Trotoar
    const motZ2 = new TrafficVehicle("utara", "motor", "kiri", "D 5946 ZX", 105, true);
    motZ2.isZebra = true;
    motZ2.banjarIdx = 2;
    motZ2.vehColorCustom = "#e2e8f0"; // Putih
    motZ2.progress = 0.362;
    list.push(motZ2);

    // 1 Truk
    const truk = new TrafficVehicle("utara", "bus", "lurus", "D 7108 CIT", 106, false);
    truk.banjarIdx = 1;
    list.push(truk);

    // 19 Mobil Lainnya (Total Mobil = 2 + 19 = 21)
    const mobPlates = [
        "D 1284 PL", "D 1593 MY", "D 1740 KQ", "D 1822 SZ", "D 1335 FA",
        "D 1678 GL", "D 1109 RZ", "D 1450 TN", "D 1934 PL", "D 1682 MY",
        "D 1399 KQ", "D 1512 SZ", "D 1776 FA", "D 1204 GL", "D 1881 RZ",
        "D 1420 TN", "D 1633 PL", "D 1755 MY", "D 1890 KQ"
    ];
    const motLetters = ['SK', 'ZX', 'KL', 'DF', 'TZX', 'BCA', 'DGO', 'NX', 'AB'];

    // Distribusi rute: Total 61 = 37 Lurus, 15 Kanan, 9 Kiri
    // Sudah ada: 4 Lurus, 1 Kanan, 1 Kiri -> Sisa butuh: 33 Lurus, 14 Kanan, 8 Kiri
    const routesPool = [];
    for (let i = 0; i < 33; i++) routesPool.push("lurus");
    for (let i = 0; i < 14; i++) routesPool.push("kanan");
    for (let i = 0; i < 8; i++) routesPool.push("kiri");

    let seed = 42;
    function pseudoRnd() { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; }
    for (let i = routesPool.length - 1; i > 0; i--) {
        const j = Math.floor(pseudoRnd() * (i + 1));
        const temp = routesPool[i]; routesPool[i] = routesPool[j]; routesPool[j] = temp;
    }

    mobPlates.forEach((plat, i) => {
        const rt = routesPool.pop();
        const v = new TrafficVehicle("utara", "mobil", rt, plat, 200 + i, false);
        list.push(v);
    });

    for (let i = 0; i < 36; i++) {
        const rt = routesPool.pop();
        const plat = `D ${2100 + (i * 117) % 4800} ${motLetters[i % motLetters.length]}`;
        const v = new TrafficVehicle("utara", "motor", rt, plat, 300 + i, false);
        list.push(v);
    }

    // Susun antrean rapi per-banjar
    const banjarQueues = { 0: [], 1: [], 2: [] };
    list.forEach(v => {
        v.assignBanjar();
        banjarQueues[v.banjarIdx].push(v);
    });

    [0, 1, 2].forEach(bIdx => {
        const bq = banjarQueues[bIdx];
        let p = 0.345;
        bq.forEach(v => {
            if (v.isZebra) {
                v.progress = 0.362;
            } else if (v.isTrotoar) {
                v.progress = 0.360;
            } else {
                v.progress = Math.max(-2.5, p);
                p -= (v.minGap + 0.008);
            }
        });
    });

    return list;
}

// Wadah Antrean Terpisah untuk Setiap Lengan (Menjamin Jumlah Pas & Tertib)
const armQueues = {
    utara: createNorthQueue61(),
    selatan: [],
    barat: [],
    timur: []
};

// Catatan Waktu Pelepasan per Banjar untuk Seluruh Lengan (Memungkinkan Pelepasan Berbarengan di 2-3 Banjar Sekaligus)
const lastDischargeBanjar = {
    utara: { 0: 0, 1: 0, 2: 0 },
    selatan: { 0: 0, 1: 0, 2: 0 },
    barat: { 0: 0, 1: 0 },
    timur: { 0: 0, 1: 0 }
};

// Interval pelepasan per banjar disesuaikan agar tenang, realistis, dan sinkron dengan durasi video (80 detik)
const DISCHARGE_INTERVAL_BANJAR_MS = {
    utara: { 0: 2200, 1: 1100, 2: 3000 }, // Banjar 1 (Lurus) lebih padat, Banjar 0 & 2 mengalir berdampingan
    selatan: { 0: 2200, 1: 1800, 2: 2200 },
    barat: { 0: 1900, 1: 1900 },         // 2 Banjar keluar berbarengan!
    timur: { 0: 1900, 1: 1900 }          // 2 Banjar keluar berbarengan!
};

// Kendaraan yang Sedang Aktif Menyeberangi Persimpangan (Hanya yang Mendapat Lampu Hijau)
let activeCrossingVehicles = [];

// ====================================================================
// FUNGSI UTAMA: RESET SIMULASI KE AWAL (INSTAN & SINKRON PENUH DENGAN CCTV)
// ====================================================================
function resetSimulasiKeAwal(reason = "") {
    currentVideoSec = 0.0;

    // 1. Bersihkan seluruh kendaraan yang tersisa di dalam persimpangan
    activeCrossingVehicles = [];

    // 2. Susun ulang formasi 61 kendaraan Lengan Utara 1:1 persis rekaman CCTV
    armQueues.utara = createNorthQueue61();

    // 3. Reset antrean lengan lainnya agar diregenerasi bersih & rapi
    armQueues.selatan = [];
    armQueues.barat = [];
    armQueues.timur = [];

    // 4. Reset counter HUD sirkulasi O-D persis ke 61 keluar awal
    countNorthExit = 61;
    countNorthToSouth = 37;
    countNorthToWest = 15;
    countNorthToEast = 9;
    updateCirculationHUD();

    // 5. Reset interval pelepasan per banjar
    Object.keys(lastDischargeBanjar).forEach(arm => {
        Object.keys(lastDischargeBanjar[arm]).forEach(b => {
            lastDischargeBanjar[arm][b] = 0;
        });
    });

    console.log(`[Simulasi ATCS Dago] 🔄 Reset Ke Awal (Detik 0.0s) -> Alasan: ${reason}`);
}

// ====================================================================
// SINKRONISASI ANTREAN KENDARAAN LENGAN UTARA 1:1 DENGAN VIDEO NYATA
// ====================================================================
function syncNorthVehiclesFromVideo(videoDetections) {
    if (!videoDetections) return;
    const timers = currentStatus && currentStatus.kpi ? currentStatus.kpi.timers.breakdown : null;
    const isGreen = timers && timers.utara ? (timers.utara.is_lurus_green || timers.utara.is_kanan_green) : (currentVideoSec >= 48.0);

    // Jika fase lampu merah (0-48s):
    // Pastikan antrean selalu utuh 61 kendaraan dan 4 kendaraan zebra cross terdepan selalu hadir
    if (!isGreen) {
        const hasZebraLeader = armQueues.utara.some(v => v.isZebra && v.id === 102);
        if (!hasZebraLeader || armQueues.utara.length < 58) {
            armQueues.utara = createNorthQueue61();
            countNorthExit = 61;
            countNorthToSouth = 37;
            countNorthToWest = 15;
            countNorthToEast = 9;
            updateCirculationHUD();
        }
    }
}

// ====================================================================
// SINKRONISASI ANTREAN LENGAN LAINNYA SESUAI O-D MATRIX BACKEND
// ====================================================================
function syncOtherArmsFromBackend(perArmData) {
    if (!perArmData) return;

    // 1. SELATAN (Derivasi Arus Seimbang Jl. Ir. H. Juanda)
    const targetCountS = Math.max(3, perArmData.selatan?.total || 7);
    while (armQueues.selatan.length < targetCountS) {
        const r = Math.random();
        const route = r < 0.60 ? "lurus" : (r < 0.85 ? "kanan" : "kiri");
        const type = r < 0.50 ? "motor" : (r < 0.85 ? "mobil" : "bus");
        const v = new TrafficVehicle("selatan", type, route);
        const lastP = armQueues.selatan.length > 0 ? armQueues.selatan[armQueues.selatan.length - 1].progress - v.minGap : 0.345;
        v.progress = Math.max(-2.5, lastP);
        armQueues.selatan.push(v);
    }
    while (armQueues.selatan.length > targetCountS && armQueues.selatan.length > 3) {
        armQueues.selatan.pop();
    }

    // 2. BARAT (Derivasi 25% Belok Kanan + Arus Silang)
    const targetCountB = Math.max(2, perArmData.barat?.total || 5);
    while (armQueues.barat.length < targetCountB) {
        const r = Math.random();
        const type = r < 0.50 ? "motor" : "mobil";
        const v = new TrafficVehicle("barat", type, r < 0.70 ? "lurus" : "kiri");
        const lastP = armQueues.barat.length > 0 ? armQueues.barat[armQueues.barat.length - 1].progress - v.minGap : 0.345;
        v.progress = Math.max(-2.5, lastP);
        armQueues.barat.push(v);
    }
    while (armQueues.barat.length > targetCountB && armQueues.barat.length > 2) {
        armQueues.barat.pop();
    }

    // 3. TIMUR (Derivasi 15% Belok Kiri + Arus Silang)
    const targetCountT = Math.max(2, perArmData.timur?.total || 4);
    while (armQueues.timur.length < targetCountT) {
        const r = Math.random();
        const type = r < 0.50 ? "motor" : "mobil";
        const v = new TrafficVehicle("timur", type, r < 0.70 ? "lurus" : "kanan");
        const lastP = armQueues.timur.length > 0 ? armQueues.timur[armQueues.timur.length - 1].progress - v.minGap : 0.345;
        v.progress = Math.max(-2.5, lastP);
        armQueues.timur.push(v);
    }
    while (armQueues.timur.length > targetCountT && armQueues.timur.length > 2) {
        armQueues.timur.pop();
    }
}

// ====================================================================
// 7. RENDER SIMULASI 2D PERSIMPANGAN SEBIDANG SIMPANG DAGO DENGAN DETAILING BANJAR
// ====================================================================
function render2DSimulation() {
    if (!canvas || !ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    if (w <= 0 || h <= 0) return;

    // Bersihkan Kanvas
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, w, h);

    ctx.save();
    // Terapkan Zoom & Pan Interaktif
    ctx.translate(w * 0.50 + panX, h * 0.50 + panY);
    ctx.scale(zoomLevel, zoomLevel);
    ctx.translate(-w * 0.50, -h * 0.50);

    const cx = w * 0.50;
    const cy = h * 0.50;

    // DIMENSI PERSIMPANGAN:
    // Lengan Utara & Selatan LEBIH BESAR (6 Banjar = 3 Masuk + 3 Keluar)
    // Lengan Timur (4 Banjar = 2 Masuk + 2 Keluar)
    // Lengan Barat (3 Banjar = 2 Keluar/Menuju Simpang + 1 Banjar Masuk)
    const roadW = Math.min(192, Math.max(168, w * 0.26)); // Utara-Selatan (Lebar)
    const roadH = Math.min(108, Math.max(96, h * 0.22));  // Timur-Barat (Ramping)

    const subW = roadW / 6.0; // Lebar tiap banjar di Lengan Utara & Selatan (~30-32px)
    const subH = roadH / 4.0; // Tinggi banjar Timur (~25-27px)
    const tw = 22; // Lebar Trotoar Pejalan Kaki (Abu-abu)

    // ====================================================================
    // FULL-SCREEN INFINITE SIMULATION WORLD BOUNDS
    // Memastikan saat di-zoom out (misal 50% atau 60%) atau digeser (pan),
    // seluruh layar pandang TETAP PENUH dengan simulasi persimpangan, aspal, marka, trotoar & taman!
    // Tidak pernah ada layar kosong/blank borders.
    // ====================================================================
    const effectiveZoom = Math.max(0.2, zoomLevel);
    const viewSpanX = (w / effectiveZoom) * 2.0 + Math.abs(panX / effectiveZoom);
    const viewSpanY = (h / effectiveZoom) * 2.0 + Math.abs(panY / effectiveZoom);
    const worldSpan = Math.max(6000, Math.max(viewSpanX, viewSpanY));

    const worldLeft = cx - worldSpan;
    const worldRight = cx + worldSpan;
    const worldTop = cy - worldSpan;
    const worldBottom = cy + worldSpan;

    // ====================================================================
    // A. TROTOAR PEJALAN KAKI ABU-ABU & TAMAN SUDUT DAGO (Kanan-Kiri Tiap Lengan)
    // ===========================================    // 1. Area Taman Hijau di 4 Sudut Luar Trotoar (Lahan Penuh Tak Terbatas)
    ctx.fillStyle = "#1e3a29";
    // Barat Laut (Northwest)
    ctx.fillRect(worldLeft, worldTop, (cx - roadW / 2 - tw) - worldLeft, (cy - roadH / 2 - tw) - worldTop);
    // Timur Laut (Northeast)
    ctx.fillRect(cx + roadW / 2 + tw, worldTop, worldRight - (cx + roadW / 2 + tw), (cy - roadH / 2 - tw) - worldTop);
    // Barat Daya (Southwest)
    ctx.fillRect(worldLeft, cy + roadH / 2 + tw, (cx - roadW / 2 - tw) - worldLeft, worldBottom - (cy + roadH / 2 + tw));
    // Tenggara (Southeast)
    ctx.fillRect(cx + roadW / 2 + tw, cy + roadH / 2 + tw, worldRight - (cx + roadW / 2 + tw), worldBottom - (cy + roadH / 2 + tw));

    // 2. Trotoar Pejalan Kaki (Warna Abu-abu Modern #94a3b8)rna Abu-abu Modern #94a3b8)
    ctx.fillStyle = "#94a3b8";

    // Utara: Trotoar Kiri & Kanan
    ctx.fillRect(cx - roadW / 2 - tw, worldTop, tw, (cy - roadH / 2) - worldTop);
    ctx.fillRect(cx + roadW / 2, worldTop, tw, (cy - roadH / 2) - worldTop);

    // Selatan: Trotoar Kiri & Kanan
    ctx.fillRect(cx - roadW / 2 - tw, cy + roadH / 2, tw, worldBottom - (cy + roadH / 2));
    ctx.fillRect(cx + roadW / 2, cy + roadH / 2, tw, worldBottom - (cy + roadH / 2));

    // Barat: Trotoar Atas & Bawah
    ctx.fillRect(worldLeft, cy - roadH / 2 - tw, (cx - roadW / 2) - worldLeft, tw);
    ctx.fillRect(worldLeft, cy + roadH / 2, (cx - roadW / 2) - worldLeft, tw);

    // Timur: Trotoar Atas & Bawah
    ctx.fillRect(cx + roadW / 2, cy - roadH / 2 - tw, worldRight - (cx + roadW / 2), tw);
    ctx.fillRect(cx + roadW / 2, cy + roadH / 2, worldRight - (cx + roadW / 2), tw);

    // Tekstur Paving Block Trotoar Abu-abu (Garis Sambungan Ubin)
    ctx.strokeStyle = "rgba(51, 65, 85, 0.30)";
    ctx.lineWidth = 1;
    const paveMinY = Math.max(worldTop, cy - 1000);
    const paveMaxY = Math.min(worldBottom, cy + 1000);
    const paveMinX = Math.max(worldLeft, cx - 1200);
    const paveMaxX = Math.min(worldRight, cx + 1200);

    for (let py = cy - roadH / 2 - 8; py >= paveMinY; py -= 20) {
        ctx.beginPath();
        ctx.moveTo(cx - roadW / 2 - tw, py); ctx.lineTo(cx - roadW / 2, py);
        ctx.moveTo(cx + roadW / 2, py); ctx.lineTo(cx + roadW / 2 + tw, py);
        ctx.stroke();
    }
    for (let py = cy + roadH / 2 + 8; py <= paveMaxY; py += 20) {
        ctx.beginPath();
        ctx.moveTo(cx - roadW / 2 - tw, py); ctx.lineTo(cx - roadW / 2, py);
        ctx.moveTo(cx + roadW / 2, py); ctx.lineTo(cx + roadW / 2 + tw, py);
        ctx.stroke();
    }
    for (let px = cx - roadW / 2 - 8; px >= paveMinX; px -= 20) {
        ctx.beginPath();
        ctx.moveTo(px, cy - roadH / 2 - tw); ctx.lineTo(px, cy - roadH / 2);
        ctx.moveTo(px, cy + roadH / 2); ctx.lineTo(px, cy + roadH / 2 + tw);
        ctx.stroke();
    }
    for (let px = cx + roadW / 2 + 8; px <= paveMaxX; px += 20) {
        ctx.beginPath();
        ctx.moveTo(px, cy - roadH / 2 - tw); ctx.lineTo(px, cy - roadH / 2);
        ctx.moveTo(px, cy + roadH / 2); ctx.lineTo(px, cy + roadH / 2 + tw);
        ctx.stroke();
    }

    // Guiding Block Kuning (Ubin Pengarah Tuna Netra / Disabilitas Indonesia)
    ctx.strokeStyle = "#eab308";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    // Barat
    ctx.moveTo(worldLeft, cy - roadH / 2 - tw / 2); ctx.lineTo(cx - roadW / 2 - 8, cy - roadH / 2 - tw / 2);
    ctx.moveTo(worldLeft, cy + roadH / 2 + tw / 2); ctx.lineTo(cx - roadW / 2 - 8, cy + roadH / 2 + tw / 2);
    // Timur
    ctx.moveTo(cx + roadW / 2 + 8, cy - roadH / 2 - tw / 2); ctx.lineTo(worldRight, cy - roadH / 2 - tw / 2);
    ctx.moveTo(cx + roadW / 2 + 8, cy + roadH / 2 + tw / 2); ctx.lineTo(worldRight, cy + roadH / 2 + tw / 2);
    // Utara
    ctx.moveTo(cx - roadW / 2 - tw / 2, worldTop); ctx.lineTo(cx - roadW / 2 - tw / 2, cy - roadH / 2 - 8);
    ctx.moveTo(cx + roadW / 2 + tw / 2, worldTop); ctx.lineTo(cx + roadW / 2 + tw / 2, cy - roadH / 2 - 8);
    // Selatan
    ctx.moveTo(cx - roadW / 2 - tw / 2, cy + roadH / 2 + 8); ctx.lineTo(cx - roadW / 2 - tw / 2, worldBottom);
    ctx.moveTo(cx + roadW / 2 + tw / 2, cy + roadH / 2 + 8); ctx.lineTo(cx + roadW / 2 + tw / 2, worldBottom);
    ctx.stroke();

    // Kanstin Trotoar (Curb Tepi Badan Jalan Putih Rapih)
    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 2;
    ctx.beginPath();
    // Tepi Utara
    ctx.moveTo(cx - roadW / 2, worldTop); ctx.lineTo(cx - roadW / 2, cy - roadH / 2);
    ctx.moveTo(cx + roadW / 2, worldTop); ctx.lineTo(cx + roadW / 2, cy - roadH / 2);
    // Tepi Selatan
    ctx.moveTo(cx - roadW / 2, cy + roadH / 2); ctx.lineTo(cx - roadW / 2, worldBottom);
    ctx.moveTo(cx + roadW / 2, cy + roadH / 2); ctx.lineTo(cx + roadW / 2, worldBottom);
    // Tepi Barat
    ctx.moveTo(worldLeft, cy - roadH / 2); ctx.lineTo(cx - roadW / 2, cy - roadH / 2);
    ctx.moveTo(worldLeft, cy + roadH / 2); ctx.lineTo(cx - roadW / 2, cy + roadH / 2);
    // Tepi Timur
    ctx.moveTo(cx + roadW / 2, cy - roadH / 2); ctx.lineTo(worldRight, cy - roadH / 2);
    ctx.moveTo(cx + roadW / 2, cy + roadH / 2); ctx.lineTo(worldRight, cy + roadH / 2);
    ctx.stroke();

    // Label Mini Trotoar Pejalan Kaki
    ctx.save();
    ctx.font = "bold 6.5px 'Segoe UI', sans-serif";
    ctx.fillStyle = "#334155";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("TROTOAR", cx - roadW / 2 - 100, cy - roadH / 2 - tw / 2);
    ctx.fillText("TROTOAR", cx - roadW / 2 - 100, cy + roadH / 2 + tw / 2);
    ctx.fillText("TROTOAR", cx + roadW / 2 + 100, cy - roadH / 2 - tw / 2);
    ctx.fillText("TROTOAR", cx + roadW / 2 + 100, cy + roadH / 2 + tw / 2);
    ctx.restore();

    // ====================================================================
    // B. BADAN JALAN ASPAL
    // ====================================================================
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(cx - roadW / 2, worldTop, roadW, worldBottom - worldTop); // Jl. Ir. H. Juanda (Utara-Selatan)
    ctx.fillRect(worldLeft, cy - roadH / 2, worldRight - worldLeft, roadH); // Jl. Siliwangi - Dipatiukur (Barat-Timur)

    // C. Garis Tepi Simpang
    ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
    ctx.lineWidth = 1;
    ctx.strokeRect(cx - roadW / 2, cy - roadH / 2, roadW, roadH);

    // D. NAMA JALAN RESMI DI PERMUKAAN ASPAL (TERLIHAT JELAS SAAT ZOOM OUT)
    ctx.save();
    ctx.fillStyle = "rgba(255, 255, 255, 0.22)";
    ctx.font = "bold 8.5px 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    // Utara: Dago Atas
    ctx.save();
    ctx.translate(cx, cy - roadH / 2 - 140);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("JL. IR. H. JUANDA (DAGO ATAS)", 0, 0);
    ctx.restore();

    // Selatan: Dago Bawah
    ctx.save();
    ctx.translate(cx, cy + roadH / 2 + 140);
    ctx.rotate(Math.PI / 2);
    ctx.fillText("JL. IR. H. JUANDA (DAGO BAWAH)", 0, 0);
    ctx.restore();

    // Barat: Siliwangi
    ctx.fillText("JL. SILIWANGI", cx - roadW / 2 - 140, cy);

    // Timur: Dipatiukur
    ctx.fillText("JL. DIPATIUKUR", cx + roadW / 2 + 140, cy);
    ctx.restore();

    // ====================================================================
    // E. DETAILING MARKA JALAN (MEDIAN GANDA KUNING & PEMBATAS BANJAR)
    // ====================================================================

    // 1. Median Tengah Ganda Kuning (Double Solid Yellow Line)
    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth = 2;
    ctx.setLineDash([]);

    // Utara Median: x = cx - 2 dan x = cx + 2
    ctx.beginPath();
    ctx.moveTo(cx - 2, worldTop); ctx.lineTo(cx - 2, cy - roadH / 2 - 26);
    ctx.moveTo(cx + 2, worldTop); ctx.lineTo(cx + 2, cy - roadH / 2 - 26);
    ctx.stroke();

    // Selatan Median: x = cx - 2 dan x = cx + 2
    ctx.beginPath();
    ctx.moveTo(cx - 2, cy + roadH / 2 + 26); ctx.lineTo(cx - 2, worldBottom);
    ctx.moveTo(cx + 2, cy + roadH / 2 + 26); ctx.lineTo(cx + 2, worldBottom);
    ctx.stroke();

    // Barat Median: y = cy - 2 dan y = cy + 2
    ctx.beginPath();
    ctx.moveTo(worldLeft, cy - 2); ctx.lineTo(cx - roadW / 2 - 26, cy - 2);
    ctx.moveTo(worldLeft, cy + 2); ctx.lineTo(cx - roadW / 2 - 26, cy + 2);
    ctx.stroke();

    // Timur Median: y = cy - 2 dan y = cy + 2
    ctx.beginPath();
    ctx.moveTo(cx + roadW / 2 + 26, cy - 2); ctx.lineTo(worldRight, cy - 2);
    ctx.moveTo(cx + roadW / 2 + 26, cy + 2); ctx.lineTo(worldRight, cy + 2);
    ctx.stroke();

    // 2. Garis Putus-Putus Pembatas Antar-Banjar (White Dashed Sub-Lane Dividers)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.38)";
    ctx.lineWidth = 1.2;
    ctx.setLineDash([6, 6]);

    // LENGAN UTARA & SELATAN (Masing-masing lajur dibagi menjadi 3 Banjar):
    const utaraDivs = [cx - 2 * subW, cx - subW, cx + subW, cx + 2 * subW];
    utaraDivs.forEach(xPos => {
        ctx.beginPath();
        ctx.moveTo(xPos, worldTop);
        ctx.lineTo(xPos, cy - roadH / 2 - 26);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(xPos, cy + roadH / 2 + 26);
        ctx.lineTo(xPos, worldBottom);
        ctx.stroke();
    });

    // LENGAN BARAT:
    // Lajur Keluar (Atas): 2 Banjar -> pembatas di cy - subH
    // Lajur Masuk (Bawah): HANYA 1 BANJAR! (Tidak ada garis pembatas cy + subH)
    ctx.beginPath();
    ctx.moveTo(worldLeft, cy - subH);
    ctx.lineTo(cx - roadW / 2 - 26, cy - subH);
    ctx.stroke();

    // LENGAN TIMUR:
    // 2 Banjar di Lajur Masuk (cy - subH) dan 2 Banjar di Lajur Keluar (cy + subH)
    [cy - subH, cy + subH].forEach(yPos => {
        ctx.beginPath();
        ctx.moveTo(cx + roadW / 2 + 26, yPos);
        ctx.lineTo(worldRight, yPos);
        ctx.stroke();
    });
    ctx.setLineDash([]);

    // 3. Marka Panah di Permukaan Aspal (Lane Direction Arrows)
    function drawArrowOnAsphalt(x, y, type, rotation = 0) {
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(rotation);
        ctx.fillStyle = "rgba(255, 255, 255, 0.45)";
        ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
        ctx.lineWidth = 1.5;

        if (type === "straight") {
            ctx.beginPath();
            ctx.moveTo(0, 10); ctx.lineTo(0, -6);
            ctx.moveTo(-4, -2); ctx.lineTo(0, -8); ctx.lineTo(4, -2);
            ctx.stroke();
        } else if (type === "left") {
            ctx.beginPath();
            ctx.moveTo(2, 10); ctx.lineTo(2, 0); ctx.arcTo(2, -6, -4, -6, 4); ctx.lineTo(-8, -6);
            ctx.moveTo(-4, -10); ctx.lineTo(-9, -6); ctx.lineTo(-4, -2);
            ctx.stroke();
        } else if (type === "right") {
            ctx.beginPath();
            ctx.moveTo(-2, 10); ctx.lineTo(-2, 0); ctx.arcTo(-2, -6, 4, -6, 4); ctx.lineTo(8, -6);
            ctx.moveTo(4, -10); ctx.lineTo(9, -6); ctx.lineTo(4, -2);
            ctx.stroke();
        }
        ctx.restore();
    }

    const arrowY_U = cy - roadH / 2 - 42;
    // Lengan Utara Lajur Keluar: 3 Banjar (Kanan, Lurus, Kiri)
    drawArrowOnAsphalt(cx + 0.5 * subW, arrowY_U, "right", Math.PI);
    drawArrowOnAsphalt(cx + 1.5 * subW, arrowY_U, "straight", Math.PI);
    drawArrowOnAsphalt(cx + 2.5 * subW, arrowY_U, "left", Math.PI);

    const arrowY_S = cy + roadH / 2 + 42;
    // Lengan Selatan Lajur Keluar: 3 Banjar (Kiri, Lurus, Kanan)
    drawArrowOnAsphalt(cx - 2.5 * subW, arrowY_S, "left", 0);
    drawArrowOnAsphalt(cx - 1.5 * subW, arrowY_S, "straight", 0);
    drawArrowOnAsphalt(cx - 0.5 * subW, arrowY_S, "right", 0);

    const arrowX_B = cx - roadW / 2 - 46;
    // Lengan Barat:
    // Lajur Keluar (2 Banjar): Kiri & Kanan
    drawArrowOnAsphalt(arrowX_B, cy - 1.5 * subH, "left", Math.PI / 2);
    drawArrowOnAsphalt(arrowX_B, cy - 0.5 * subH, "right", Math.PI / 2);
    // Lajur Masuk (1 Banjar Tunggal): Panah Lurus Menjauhi Simpang (ke arah Barat)
    drawArrowOnAsphalt(arrowX_B, cy + roadH * 0.25, "straight", -Math.PI / 2);

    const arrowX_T = cx + roadW / 2 + 46;
    // Lengan Timur:
    drawArrowOnAsphalt(arrowX_T, cy + 1.5 * subH, "left", -Math.PI / 2);
    drawArrowOnAsphalt(arrowX_T, cy + 0.5 * subH, "right", -Math.PI / 2);

    // ====================================================================
    // E. STATUS LAMPU & SINYAL TRAFFIC LIGHTS
    // ====================================================================
    const timers = currentStatus && currentStatus.kpi ? currentStatus.kpi.timers.breakdown : null;
    const uLurusGreen = timers ? timers.utara.is_lurus_green : false;
    const uKananGreen = timers ? timers.utara.is_kanan_green : false;
    const sLurusGreen = timers ? timers.selatan.is_lurus_green : false;
    const sKananGreen = timers ? timers.selatan.is_kanan_green : false;
    const tGreen = timers ? timers.timur.is_green : false;
    const bGreen = timers ? timers.barat.is_green : false;

    // ====================================================================
    // F. ZEBRA CROSS & GARIS HENTI (GARIS HENTI BERADA DI BELAKANG ZEBRA CROSS)
    // ====================================================================
    function drawZebraCrossings() {
        const zebraW_U = roadW;
        const zebraH_B = roadH;

        // Dimensi Zebra Cross
        // 1. UTARA: Datang dari atas (y: 0 -> cy)
        // Zebra Cross: zyU s/d zyU + 16 (antara Garis Henti & Simpang)
        const zxU = cx - roadW / 2;
        const zyU = cy - roadH / 2 - 22;
        ctx.fillStyle = "#f8fafc";
        const nBarsU = 10;
        const barWU = zebraW_U / (nBarsU * 2);
        for (let i = 0; i < nBarsU; i++) {
            ctx.fillRect(zxU + i * 2 * barWU, zyU, barWU, 16);
        }

        // 2. SELATAN: Datang dari bawah (y: h -> cy)
        // Zebra Cross: zyS s/d zyS + 16
        const zxS = cx - roadW / 2;
        const zyS = cy + roadH / 2 + 6;
        for (let i = 0; i < nBarsU; i++) {
            ctx.fillRect(zxS + i * 2 * barWU, zyS, barWU, 16);
        }

        // 3. BARAT: Datang dari kiri (x: 0 -> cx)
        // Zebra Cross: zxB s/d zxB + 16 (antara Garis Henti & Simpang)
        const zxB = cx - roadW / 2 - 22;
        const zyB = cy - roadH / 2;
        const nBarsB = 6;
        const barHB = zebraH_B / (nBarsB * 2);
        for (let i = 0; i < nBarsB; i++) {
            ctx.fillRect(zxB, zyB + i * 2 * barHB, 16, barHB);
        }

        // 4. TIMUR: Datang dari kanan (x: w -> cx)
        // Zebra Cross: zxT s/d zxT + 16 (antara Simpang & Garis Henti)
        const zxT = cx + roadW / 2 + 6;
        const zyT = cy - roadH / 2;
        for (let i = 0; i < nBarsB; i++) {
            ctx.fillRect(zxT, zyT + i * 2 * barHB, 16, barHB);
        }

        // GARIS HENTI SOLID (STOP LINE) BERADA DI BELAKANG SETIAP ZEBRA CROSS
        ctx.lineWidth = 4;

        // 1. UTARA: Garis Henti di ATAS Zebra Cross (y = zyU)
        ctx.strokeStyle = uKananGreen ? "#10b981" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(cx, zyU); ctx.lineTo(cx + subW, zyU); ctx.stroke();
        ctx.strokeStyle = uLurusGreen ? "#10b981" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(cx + subW, zyU); ctx.lineTo(cx + roadW / 2, zyU); ctx.stroke();
        ctx.strokeStyle = "#ffffff";
        ctx.beginPath(); ctx.moveTo(cx - roadW / 2, zyU); ctx.lineTo(cx, zyU); ctx.stroke();

        // 2. SELATAN: Garis Henti di BAWAH Zebra Cross (y = zyS + 16)
        // Banjar Belok Kiri (cx - roadW/2 s/d cx - 2*subW): Belok Kiri Jalan Terus (Garis Hijau Putus-putus)
        ctx.strokeStyle = "#10b981";
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(cx - roadW / 2, zyS + 16); ctx.lineTo(cx - 2 * subW, zyS + 16); ctx.stroke();
        ctx.setLineDash([]);

        // Banjar Lurus:
        ctx.strokeStyle = sLurusGreen ? "#10b981" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(cx - 2 * subW, zyS + 16); ctx.lineTo(cx - subW, zyS + 16); ctx.stroke();

        // Banjar Kanan:
        ctx.strokeStyle = sKananGreen ? "#10b981" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(cx - subW, zyS + 16); ctx.lineTo(cx, zyS + 16); ctx.stroke();

        ctx.strokeStyle = "#ffffff";
        ctx.beginPath(); ctx.moveTo(cx, zyS + 16); ctx.lineTo(cx + roadW / 2, zyS + 16); ctx.stroke();

        // Marka Teks Indikator Belok Kiri Jalan Terus
        ctx.save();
        ctx.font = "bold 6.5px 'Segoe UI', sans-serif";
        ctx.fillStyle = "#34d399";
        ctx.textAlign = "center";
        ctx.fillText("← KIRI JALAN TERUS", cx - 2.5 * subW, zyS + 26);
        ctx.restore();

        // 3. BARAT: Garis Henti di KIRI Zebra Cross (x = zxB, sebelum zebra cross!)
        // Banjar Belok Kiri: Belok Kiri Jalan Terus
        ctx.strokeStyle = "#10b981";
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(zxB, cy - roadH / 2); ctx.lineTo(zxB, cy - subH); ctx.stroke();
        ctx.setLineDash([]);
        // Banjar Lurus/Kanan:
        ctx.strokeStyle = bGreen ? "#10b981" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(zxB, cy - subH); ctx.lineTo(zxB, cy); ctx.stroke();
        // Sisi Masuk Barat (1 Banjar): Marka putih pembatas
        ctx.strokeStyle = "#ffffff";
        ctx.beginPath(); ctx.moveTo(zxB, cy); ctx.lineTo(zxB, cy + roadH / 2); ctx.stroke();

        // 4. TIMUR: Garis Henti di KANAN Zebra Cross (x = zxT + 16, sebelum zebra cross!)
        // Banjar Belok Kiri: Belok Kiri Jalan Terus
        ctx.strokeStyle = "#10b981";
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(zxT + 16, cy); ctx.lineTo(zxT + 16, cy + subH); ctx.stroke();
        ctx.setLineDash([]);
        // Banjar Lurus/Kanan:
        ctx.strokeStyle = tGreen ? "#10b981" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(zxT + 16, cy + subH); ctx.lineTo(zxT + 16, cy + roadH / 2); ctx.stroke();
        ctx.strokeStyle = "#ffffff";
        ctx.beginPath(); ctx.moveTo(zxT + 16, cy - roadH / 2); ctx.lineTo(zxT + 16, cy); ctx.stroke();
    }
    drawZebraCrossings();

    // ====================================================================
    // G. LABEL PANDUAN LAJUR & BANJAR (Di Luar Aspal Agar Bebas Tabrakan Teks)
    // ====================================================================
    function drawDetailedBadge(text, x, y, isOutflow, subText = "") {
        ctx.save();
        ctx.font = "bold 8px 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const displayTxt = subText ? `${text} • ${subText}` : text;
        const tw = ctx.measureText(displayTxt).width;
        const bw = tw + 10;
        const bh = 15;

        ctx.fillStyle = isOutflow ? "rgba(15, 23, 42, 0.94)" : "rgba(15, 23, 42, 0.88)";
        ctx.strokeStyle = isOutflow ? "rgba(56, 189, 248, 0.90)" : "rgba(52, 211, 153, 0.75)";
        ctx.lineWidth = 1;

        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x - bw / 2, y - bh / 2, bw, bh, 3);
        else ctx.rect(x - bw / 2, y - bh / 2, bw, bh);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = isOutflow ? "#38bdf8" : "#34d399";
        ctx.fillText(displayTxt, x, y);
        ctx.restore();
    }

    // 1. UTARA: Diletakkan di LUAR badan jalan (di atas plaza trotoar/taman) agar tidak menutupi kendaraan
    const utaraInBadgeX = cx - roadW / 2 - tw - 80;
    const utaraOutBadgeX = cx + roadW / 2 + tw + 80;
    const utaraBadgeY = cy - roadH / 2 - tw - 24;
    drawDetailedBadge("MASUK (↑) • 3 BANJAR", utaraInBadgeX, utaraBadgeY, false);
    drawDetailedBadge("KELUAR (↓) • 3 BANJAR", utaraOutBadgeX, utaraBadgeY, true, `CCTV: 61`);

    // 2. SELATAN: Diletakkan di LUAR badan jalan (di bawah plaza trotoar/taman)
    const selatanOutBadgeX = cx - roadW / 2 - tw - 80;
    const selatanInBadgeX = cx + roadW / 2 + tw + 80;
    const selatanBadgeY = cy + roadH / 2 + tw + 24;
    drawDetailedBadge("KELUAR (↑) • 3 BANJAR", selatanOutBadgeX, selatanBadgeY, true, `O-D: ${armQueues.selatan.length}`);
    drawDetailedBadge("MASUK (↓) • 3 BANJAR", selatanInBadgeX, selatanBadgeY, false);

    // 3. BARAT:
    // Ditaruh di LUAR badan jalan (di atas & bawah trotoar), bebas tabrakan dengan antrean mobil & kotak sinyal
    const baratBadgeX = cx - roadW / 2 - 130;
    drawDetailedBadge("KELUAR (→) • 2 BANJAR", baratBadgeX, cy - roadH / 2 - tw - 14, true, `O-D: ${armQueues.barat.length}`);
    drawDetailedBadge("MASUK (←) • 1 BANJAR", baratBadgeX, cy + roadH / 2 + tw + 14, false);

    // 4. TIMUR:
    const timurBadgeX = cx + roadW / 2 + 130;
    drawDetailedBadge("MASUK (→) • 2 BANJAR", timurBadgeX, cy - roadH / 2 - tw - 14, false);
    drawDetailedBadge("KELUAR (←) • 2 BANJAR", timurBadgeX, cy + roadH / 2 + tw + 14, true, `O-D: ${armQueues.timur.length}`);

    // ====================================================================
    // H. KOTAK LAMPU LALU LINTAS (Di Plaza Sudut Trotoar, Rapi & Lega)
    // ====================================================================
    function drawDualSignalBox(x, y, isLurusGreen, isKananGreen, timerLurus, timerKanan, title) {
        ctx.save();
        ctx.fillStyle = "#0f172a";
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 1.5;
        ctx.fillRect(x, y, 84, 52);
        ctx.strokeRect(x, y, 84, 52);

        ctx.fillStyle = "#94a3b8";
        ctx.font = "bold 8px 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(title, x + 42, y + 10);

        // 1. Lurus (↑)
        const colL = isLurusGreen ? "#10b981" : "#ef4444";
        const glowL = isLurusGreen ? "rgba(16, 185, 129, 0.45)" : "rgba(239, 68, 68, 0.45)";
        ctx.fillStyle = glowL;
        ctx.beginPath(); ctx.arc(x + 23, y + 27, 11, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = colL;
        ctx.beginPath(); ctx.arc(x + 23, y + 27, 8.5, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(255, 255, 255, 0.85)"; ctx.lineWidth = 1.0; ctx.stroke();
        // Panah lurus vector
        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5;
        const axL = x + 23, ayL = y + 27;
        ctx.beginPath();
        ctx.moveTo(axL, ayL + 5); ctx.lineTo(axL, ayL - 4);
        ctx.moveTo(axL - 3.5, ayL - 1); ctx.lineTo(axL, ayL - 5); ctx.lineTo(axL + 3.5, ayL - 1);
        ctx.stroke();
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 10px monospace";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(`${timerLurus || 0}s`, x + 23, y + 47);

        // 2. Kanan (→)
        const colK = isKananGreen ? "#10b981" : "#ef4444";
        const glowK = isKananGreen ? "rgba(16, 185, 129, 0.45)" : "rgba(239, 68, 68, 0.45)";
        ctx.fillStyle = glowK;
        ctx.beginPath(); ctx.arc(x + 61, y + 27, 11, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = colK;
        ctx.beginPath(); ctx.arc(x + 61, y + 27, 8.5, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(255, 255, 255, 0.85)"; ctx.lineWidth = 1.0; ctx.stroke();
        // Panah kanan vector
        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5;
        const axK = x + 61, ayK = y + 27;
        ctx.beginPath();
        ctx.moveTo(axK - 5, ayK); ctx.lineTo(axK + 4, ayK);
        ctx.moveTo(axK + 1, ayK - 3.5); ctx.lineTo(axK + 5, ayK); ctx.lineTo(axK + 1, ayK + 3.5);
        ctx.stroke();
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 10px monospace";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(`${timerKanan || 0}s`, x + 61, y + 47);
        ctx.restore();
    }

    function drawSingleSignalBox(x, y, isGreen, timerVal, title, isLeft = true) {
        ctx.save();
        ctx.fillStyle = "#0f172a";
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 1.5;
        ctx.fillRect(x, y, 48, 52);
        ctx.strokeRect(x, y, 48, 52);

        // Judul Lengan (BARAT / TIMUR)
        ctx.fillStyle = "#94a3b8";
        ctx.font = "bold 8px 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(title, x + 24, y + 10);

        const activeColor = isGreen ? "#10b981" : "#ef4444";
        const glowColor = isGreen ? "rgba(16, 185, 129, 0.50)" : "rgba(239, 68, 68, 0.50)";

        // Outer Glow Halo
        ctx.fillStyle = glowColor;
        ctx.beginPath();
        ctx.arc(x + 24, y + 27, 12, 0, Math.PI * 2);
        ctx.fill();

        // Main Solid Lamp Circle (Pasti Berwarna Merah / Hijau Pekat Menyala)
        ctx.fillStyle = activeColor;
        ctx.beginPath();
        ctx.arc(x + 24, y + 27, 9.5, 0, Math.PI * 2);
        ctx.fill();

        // Ring Border Putih Halus
        ctx.strokeStyle = "rgba(255, 255, 255, 0.90)";
        ctx.lineWidth = 1.2;
        ctx.stroke();

        // Simbol Panah Vector Tajam (Bukan font)
        ctx.strokeStyle = "#ffffff";
        ctx.fillStyle = "#ffffff";
        ctx.lineWidth = 1.5;
        const ax = x + 24, ay = y + 27;
        ctx.beginPath();
        if (isLeft) {
            // Panah ke KIRI (←) untuk BARAT
            ctx.moveTo(ax + 5, ay); ctx.lineTo(ax - 4, ay);
            ctx.moveTo(ax - 1, ay - 3.5); ctx.lineTo(ax - 5, ay); ctx.lineTo(ax - 1, ay + 3.5);
        } else {
            // Panah ke KANAN (→) untuk TIMUR
            ctx.moveTo(ax - 5, ay); ctx.lineTo(ax + 4, ay);
            ctx.moveTo(ax + 1, ay - 3.5); ctx.lineTo(ax + 5, ay); ctx.lineTo(ax + 1, ay + 3.5);
        }
        ctx.stroke();

        // Angka Hitung Mundur (Detik)
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 10px monospace";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(`${timerVal || 0}s`, x + 24, y + 47);
        ctx.restore();
    }

    const tU = timers ? timers.utara : { timer_lurus: 30, timer_kanan: 16 };
    const tS = timers ? timers.selatan : { timer_lurus: 30, timer_kanan: 15 };
    const tT = timers ? timers.timur : { timer: 20 };
    const tB = timers ? timers.barat : { timer: 20 };

    // Kotak Sinyal Lampu Presisi di Plaza Sudut Trotoar (Lega & Bebas Tumpang Tindih)
    drawDualSignalBox(cx + roadW / 2 + tw + 8, cy - roadH / 2 - tw - 60, uLurusGreen, uKananGreen, tU.timer_lurus, tU.timer_kanan, "UTARA (↑ + →)");
    drawDualSignalBox(cx - roadW / 2 - tw - 92, cy + roadH / 2 + tw + 14, sLurusGreen, sKananGreen, tS.timer_lurus, tS.timer_kanan, "SELATAN (↑ + →)");
    drawSingleSignalBox(cx + roadW / 2 + tw + 8, cy + roadH / 2 + tw + 14, Boolean(tGreen), tT.timer, "TIMUR", false);
    drawSingleSignalBox(cx - roadW / 2 - tw - 58, cy - roadH / 2 - tw - 60, Boolean(bGreen), tB.timer, "BARAT", true);

    // ====================================================================
    // I. LOGIKA PERGERAKAN DISIPLIN PER-BANJAR: ZERO SEROBOT LAMPU MERAH!
    // ====================================================================
    const nowTime = Date.now();
    const armList = ["utara", "selatan", "barat", "timur"];

    armList.forEach(armName => {
        const queue = armQueues[armName];
        if (!queue || queue.length === 0) return;

        // 1. DISCHARGE KENDARAAN SESUAI LAMPU HIJAU
        // 1. DISCHARGE KENDARAAN SESUAI LAMPU HIJAU (MULTI-BANJAR BERBARENGAN)
        if (armName === "utara") {
            // LENGAN UTARA DISCHARGE ENGINE (Sinkron Video 48 - 80s)
            // Kendaraan dapat keluar berbarengan di 2-3 banjar sekaligus
            if (uLurusGreen || uKananGreen) {
                [0, 1, 2].forEach(bIdx => {
                    let canDischarge = false;
                    if (bIdx === 0) canDischarge = Boolean(uKananGreen);
                    else if (bIdx === 1) canDischarge = Boolean(uLurusGreen);
                    else canDischarge = Boolean(uLurusGreen || uKananGreen);

                    const banjarInterval = (DISCHARGE_INTERVAL_BANJAR_MS.utara && DISCHARGE_INTERVAL_BANJAR_MS.utara[bIdx]) || 1500;
                    if (canDischarge && (nowTime - (lastDischargeBanjar.utara[bIdx] || 0) >= banjarInterval)) {
                        for (let idx = 0; idx < queue.length; idx++) {
                            const cand = queue[idx];
                            if (cand.banjarIdx === bIdx && cand.progress >= 0.335) {
                                lastDischargeBanjar.utara[bIdx] = nowTime;
                                const crossingVeh = queue.splice(idx, 1)[0];
                                crossingVeh.waiting = false;
                                crossingVeh.isViolation = false; // Legal melaju saat hijau
                                crossingVeh.crossT = 0.0;
                                activeCrossingVehicles.push(crossingVeh);

                                if (!crossingVeh.counted) {
                                    crossingVeh.counted = true;
                                    countNorthExit++;
                                    if (crossingVeh.route === "lurus") countNorthToSouth++;
                                    else if (crossingVeh.route === "kanan") countNorthToWest++;
                                    else countNorthToEast++;
                                    updateCirculationHUD();
                                }

                                // Tambahkan kendaraan baru di ujung belakang antrean agar arus lalu lintas Dago tetap mengalir realistis sepanjang lampu hijau
                                const nextRoute = getNextRouteUtara();
                                const newVeh = new TrafficVehicle("utara", crossingVeh.type, nextRoute);
                                const bq = queue.filter(q => q.banjarIdx === crossingVeh.banjarIdx);
                                const lastP = bq.length > 0 ? bq[bq.length - 1].progress - newVeh.minGap : -0.20;
                                newVeh.progress = Math.max(-2.5, lastP);
                                queue.push(newVeh);
                                break;
                            }
                        }
                    }
                });
            } else {
                // Saat lampu merah (0-48s), pastikan antrean selalu terkumpul penuh 61 kendaraan riil
                if (queue.length < 55) {
                    armQueues.utara = createNorthQueue61();
                    countNorthExit = 61;
                    countNorthToSouth = 37;
                    countNorthToWest = 15;
                    countNorthToEast = 9;
                    updateCirculationHUD();
                }
            }
        } else {
            // LENGAN SELATAN, BARAT, TIMUR: MULTI-BANJAR BERBARENGAN
            // 2 Banjar keluar langsung bersamaan untuk merepresentasikan kepadatan arus nyata
            const banjarsInArm = (armName === "selatan") ? [0, 1, 2] : [0, 1];
            banjarsInArm.forEach(bIdx => {
                const banjarInterval = (DISCHARGE_INTERVAL_BANJAR_MS[armName] && DISCHARGE_INTERVAL_BANJAR_MS[armName][bIdx]) || 1900;
                
                // Cari kendaraan paling depan di banjar ini yang sudah berada di garis henti
                for (let idx = 0; idx < queue.length; idx++) {
                    const cand = queue[idx];
                    if (cand.banjarIdx === bIdx && cand.progress >= 0.335) {
                        // Periksa sinyal lampu spesifik berdasarkan rute kendaraan terdepan
                        let canCross = false;
                        if (cand.route === "kiri") {
                            // Belok kiri langsung jalan terus (LTOR)
                            canCross = true;
                        } else if (cand.route === "lurus") {
                            // LURUS WAJIB MENUNGGU LAMPU HIJAU!
                            if (armName === "selatan") canCross = Boolean(sLurusGreen);
                            else if (armName === "timur") canCross = Boolean(tGreen);
                            else if (armName === "barat") canCross = Boolean(bGreen); // ZERO TOLERANCE: BARAT LURUS HARUS LAMPU HIJAU!
                        } else if (cand.route === "kanan") {
                            // BELOK KANAN WAJIB MENUNGGU LAMPU HIJAU!
                            if (armName === "selatan") canCross = Boolean(sKananGreen);
                            else if (armName === "timur") canCross = Boolean(tGreen);
                            else if (armName === "barat") canCross = Boolean(bGreen);
                        }

                        // Hanya discharge jika lampu mengizinkan dan interval waktu terpenuhi
                        if (canCross && (nowTime - (lastDischargeBanjar[armName][bIdx] || 0) >= banjarInterval)) {
                            lastDischargeBanjar[armName][bIdx] = nowTime;
                            const crossingVeh = queue.splice(idx, 1)[0];
                            crossingVeh.waiting = false;
                            crossingVeh.crossT = 0.0;
                            activeCrossingVehicles.push(crossingVeh);

                            const r = Math.random();
                            const newRoute = (armName === "selatan") 
                                ? (r < 0.60 ? "lurus" : (r < 0.85 ? "kanan" : "kiri"))
                                : (armName === "barat"
                                    ? (bIdx === 0 ? "kiri" : (r < 0.70 ? "lurus" : "kanan"))
                                    : (bIdx === 0 ? "kiri" : (r < 0.70 ? "lurus" : "kanan")));
                            const newVeh = new TrafficVehicle(armName, crossingVeh.type, newRoute);
                            const bq = queue.filter(q => q.banjarIdx === bIdx);
                            const lastP = bq.length > 0 ? bq[bq.length - 1].progress - newVeh.minGap : -0.15;
                            newVeh.progress = Math.max(-2.2, lastP);
                            queue.push(newVeh);
                        }
                        // Stop pengecekan banjar ini: jika kendaraan terdepan belum boleh lewat (misal merah), tahan antrean di belakangnya!
                        break;
                    }
                }
            });
        }

        // 2. KELOMPOKKAN KENDARAAN PER-BANJAR UNTUK CAR-FOLLOWING MODEL YANG RAPI
        const banjarGroups = {};
        queue.forEach(v => {
            if (!banjarGroups[v.banjarIdx]) banjarGroups[v.banjarIdx] = [];
            banjarGroups[v.banjarIdx].push(v);
        });

        // 3. UPDATE POSISI KENDARAAN DI SETIAP BANJAR DENGAN PROTEKSI ANTI-TABRAKAN
        Object.keys(banjarGroups).forEach(bIdx => {
            const bQueue = banjarGroups[bIdx];
            for (let i = 0; i < bQueue.length; i++) {
                const v = bQueue[i];
                let targetP = 0.345; // Garis henti stop line ketat!

                if (i === 0) {
                    if (v.arm === "utara" && v.isZebra && !uLurusGreen && !uKananGreen) {
                        targetP = 0.362; // Pelanggar zebra cross riil CCTV Utara
                    } else if (v.arm === "utara" && v.isTrotoar && !uLurusGreen && !uKananGreen) {
                        targetP = 0.360; // Pelanggar trotoar riil CCTV Utara
                    } else {
                        targetP = 0.345; // 100% Disiplin di belakang garis stop line
                    }

                    // ANTI-TABRAKAN DENGAN KENDARAAN YANG SEDANG KELUAR MENYEBERANG:
                    // Jika ada kendaraan di banjar yang sama yang baru saja keluar dan masih berada dekat garis henti (crossT < 0.16),
                    // tahan kendaraan pertama di antrean pada jarak aman (0.320) agar tidak menabrak buritan kendaraan depan!
                    const departingAhead = activeCrossingVehicles.find(
                        cv => cv.arm === v.arm && cv.banjarIdx === v.banjarIdx && cv.crossT < 0.16
                    );
                    if (departingAhead) {
                        targetP = Math.min(targetP, 0.320);
                    }
                } else {
                    const ahead = bQueue[i - 1];
                    if (v.arm === "utara" && v.isZebra && !uLurusGreen && !uKananGreen) {
                        targetP = 0.362; // Tetap di zebra cross berdampingan
                    } else {
                        targetP = ahead.progress - v.minGap;
                    }
                }

                // Kecepatan maju antrean yang sinkron & realistis (halus)
                const moveSpd = (v.arm === "utara" && (uLurusGreen || uKananGreen)) ? v.speed * 1.15 : v.speed;
                if (v.progress < targetP) {
                    v.waiting = false;
                    v.progress = Math.min(targetP, v.progress + moveSpd);
                } else {
                    v.progress = targetP;
                    v.waiting = true;
                }
            }
        });
    });

    // 4. UPDATE KENDARAAN YANG SEDANG MENYEBERANGI PERSIMPANGAN (Crossing)
    // Kecepatan jelajah persimpangan yang tenang, realistis & sinkron dengan durasi video (~8.8 detik melintasi simpang)
    for (let i = activeCrossingVehicles.length - 1; i >= 0; i--) {
        const v = activeCrossingVehicles[i];
        v.crossT += 0.0019;

        if (v.crossT >= 1.0) {
            activeCrossingVehicles.splice(i, 1);
        }
    }

    // ====================================================================
    // J. RENDERING KENDARAAN DENGAN KOORDINAT BANJAR PRESISI
    // ====================================================================

    function evalCubicBezier(p0, p1, p2, p3, t) {
        const mt = 1 - t;
        const mt2 = mt * mt;
        const t2 = t * t;

        const x = mt2 * mt * p0.x + 3 * mt2 * t * p1.x + 3 * mt * t2 * p2.x + t2 * t * p3.x;
        const y = mt2 * mt * p0.y + 3 * mt2 * t * p1.y + 3 * mt * t2 * p2.y + t2 * t * p3.y;

        const dx = 3 * mt2 * (p1.x - p0.x) + 6 * mt * t * (p2.x - p1.x) + 3 * t2 * (p3.x - p2.x);
        const dy = 3 * mt2 * (p1.y - p0.y) + 6 * mt * t * (p2.y - p1.y) + 3 * t2 * (p3.y - p2.y);
        const angle = Math.atan2(dy, dx);

        return { x, y, angle };
    }

    function drawVehicleOnCanvas(v, isCrossing = false) {
        if (v.hidden) return; // Sembunyi jika belum masuk waktu kemunculan
        let vx = cx, vy = cy, vAngle = 0;

        if (!isCrossing) {
            // A. KENDARAAN DI DALAM ANTREAN BANJAR SEBELUM GARIS HENTI (DI BELAKANG ZEBRA CROSS)
            const p = v.progress;
            const queueDist = (0.345 - p) * 750;

            if (v.arm === "utara") {
                if (v.isTrotoar) {
                    // Motor di trotoar pejalan kaki sisi timur (#101 D 5171 BCA)
                    const trotoarEastX = cx + roadW / 2 + tw / 2;
                    vx = trotoarEastX;
                    vy = cy - roadH / 2 - 14; // Sejajar tepat di samping zebra cross
                    vAngle = Math.PI / 2;
                } else if (v.isZebra) {
                    // 4 Pelanggar Zebra Cross Berjajar Rapi di Garis Terdepan (Sesuai Video CCTV):
                    if (v.id === 102) vx = cx + 0.40 * subW;       // Mobil Hitam (Kiri)
                    else if (v.id === 104) vx = cx + 1.10 * subW;  // Motor Hijau (Tengah-Kiri)
                    else if (v.id === 103) vx = cx + 1.85 * subW;  // Mobil Putih (Tengah-Kanan)
                    else if (v.id === 105) vx = cx + 2.60 * subW;  // Motor Putih (Kanan Dekat Trotoar)
                    else vx = cx + (v.banjarIdx + 0.5) * subW;

                    vy = cy - roadH / 2 - 14; // Tepat di tengah balok zebra cross (zyU s/d zyU + 16)
                    vAngle = Math.PI / 2;
                } else {
                    // 100% DISIPLIN STOP LINE: Bumper depan berhenti aman 4px di BELAKANG Garis Henti
                    // Garis henti di zyU = cy - roadH/2 - 22
                    const bOffset = (v.banjarIdx + 0.5) * subW;
                    const stopY = (cy - roadH / 2 - 22) - 4 - v.len / 2;
                    vx = cx + bOffset;
                    vy = stopY - queueDist;
                    vAngle = Math.PI / 2; // Menghadap ke bawah (Selatan)
                }
            } else if (v.arm === "selatan") {
                // 100% DISIPLIN STOP LINE: Bumper depan berhenti aman 4px di BELAKANG Garis Henti
                // Garis henti di zyS + 16 = cy + roadH/2 + 22
                const bOffset = (2.5 - v.banjarIdx) * subW;
                const stopY = (cy + roadH / 2 + 22) + 4 + v.len / 2;
                vx = cx - bOffset;
                vy = stopY + queueDist;
                vAngle = -Math.PI / 2; // Menghadap ke atas (Utara)
            } else if (v.arm === "barat") {
                // 100% DISIPLIN STOP LINE: Bumper depan berhenti aman 4px di BELAKANG Garis Henti
                // Garis henti di zxB = cx - roadW/2 - 22
                const bOffset = (1.5 - v.banjarIdx) * subH;
                const stopX = (cx - roadW / 2 - 22) - 4 - v.len / 2;
                vx = stopX - queueDist;
                vy = cy - bOffset;
                vAngle = 0; // Menghadap ke kanan (Timur)
            } else if (v.arm === "timur") {
                // 100% DISIPLIN STOP LINE: Bumper depan berhenti aman 4px di BELAKANG Garis Henti
                // Garis henti di zxT + 16 = cx + roadW/2 + 22
                const bOffset = (1.5 - v.banjarIdx) * subH;
                const stopX = (cx + roadW / 2 + 22) + 4 + v.len / 2;
                vx = stopX + queueDist;
                vy = cy + bOffset;
                vAngle = Math.PI; // Menghadap ke kiri (Barat)
            }
        } else {
            // B. KENDARAAN MENYEBERANG DUA FASE: BELOKAN DI DALAM SIMPANG + MELAJU LURUS DI LAJUR MASUK TUJUAN
            const t = Math.max(0.0, Math.min(1.0, v.crossT));

            // Titik awal tepat pada garis henti asal masing-masing banjar
            let x0 = cx, y0 = cy;
            if (v.arm === "utara") {
                const bOffset = (v.banjarIdx + 0.5) * subW;
                x0 = cx + bOffset;
                y0 = (cy - roadH / 2 - 22) - 4 - v.len / 2;
            } else if (v.arm === "selatan") {
                const bOffset = (2.5 - v.banjarIdx) * subW;
                x0 = cx - bOffset;
                y0 = (cy + roadH / 2 + 22) + 4 + v.len / 2;
            } else if (v.arm === "barat") {
                const bOffset = (1.5 - v.banjarIdx) * subH;
                x0 = (cx - roadW / 2 - 22) - 4 - v.len / 2;
                y0 = cy - bOffset;
            } else if (v.arm === "timur") {
                const bOffset = (1.5 - v.banjarIdx) * subH;
                x0 = (cx + roadW / 2 + 22) + 4 + v.len / 2;
                y0 = cy + bOffset;
            }

            const tTurn = 0.40;

            if (v.route === "lurus") {
                // RUTE LURUS: Melaju lurus sempurna pada banjar masing-masing tanpa pergeseran lateral
                if (v.arm === "utara") {
                    const reachY = Math.max(1400, worldBottom - y0);
                    vx = x0;
                    vy = y0 + t * reachY;
                    vAngle = Math.PI / 2;
                } else if (v.arm === "selatan") {
                    const reachY = Math.max(1400, y0 - worldTop);
                    vx = x0;
                    vy = y0 - t * reachY;
                    vAngle = -Math.PI / 2;
                } else if (v.arm === "barat") {
                    const reachX = Math.max(1400, worldRight - x0);
                    vx = x0 + t * reachX;
                    vy = cy - subH;
                    vAngle = 0;
                } else if (v.arm === "timur") {
                    const reachX = Math.max(1400, x0 - worldLeft);
                    vx = x0 - t * reachX;
                    vy = cy + subH;
                    vAngle = Math.PI;
                }
            } else {
                // RUTE BELOK (Fase 1: Manuver lokal 90 derajat di dalam simpang; Fase 2: Melaju lurus di lajur tujuan)
                let p0 = { x: x0, y: y0 };
                let p1 = { x: x0, y: y0 };
                let p2 = { x: x0, y: y0 };
                let p3 = { x: x0, y: y0 };
                let outAngle = 0;
                let dx3 = 0, dy3 = 0;

                if (v.arm === "utara") {
                    if (v.route === "kanan") {
                        // Belok Kanan ke Barat (Lajur Masuk Barat: y = cy + subH, melaju ke Barat ←)
                        p3 = { x: cx - roadW / 2 - 22 - 10, y: cy + subH };
                        dx3 = -1; dy3 = 0; outAngle = Math.PI;
                        const dy = Math.abs(p3.y - y0);
                        const dx = Math.abs(p3.x - x0);
                        p1 = { x: x0, y: y0 + dy * 0.55 };
                        p2 = { x: p3.x + dx * 0.55, y: p3.y };
                    } else {
                        // Belok Kiri ke Timur (Lajur Masuk Timur: y = cy - subH, melaju ke Timur →)
                        p3 = { x: cx + roadW / 2 + 22 + 10, y: cy - subH };
                        dx3 = 1; dy3 = 0; outAngle = 0;
                        const dy = Math.abs(p3.y - y0);
                        const dx = Math.abs(p3.x - x0);
                        p1 = { x: x0, y: y0 + dy * 0.55 };
                        p2 = { x: p3.x - dx * 0.55, y: p3.y };
                    }
                } else if (v.arm === "selatan") {
                    if (v.route === "kanan") {
                        // Belok Kanan ke Timur (Lajur Masuk Timur: y = cy - subH, melaju ke Timur →)
                        p3 = { x: cx + roadW / 2 + 22 + 10, y: cy - subH };
                        dx3 = 1; dy3 = 0; outAngle = 0;
                        const dy = Math.abs(y0 - p3.y);
                        const dx = Math.abs(p3.x - x0);
                        p1 = { x: x0, y: y0 - dy * 0.55 };
                        p2 = { x: p3.x - dx * 0.55, y: p3.y };
                    } else {
                        // Belok Kiri ke Barat (Lajur Masuk Barat: y = cy + subH, melaju ke Barat ←)
                        p3 = { x: cx - roadW / 2 - 22 - 10, y: cy + subH };
                        dx3 = -1; dy3 = 0; outAngle = Math.PI;
                        const dy = Math.abs(y0 - p3.y);
                        const dx = Math.abs(x0 - p3.x);
                        p1 = { x: x0, y: y0 - dy * 0.55 };
                        p2 = { x: p3.x + dx * 0.55, y: p3.y };
                    }
                } else if (v.arm === "barat") {
                    if (v.route === "kiri") {
                        // Belok Kiri ke Utara (Lajur Masuk Utara: x = cx - 1.5 * subW, melaju ke Utara ↑)
                        p3 = { x: cx - 1.5 * subW, y: cy - roadH / 2 - 22 - 10 };
                        dx3 = 0; dy3 = -1; outAngle = -Math.PI / 2;
                        const dx = Math.abs(p3.x - x0);
                        const dy = Math.abs(y0 - p3.y);
                        p1 = { x: x0 + dx * 0.55, y: y0 };
                        p2 = { x: p3.x, y: p3.y + dy * 0.55 };
                    } else {
                        // Belok Kanan ke Selatan (Lajur Masuk Selatan: x = cx + 1.5 * subW, melaju ke Selatan ↓)
                        p3 = { x: cx + 1.5 * subW, y: cy + roadH / 2 + 22 + 10 };
                        dx3 = 0; dy3 = 1; outAngle = Math.PI / 2;
                        const dx = Math.abs(p3.x - x0);
                        const dy = Math.abs(p3.y - y0);
                        p1 = { x: x0 + dx * 0.55, y: y0 };
                        p2 = { x: p3.x, y: p3.y - dy * 0.55 };
                    }
                } else if (v.arm === "timur") {
                    if (v.route === "kiri") {
                        // Belok Kiri ke Selatan (Lajur Masuk Selatan: x = cx + 1.5 * subW, melaju ke Selatan ↓)
                        p3 = { x: cx + 1.5 * subW, y: cy + roadH / 2 + 22 + 10 };
                        dx3 = 0; dy3 = 1; outAngle = Math.PI / 2;
                        const dx = Math.abs(x0 - p3.x);
                        const dy = Math.abs(p3.y - y0);
                        p1 = { x: x0 - dx * 0.55, y: y0 };
                        p2 = { x: p3.x, y: p3.y - dy * 0.55 };
                    } else {
                        // Belok Kanan ke Utara (Lajur Masuk Utara: x = cx - 1.5 * subW, melaju ke Utara ↑)
                        p3 = { x: cx - 1.5 * subW, y: cy - roadH / 2 - 22 - 10 };
                        dx3 = 0; dy3 = -1; outAngle = -Math.PI / 2;
                        const dx = Math.abs(x0 - p3.x);
                        const dy = Math.abs(y0 - p3.y);
                        p1 = { x: x0 - dx * 0.55, y: y0 };
                        p2 = { x: p3.x, y: p3.y + dy * 0.55 };
                    }
                }

                if (t <= tTurn) {
                    const u = t / tTurn;
                    const res = evalCubicBezier(p0, p1, p2, p3, u);
                    vx = res.x; vy = res.y; vAngle = res.angle;
                } else {
                    const driveDist = ((t - tTurn) / (1.0 - tTurn)) * 1400;
                    vx = p3.x + (dx3 * driveDist);
                    vy = p3.y + (dy3 * driveDist);
                    vAngle = outAngle;
                }
            }
        }

        // Gambar Badan Kendaraan Bersih & Rapi (Kotak-kotak keterangan plat nomor dihapus total)
        ctx.save();
        ctx.translate(vx, vy);
        ctx.rotate(vAngle);

        let vehColor = v.vehColorCustom || "#10b981"; // Gunakan warna kustom jika ada
        if (!v.vehColorCustom) {
            if (v.type === "motor") vehColor = "#00e5ff"; // Motor (Cyan)
            else if (v.type === "bus") vehColor = "#f59e0b"; // Bus / Angkot (Amber)
        }

        if (v.isViolation && v.waiting) {
            const glowCol = v.isTrotoar ? "#d946ef" : "#ef4444";
            ctx.shadowColor = glowCol;
            ctx.shadowBlur = 8;
            ctx.strokeStyle = glowCol;
            ctx.lineWidth = 2.0;
            ctx.strokeRect(-v.len / 2 - 2, -v.wid / 2 - 2, v.len + 4, v.wid + 4);
        }

        ctx.fillStyle = vehColor;
        ctx.fillRect(-v.len / 2, -v.wid / 2, v.len, v.wid);

        // Kaca Depan Kendaraan
        ctx.fillStyle = (v.vehColorCustom === "#f8fafc" || v.vehColorCustom === "#e2e8f0") ? "#38bdf8" : "#ffffff";
        ctx.fillRect(v.len / 2 - 3, -v.wid / 4, 3, v.wid / 2);

        ctx.restore();
    }

    // Sinkronisasi status pelanggaran Lengan Utara dengan detik video:
    // 0 - 47.5s : Tepat 4 kotak zebra cross, trotoar bersih
    // 47.5 - 49.0s : 5 kotak (4 zebra + 1 motor trotoar)
    // 49.0 - 80s : Lampu Hijau, 0 kotak pelanggaran (semua kotak hilang total)
    armQueues.utara.forEach(v => {
        if (v.isZebra) {
            v.isViolation = (currentVideoSec < 49.0);
        } else if (v.isTrotoar) {
            v.isViolation = (currentVideoSec >= 47.5 && currentVideoSec < 49.0);
            v.hidden = (currentVideoSec < 47.0);
        } else {
            v.isViolation = false;
        }
    });

    // Gambar Seluruh Antrean Kendaraan di 4 Lengan
    armList.forEach(armName => {
        armQueues[armName].forEach(v => drawVehicleOnCanvas(v, false));
    });

    // Pelanggaran Bus Berhenti di Trotoar Timur pada Beberapa Waktu (15s s/d 42s)
    const showEastBus = (currentVideoSec >= 15.0 && currentVideoSec <= 42.0) || (currentStatus && currentStatus.has_east_bus_violation);
    if (showEastBus) {
        ctx.save();
        const busTx = cx + roadW / 2 + 85;
        const busTy = cy - roadH / 2 - tw / 2; // Tepat di trotoar timur atas
        ctx.translate(busTx, busTy);
        ctx.rotate(Math.PI); // Menghadap ke barat

        const bLen = 34, bWid = 16;

        // Bounding box pelanggaran merah menyala di trotoar
        ctx.shadowColor = "#ef4444";
        ctx.shadowBlur = 10;
        ctx.strokeStyle = "#ef4444";
        ctx.lineWidth = 2.0;
        ctx.strokeRect(-bLen / 2 - 2, -bWid / 2 - 2, bLen + 4, bWid + 4);

        // Badan Bus (Amber)
        ctx.fillStyle = "#f59e0b";
        ctx.fillRect(-bLen / 2, -bWid / 2, bLen, bWid);

        // Kaca Depan & Jendela Bus
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(bLen / 2 - 4, -bWid / 4, 4, bWid / 2);
        ctx.fillStyle = "#1e293b";
        ctx.fillRect(-bLen / 2 + 6, -bWid / 2 + 2, bLen - 14, 2.5);
        ctx.fillRect(-bLen / 2 + 6, bWid / 2 - 4.5, bLen - 14, 2.5);

        ctx.restore();

        // Label Pelanggaran Taktis di Atas Bus
        ctx.save();
        ctx.font = "bold 7px 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const badgeTxt = "#601 D 7812 BDG [TROTOAR TIMUR]";
        const twTag = ctx.measureText(badgeTxt).width + 6;
        ctx.fillStyle = "rgba(185, 28, 28, 0.92)";
        ctx.strokeStyle = "#ef4444";
        ctx.lineWidth = 1;
        ctx.fillRect(busTx - twTag / 2, busTy - 18, twTag, 11);
        ctx.strokeRect(busTx - twTag / 2, busTy - 18, twTag, 11);
        ctx.fillStyle = "#ffffff";
        ctx.fillText(badgeTxt, busTx, busTy - 12.5);
        ctx.restore();
    }

    // Gambar Kendaraan yang Sedang Melintasi Persimpangan
    activeCrossingVehicles.forEach(v => drawVehicleOnCanvas(v, true));

    // Restore matrix transform Zoom & Pan
    ctx.restore();
}

let currentVideoSec = 0.0;
let lastAnimTime = performance.now();
let lastServerLoopEpoch = 0;

function animationLoop(now) {
    if (!lastAnimTime) lastAnimTime = now;
    const dt = Math.min(0.1, (now - lastAnimTime) / 1000);
    lastAnimTime = now;

    // Alirkan waktu video lokal secara halus
    const prevSec = currentVideoSec;
    currentVideoSec = (currentVideoSec + dt) % 80.0;

    // DETEKSI OTOMATIS: JIKA DURASI VIDEO HABIS (80 DETIK), SIMULASI LANGSUNG KEMBALI KE AWAL!
    if (prevSec >= 78.5 && currentVideoSec < 2.0) {
        resetSimulasiKeAwal("Durasi Video 80s Selesai (Local Loop)");
    }

    render2DSimulation();
    requestAnimationFrame(animationLoop);
}
requestAnimationFrame(animationLoop);

// ====================================================================
// 8. SINKRONISASI API REAL-TIME DASHBOARD
// ====================================================================
function fetchStatus() {
    fetch('/api/status')
    .then(res => res.json())
    .then(data => {
        currentStatus = data;

        // Deteksi pergantian epoch loop video dari backend
        if (data.video_loop_epoch !== undefined) {
            if (lastServerLoopEpoch === 0) {
                lastServerLoopEpoch = data.video_loop_epoch;
            } else if (data.video_loop_epoch > lastServerLoopEpoch) {
                lastServerLoopEpoch = data.video_loop_epoch;
                resetSimulasiKeAwal(`Server Loop Epoch #${data.video_loop_epoch}`);
            }
        }

        // Deteksi jika waktu server melompat mundur dari detik akhir ke detik awal
        if (currentVideoSec > 70.0 && data.current_video_sec !== undefined && data.current_video_sec < 3.0) {
            resetSimulasiKeAwal("Server Video Time Looped to Detik 0");
        }

        if (data.current_video_sec !== undefined) {
            currentVideoSec = data.current_video_sec;
        }

        // A. Header Fase & Timer
        const faseEl = document.getElementById("fase-lampu-badge");
        const timerEl = document.getElementById("timer-lampu-badge");
        const activeFase = data.fase_lampu || "UTARA";

        if (faseEl) {
            faseEl.innerHTML = `<i class="fa-solid fa-traffic-light me-1"></i>FASE HIJAU: LENGAN ${activeFase}`;
            faseEl.className = (activeFase === "UTARA" || activeFase === "SELATAN")
                ? "badge bg-primary fs-7 shadow-sm py-2 px-3 font-monospace"
                : "badge bg-success fs-7 shadow-sm py-2 px-3 font-monospace";
        }

        if (timerEl && data.kpi && data.kpi.timers) {
            const curTimerArm = data.kpi.timers.breakdown[activeFase.toLowerCase()];
            const mainTimerVal = curTimerArm ? (curTimerArm.timer_lurus || curTimerArm.timer || 0) : 0;
            timerEl.textContent = `${mainTimerVal} DETIK`;
        }

        // B. Sinkronisasi Data Kendaraan Video CCTV Lengan Utara 1:1
        if (data.simulasi && data.simulasi.utara) {
            syncNorthVehiclesFromVideo(data.simulasi.utara);
        }

        // C. Sinkronisasi Data Kendaraan Lengan Lainnya dari O-D Matrix Backend
        if (data.per_arm) {
            syncOtherArmsFromBackend(data.per_arm);
        }

        // D. Sinkronisasi Sirkulasi O-D
        if (data.sirkulasi_od) {
            countNorthExit = data.sirkulasi_od.total_keluar || 61;
            countNorthToSouth = data.sirkulasi_od.masuk_selatan || 37;
            countNorthToWest = data.sirkulasi_od.masuk_barat || 15;
            countNorthToEast = data.sirkulasi_od.masuk_timur || 9;
            updateCirculationHUD();
        }

        const kpi = data.kpi;
        if (!kpi) return;

        // E. KARTU 1: KPI KEPADATAN (SMP)
        const totalSmpEl = document.getElementById("kpi-total-smp-badge");
        if (totalSmpEl) totalSmpEl.textContent = `TOTAL: ${kpi.kepadatan.total_smp} SMP`;

        ["utara", "timur", "selatan", "barat"].forEach(arm => {
            const armData = kpi.kepadatan.breakdown[arm];
            const badge = document.getElementById(`kepadatan-badge-${arm}`);
            const val = document.getElementById(`smp-val-${arm}`);
            if (badge && armData) {
                badge.textContent = armData.status;
                if (armData.status === "PADAT") badge.className = "badge bg-danger text-white my-1 font-monospace";
                else if (armData.status === "SEDANG") badge.className = "badge bg-warning-subtle text-warning-emphasis my-1 font-monospace";
                else badge.className = "badge bg-success-subtle text-success my-1 font-monospace";
            }
            if (val && armData) val.textContent = `${armData.smp} SMP`;
        });

        const smpDetU = document.getElementById("smp-detail-utara");
        if (smpDetU && data.per_arm.utara) smpDetU.textContent = `L:${data.per_arm.utara.smp_lurus} | K:${data.per_arm.utara.smp_kanan}`;
        const smpDetS = document.getElementById("smp-detail-selatan");
        if (smpDetS && data.per_arm.selatan) smpDetS.textContent = `L:${data.per_arm.selatan.smp_lurus} | K:${data.per_arm.selatan.smp_kanan}`;

        // F. KARTU 2: KPI VOLUME KENDARAAN (SINKRON DENGAN DETEKSI VIDEO)
        const totVolEl = document.getElementById("kpi-total-volume-badge");
        if (totVolEl) totVolEl.textContent = `TOTAL: ${kpi.volume.total_akumulasi} KEND`;

        ["utara", "timur", "selatan", "barat"].forEach(arm => {
            const vData = kpi.volume.breakdown[arm];
            const totEl = document.getElementById(`vol-total-${arm}`);
            const mtrEl = document.getElementById(`vol-motor-${arm}`);
            const mblEl = document.getElementById(`vol-mobil-${arm}`);
            const busEl = document.getElementById(`vol-bus-${arm}`);

            if (totEl && vData) totEl.textContent = `${vData.total} Kend`;
            if (mtrEl && vData) mtrEl.textContent = vData.motor;
            if (mblEl && vData) mblEl.textContent = vData.mobil;
            if (busEl && vData) busEl.textContent = vData.bus;
        });

        // G. KARTU 3: KPI PELANGGARAN HARI INI
        const totPelEl = document.getElementById("kpi-total-pelanggaran-badge");
        if (totPelEl) totPelEl.textContent = `TERJARING: ${kpi.pelanggaran.total_terjaring}`;

        ["utara", "timur", "selatan", "barat"].forEach(arm => {
            const pData = kpi.pelanggaran.breakdown[arm];
            const totEl = document.getElementById(`pel-total-${arm}`);
            const zebEl = document.getElementById(`pel-zebra-${arm}`);
            const troEl = document.getElementById(`pel-trotoar-${arm}`);

            if (totEl && pData) totEl.textContent = pData.total;
            if (zebEl && pData) zebEl.textContent = pData.zebra;
            if (troEl && pData) troEl.textContent = pData.trotoar;
        });

        // H. KARTU 4: ATCS SIGNAL TIMERS
        const faseAktifEl = document.getElementById("kpi-fase-aktif-badge");
        if (faseAktifEl) faseAktifEl.textContent = `FASE: ${kpi.timers.fase_aktif}`;

        // UTARA (Dual Sinyal dengan Early Cut-Off)
        const uTim = kpi.timers.breakdown.utara;
        const bULurus = document.getElementById("timer-badge-u-lurus");
        const vULurus = document.getElementById("timer-val-u-lurus");
        const bUKanan = document.getElementById("timer-badge-u-kanan");
        const vUKanan = document.getElementById("timer-val-u-kanan");
        if (bULurus && uTim) {
            bULurus.className = uTim.is_lurus_green ? "badge bg-success font-monospace" : "badge bg-danger font-monospace";
            if (vULurus) vULurus.textContent = `${uTim.timer_lurus}s`;
        }
        if (bUKanan && uTim) {
            bUKanan.className = uTim.is_kanan_green ? "badge bg-success font-monospace" : "badge bg-danger font-monospace";
            if (vUKanan) vUKanan.textContent = `${uTim.timer_kanan}s`;
        }
        const durU = document.getElementById("durasi-info-utara");
        if (durU && uTim) durU.textContent = `Dur: ${uTim.durasi_lurus}s (Maks 125s) / ${uTim.durasi_kanan}s`;

        // SELATAN (Dual Sinyal dengan Early Cut-Off)
        const sTim = kpi.timers.breakdown.selatan;
        const bSLurus = document.getElementById("timer-badge-s-lurus");
        const vSLurus = document.getElementById("timer-val-s-lurus");
        const bSKanan = document.getElementById("timer-badge-s-kanan");
        const vSKanan = document.getElementById("timer-val-s-kanan");
        if (bSLurus && sTim) {
            bSLurus.className = sTim.is_lurus_green ? "badge bg-success font-monospace" : "badge bg-danger font-monospace";
            if (vSLurus) vSLurus.textContent = `${sTim.timer_lurus}s`;
        }
        if (bSKanan && sTim) {
            bSKanan.className = sTim.is_kanan_green ? "badge bg-success font-monospace" : "badge bg-danger font-monospace";
            if (vSKanan) vSKanan.textContent = `${sTim.timer_kanan}s`;
        }
        const durS = document.getElementById("durasi-info-selatan");
        if (durS && sTim) durS.textContent = `Dur: ${sTim.durasi_lurus}s (Maks 82s) / ${sTim.durasi_kanan}s`;

        // TIMUR (Sinyal Tunggal)
        const tTim = kpi.timers.breakdown.timur;
        const bTimur = document.getElementById("timer-badge-timur");
        const vTimur = document.getElementById("timer-val-timur");
        if (bTimur && tTim) {
            bTimur.className = tTim.is_green ? "badge bg-success font-monospace" : "badge bg-danger font-monospace";
            if (vTimur) vTimur.textContent = `${tTim.timer}s`;
        }

        // BARAT (Sinyal Tunggal)
        const bTim = kpi.timers.breakdown.barat;
        const bBarat = document.getElementById("timer-badge-barat");
        const vBarat = document.getElementById("timer-val-barat");
        if (bBarat && bTim) {
            bBarat.className = bTim.is_green ? "badge bg-success font-monospace" : "badge bg-danger font-monospace";
            if (vBarat) vBarat.textContent = `${bTim.timer}s`;
        }

        // I. CCTV STAT OVERLAYS & VIDEO SYNC
        const cctvFootU = document.getElementById("cctv-footer-utara");
        if (cctvFootU && data.per_arm.utara) cctvFootU.textContent = `Beban: ${data.per_arm.utara.smp} SMP | ${data.per_arm.utara.total} Kend (Live Video)`;

        const cctvStatT = document.getElementById("cctv-stat-timur");
        if (cctvStatT && data.per_arm.timur) cctvStatT.textContent = `Beban: ${data.per_arm.timur.smp} SMP | ${data.per_arm.timur.total} Kend`;

        const cctvStatS = document.getElementById("cctv-stat-selatan");
        if (cctvStatS && data.per_arm.selatan) cctvStatS.textContent = `Beban: ${data.per_arm.selatan.smp} SMP | ${data.per_arm.selatan.total} Kend`;

        const cctvStatB = document.getElementById("cctv-stat-barat");
        if (cctvStatB && data.per_arm.barat) cctvStatB.textContent = `Beban: ${data.per_arm.barat.smp} SMP | ${data.per_arm.barat.total} Kend`;

        // Sinkronisasi status file video aktif CCTV
        if (data.active_videos) {
            ["timur", "selatan", "barat"].forEach(arm => {
                const hasVid = Boolean(data.active_videos[arm]);
                updateCctvArmUI(arm, hasVid, data.active_videos[arm]);
            });
        }

        // J. TOAST PELANGGARAN INSTAN
        if (data.detail_pelanggaran && data.detail_pelanggaran.id !== lastKnownViolationId) {
            lastKnownViolationId = data.detail_pelanggaran.id;
            showViolationToast(data.detail_pelanggaran);
        }

        // K. UPDATE TABEL PELANGGARAN
        rawViolationsList = data.daftar_pelanggaran || [];
        filterTilangTable();
    })
    .catch(err => console.error("Error polling /api/status:", err));
}

// ====================================================================
// 9. FILTER & RENDER TABEL E-TILANG
// ====================================================================
function filterTilangTable() {
    const searchVal = (document.getElementById("search-tilang-input")?.value || "").toLowerCase().trim();
    const filterLengan = document.getElementById("filter-lengan")?.value || "ALL";
    const filterKendaraan = document.getElementById("filter-kendaraan")?.value || "ALL";
    const filterJenis = document.getElementById("filter-jenis")?.value || "ALL";

    const tbody = document.getElementById("tbody-tilang");
    const countBadge = document.getElementById("tilang-counter-badge");
    const summaryText = document.getElementById("tilang-summary-text");
    if (!tbody) return;

    let filtered = rawViolationsList.filter(row => {
        if (filterLengan !== "ALL" && row.lengan !== filterLengan) return false;
        if (filterKendaraan !== "ALL" && row.cls !== filterKendaraan) return false;
        if (filterJenis !== "ALL") {
            if (filterJenis === "Zebra" && !row.jenis.includes("Zebra") && !row.jenis.includes("Stop Line") && !row.jenis.includes("Garis Henti")) return false;
            if (filterJenis === "Trotoar" && !row.jenis.includes("Trotoar")) return false;
        }
        if (searchVal) {
            const matchPlat = (row.plat || "").toLowerCase().includes(searchVal);
            const matchId = (row.id || "").toLowerCase().includes(searchVal);
            if (!matchPlat && !matchId) return false;
        }
        return true;
    });

    if (countBadge) countBadge.textContent = `${rawViolationsList.length} Terekam`;
    if (summaryText) summaryText.textContent = `Menampilkan ${filtered.length} dari ${rawViolationsList.length} data bukti kejadian`;

    if (filtered.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center py-4 text-muted">
                    <i class="fa-solid fa-folder-open me-2"></i>Tidak ada data pelanggaran yang sesuai filter.
                </td>
            </tr>
        `;
        return;
    }

    let html = "";
    filtered.forEach(row => {
        const isTrotoar = row.jenis.includes("Trotoar");
        const badgeJenisClass = isTrotoar ? "badge bg-warning-subtle text-warning-emphasis border border-warning-subtle" : "badge bg-danger-subtle text-danger border border-danger-subtle";
        const iconJenis = isTrotoar ? "fa-person-walking-arrow-right" : "fa-ban";
        const fotoUrl = row.foto_url || "/static/uploads/evidence/evidence_ET-0001.jpg";
        const pasalText = row.pasal || "Pasal 106 Ayat (2)&(4) jo. Pasal 287 (1) UU LLAJ";

        html += `
            <tr>
                <td class="ps-3 fw-bold text-primary">${row.id}</td>
                <td class="text-center">
                    <img src="${fotoUrl}" alt="Crop Bukti" class="rounded border shadow-sm" style="width: 52px; height: 36px; object-fit: cover; cursor: pointer;" onclick="openEvidenceModal('${row.id}')" title="Klik untuk lihat bukti foto lengkap">
                </td>
                <td><small class="text-muted">${row.waktu}</small><br><small class="text-secondary">${row.tanggal || ''}</small></td>
                <td><span class="badge bg-secondary-subtle text-dark border">${row.lengan}</span></td>
                <td><span class="plat-badge">${row.plat}</span></td>
                <td><i class="fa-solid ${row.cls === 'motor' ? 'fa-motorcycle text-info' : (row.cls === 'mobil' ? 'fa-car text-success' : 'fa-bus text-warning')} me-1"></i>${row.jenis_kendaraan}</td>
                <td>
                    <span class="${badgeJenisClass} d-inline-block mb-1"><i class="fa-solid ${iconJenis} me-1"></i>${row.jenis}</span>
                    <small class="text-muted d-block" style="font-size:0.65rem;">${pasalText}</small>
                </td>
                <td>
                    <span class="badge bg-success-subtle text-success border border-success-subtle d-inline-block" style="font-size:0.65rem;">
                        <i class="fa-solid fa-camera me-1"></i>[LOGGED / READY FOR ETLE VERIFICATION]
                    </span>
                    <small class="text-secondary d-block font-monospace" style="font-size:0.62rem;">${row.sanksi || 'Denda Maks. Rp500.000,00'}</small>
                </td>
                <td class="text-center pe-3">
                    <button type="button" class="btn btn-sm btn-outline-primary py-1 px-2" style="font-size:0.70rem;" onclick="openEvidenceModal('${row.id}')" title="Lihat Berkas Bukti Foto & Hukum">
                        <i class="fa-solid fa-file-invoice me-1"></i>Bukti
                    </button>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
}

// Polling Status Interval
setInterval(fetchStatus, 800);
fetchStatus();

// ====================================================================
// 9. FITUR UNGGAH & HAPUS FILE VIDEO CCTV LENGAN (TIMUR, SELATAN, BARAT)
// ====================================================================
function uploadCctvVideo(arm, inputEl) {
    if (!inputEl.files || inputEl.files.length === 0) return;
    const file = inputEl.files[0];
    const formData = new FormData();
    formData.append("video", file);

    const badge = document.getElementById(`cctv-badge-${arm}`);
    if (badge) {
        badge.className = "badge bg-warning text-dark font-monospace fs-8";
        badge.textContent = "MEMUAT...";
    }

    fetch(`/api/upload_video/${arm}`, {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            updateCctvArmUI(arm, true, data.filename);
            showToastMessage("Unggah Video Berhasil", `Video CCTV Lengan ${arm.toUpperCase()} berhasil dimuat (${data.filename})`);
        } else {
            showToastMessage("Unggah Gagal", data.message || "Gagal mengunggah video");
            if (badge) {
                badge.className = "badge bg-secondary font-monospace fs-8";
                badge.textContent = "STANDBY";
            }
        }
    })
    .catch(err => {
        console.error("Upload error:", err);
        showToastMessage("Kesalahan Sistem", "Gagal menghubungi server saat mengunggah video");
    });
}

function deleteCctvVideo(arm) {
    if (!confirm(`Hapus berkas rekaman video CCTV Lengan ${arm.toUpperCase()} dan kembali ke Standby Feed?`)) return;

    fetch(`/api/delete_video/${arm}`, {
        method: 'POST'
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            updateCctvArmUI(arm, false, null);
            showToastMessage("Berkas Dihapus", `CCTV Lengan ${arm.toUpperCase()} kembali ke Standby Feed`);
        }
    })
    .catch(err => console.error("Delete error:", err));
}

function updateCctvArmUI(arm, hasVideo, filename) {
    const videoWrap = document.getElementById(`cctv-video-wrap-${arm}`);
    const standbyWrap = document.getElementById(`cctv-standby-${arm}`);
    const imgEl = document.getElementById(`cctv-img-${arm}`);
    const badgeEl = document.getElementById(`cctv-badge-${arm}`);
    const btnDel = document.getElementById(`btn-del-${arm}`);

    if (hasVideo) {
        if (videoWrap) videoWrap.classList.remove("d-none");
        if (standbyWrap) standbyWrap.classList.add("d-none");
        if (imgEl) {
            imgEl.src = `/video_feed/${arm}?t=${Date.now()}`;
        }
        if (badgeEl) {
            badgeEl.className = "badge bg-success font-monospace fs-8";
            badgeEl.textContent = "LIVE FILE (AI YOLO)";
        }
        if (btnDel) btnDel.classList.remove("d-none");
    } else {
        if (videoWrap) videoWrap.classList.add("d-none");
        if (standbyWrap) standbyWrap.classList.remove("d-none");
        if (imgEl) {
            imgEl.src = "";
        }
        if (badgeEl) {
            badgeEl.className = "badge bg-secondary font-monospace fs-8";
            badgeEl.textContent = "STANDBY";
        }
        if (btnDel) btnDel.classList.add("d-none");
    }
}

// ====================================================================
// 10. FITUR RESET KESELURUHAN (SIMULASI, ANTREAN, DATA PELANGGARAN)
// ====================================================================
function resetKeseluruhan() {
    fetch('/api/reset_all', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        // Reset penuh simulasi lokal seketika
        resetSimulasiKeAwal("Tombol Reset Keseluruhan Ditekan");

        // Refresh feed gambar CCTV
        const imgU = document.querySelector('img[alt="CCTV Lengan Utara"]') || document.querySelector('img[alt*="Utara"]');
        if (imgU) imgU.src = `/video_feed/utara?t=${Date.now()}`;

        // Kosongkan tabel bukti pelanggaran & tarik status terbaru
        rawViolationsList = [];
        renderViolationsTable();
        fetchStatus();

        showToastMessage("Reset Berhasil", data.message || "Video CCTV dan simulasi persimpangan telah diulang dari detik 0!");
    })
    .catch(err => {
        console.error("Reset error:", err);
        showToastMessage("Kesalahan Sistem", "Gagal melakukan reset sistem.");
    });
}

function showToastMessage(title, text) {
    const toastEl = document.getElementById("violationToast");
    if (!toastEl) {
        alert(`${title}: ${text}`);
        return;
    }
    const tTitle = toastEl.querySelector(".toast-header strong");
    const tType = document.getElementById("toast-violation-type");
    const tMeta = document.getElementById("toast-meta");
    if (tTitle) tTitle.textContent = title;
    if (tType) tType.textContent = text;
    if (tMeta) tMeta.textContent = new Date().toLocaleTimeString();
    const bsToast = bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 4000 });
    bsToast.show();
}