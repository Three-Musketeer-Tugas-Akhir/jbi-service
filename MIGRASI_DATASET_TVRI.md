# Migrasi Dataset TVRI ke anotasi.ai

Dokumen ini menjelaskan bentuk data TVRI, bagaimana ia dipetakan ke skema
anotasi.ai, apa yang sudah diperbaiki supaya sistem sanggup menampungnya, dan
langkah persis untuk menginjeksikan datanya.

**Jawaban singkat soal deploy: tidak ada `ALTER TABLE` dan tidak ada migrasi
Alembic.** Yang dibutuhkan hanya `git pull` + rebuild Docker, lalu menjalankan
skrip importer di dalam container API.

Rebuild-nya **wajib**, bukan sekadar restart: `requirements.txt` bertambah
`openpyxl` (dipakai kedua skrip untuk membaca workbook). `ffmpeg` sendiri sudah
ada di image sejak awal.

---

## 1. Bentuk data sumber

Di `dev 2.0/dataset TVRI` ada dua workbook, satu per bahasa isyarat. Isinya
**hanya metadata** — file `.mp4`-nya tidak ada di folder itu (lihat §5).

| | BISINDO | SIBI |
|---|---|---|
| Sheet (hari siaran) | 12 | 12 |
| Rekaman (`MEM001M-…`) | 24 | 24 |
| Segmen | 121 | 100 |
| Kalimat / klip | 7.200 | 6.141 |
| Baris rusak | 0 | 2 |

> Catatan: objektif internal menyebut **13 siaran**, tetapi tiap workbook berisi
> **12 sheet**. Tiap sheet memuat **dua** rekaman (siaran jam 10 dan jam 11),
> jadi totalnya 24 rekaman per bahasa. Kalau memang ada siaran ke-13, sheet-nya
> belum masuk ke file ini.

Nama file klip adalah kunci strukturnya:

```
MEM001M-20191111Z103928_0_0.40_7.66.mp4
└──────── rekaman ─────┘ │ └ start ┘ └ end ┘
                     segmen
```

`start`/`end` adalah **detik relatif terhadap segmen**, bukan terhadap siaran
utuh — persis arti `pipeline_transcripts.start/end` di sistem ini (ASR worker
mentranskrip video segmen, bukan video sumber). Jadi tidak ada rebasing waktu.

Dua baris di workbook SIBI tidak bisa diparsing dan **dilewati** oleh importer
(sudah dilaporkan ke log, bukan diam-diam dibuang):

- `3.Elni-20 Des 2019!A7` → isinya `ok`
- `3.Rina-11 Jan 2020!A353` → isinya URL Google Drive

### Pemetaan kolom

| Kolom XLSX | Tujuan di DB | Tampil di UI sebagai |
|---|---|---|
| Segmen Video Bahasa Isyarat | nama file klip → key MinIO | video di workspace |
| Rentang Waktu JBI | `pipeline_transcripts.start/end` | batas filmstrip |
| Transkripsi ... oleh Sistem | `pipeline_transcripts.text`, `voice_annotations.asr_text` | teks ASR |
| Penyelarasan Suara/Teks ... | `voice_annotations.ground_truth_text` | panel **"1. Baca Teks Ini (GT)"** |
| Glosa Bahasa Isyarat / Kalimat yang Diperagakan | `annotation_edits.utterance_corrections[].text` | panel **"2. Notasi Glosa"** |
| Potensi Masalah | menentukan `status` per kalimat + disimpan di `tvri_source` | kunci/buka filmstrip |
| Keterangan Annotator | `tvri_source.note` | (arsip, belum ditampilkan) |
| Nama Annotator | `tvri_source.annotator` | (arsip) |

Kolom **Penyelarasan** berisi `"OK"` kalau teks ASR sudah benar; kalau tidak, isi
selnya **adalah** teks yang sudah dikoreksi manusia. Sel kosong berarti belum
pernah direview, sehingga teks ASR dipakai apa adanya sebagai ground truth.

### Pemetaan entitas

```
rekaman  MEM001M-20191111Z103928   →  pipeline_jobs        (1 job / rekaman)
segmen   _0_                       →  pipeline_segments    (segment_index = 0)
baris                              →  pipeline_transcripts (utterance_index urut waktu)
                                   →  voice_annotations
segmen                             →  annotation_edits     (1 DRAFT berisi semua glosa)
```

Total yang akan masuk: **48 job, 221 segmen, 13.341 kalimat.**

---

## 2. Aturan status: mana yang terkunci, mana yang bisa diselaraskan

Di dataset non-iNews, FE mengunci workspace lewat dua mekanisme yang sudah ada:

- `glosaLocked = isProcessed` → **glosa selalu terkunci** untuk seluruh dataset
  TVRI. Ini memang sesuai objektif 7 & 8: pekerjaannya adalah *penyelarasan
  video*, bukan mengubah glosa.
- `isTrimLocked = isProcessed && status === 'OK'` → filmstrip hanya bisa digeser
  untuk kalimat yang statusnya **belum** `OK`.

Importer memakai kolom **Potensi Masalah** untuk menentukannya:

| Isi Potensi Masalah | `status` hasil impor | Efek di UI |
|---|---|---|
| mengandung `kesalahan waktu` | `null` | filmstrip **bisa** digeser |
| label lain saja (`kurang informasi`, `salah isyarat`, …) | `OK` | terkunci |
| kosong | `OK` | terkunci |

Alasannya: hanya "Kesalahan Waktu" yang bisa diperbaiki dengan menggeser handle.
Label lain adalah penilaian isi (informasi kurang/salah, isyarat tidak terbaca)
yang tidak bisa diselesaikan lewat trim.

Hasilnya:

| | perlu penyelarasan | terkunci |
|---|---|---|
| BISINDO | **2.399** (33%) | 4.801 |
| SIBI | **871** (14%) | 5.270 |

Kalau nanti berubah pikiran dan ingin semuanya terkunci, jalankan importer
dengan `--lock-all`.

---

## 3. Apakah sistem as-is sanggup menyelaraskan kalimat yang belum OK?

Jawaban: **ya, mekanismenya sudah ada dan tidak perlu fitur baru** — tapi ada
empat hal yang harus diperbaiki dulu, dan dua batasan yang perlu diketahui.

### Yang sudah jalan tanpa perubahan

Seluruh alur penyelarasan bekerja murni dari `pipeline_transcripts.video_path`
(klip per kalimat), **tidak** butuh video siaran utuh maupun video segmen:

- `UtteranceMergeService` menyusun tape `[N | N+1]` dari dua klip.
- Handle *end* digeser ke kanan → `UtteranceCroppingService` memotong Part A
  dari klip N + Part B dari kepala klip N+1, lalu menyambungnya.
- Handle *start* digeser ke kiri → mekanisme lookback (`include_prev=true`)
  menyambung ekor yatim kalimat N-1, lihat [`LOOKBACK_TRIM_IN.md`](./LOOKBACK_TRIM_IN.md).
- Cascade memindahkan `floor` kalimat N+1 secara idempoten.

Asumsi yang membuat ini benar adalah **klip berurutan bersambung persis**
(`end` klip N == `start` klip N+1). Di data TVRI asumsi itu terpenuhi untuk
**97%** pasangan (6.870 dari 7.079 di BISINDO, 5.828 dari 6.041 di SIBI).

### Batasan 1 — 2% kalimat punya jeda ke tetangganya

Untuk kalimat yang perlu diselaraskan:

| | trim-out ke klip berikutnya ada jeda | trim-in ke klip sebelumnya ada jeda |
|---|---|---|
| BISINDO | 47 dari 2.399 (2,0%) | 41 dari 2.399 (1,7%) |
| SIBI | 18 dari 871 (2,1%) | 19 dari 871 (2,2%) |

Pada baris-baris itu, menarik handle melewati batas klip akan menyambung
potongan yang **tidak** bersebelahan secara waktu — hasilnya *jump cut*, bukan
gerakan yang hilang tertangkap. Trim ke **dalam** (memperpendek) tetap aman.

Ini bukan bug baru — perilakunya sama di iNews. Untuk TVRI angkanya kecil
(125 sisi handle dari total 6.540 sisi pada kalimat yang perlu diselaraskan)
sehingga saya tidak mengubah logikanya. Kalau nanti mengganggu, penanganannya
adalah menonaktifkan trim lintas-klip ketika jeda terdeteksi, dan itu perlu
perubahan tersendiri.

### Batasan 2 — batas antar-segmen

`_prev_orphan_geometry` dan `_cascade_set_next_start` mencari tetangga
**lintas segmen** dalam satu job. Padahal segmen TVRI dipisah oleh bagian siaran
tanpa penerjemah, jadi kalimat terakhir segmen K dan kalimat pertama segmen K+1
bisa terpaut menit. Yang terdampak adalah kalimat pertama/terakhir sebuah
segmen yang perlu penyelarasan: 40 kalimat BISINDO (1,7%) dan 11 kalimat SIBI
(1,3%). Sama seperti Batasan 1, ini perilaku lama yang juga berlaku di iNews.

### Yang harus diperbaiki — sudah dikerjakan

| # | Masalah | Dampak kalau dibiarkan | Perbaikan |
|---|---|---|---|
| 1 | `loadJob` mengambil `getQueue({page:1, page_size:100})` lalu memfilter `job_id` di sisi klien | 121 segmen BISINDO milik satu annotator tidak muat di satu halaman → job gagal dibuka (`Job tidak ditemukan di antrian`) atau terbuka dengan sebagian kalimat hilang | endpoint `/annotations/queue` menerima `job_id`; FE memakai `getQueueForJob()` yang menelusuri semua halaman |
| 2 | Urutan antrian hanya `priority DESC, assigned_at ASC` | assignment massal menulis `assigned_at` nyaris identik → urutan baris tidak deterministik, kartu job berpindah halaman tiap polling 10 detik | ditambah tiebreaker `job_id, segment_index` |
| 3 | FE mengurutkan segmen dengan regex `segment_(\d+).mp4` dari `video_url` | segmen TVRI tidak punya video segmen → semua ter-index 0 → urutan kalimat acak | response segmen kini membawa `segment_index`; regex hanya jadi fallback |
| 4 | `_recalculate_job_status` menurunkan status job ke `NEEDS_VOICE_ANNOTATION` begitu ada satu kata ter-flag KBBI | satu edit di halaman Anotasi Suara membuat job TVRI hilang dari halaman Assign JBI dan tidak bisa di-reassign, padahal annotator sedang mengerjakannya | job yang sudah punya assignment JBI tidak lagi diturunkan statusnya |

Dua perbaikan tambahan yang ikut sekalian karena skala TVRI membuatnya terasa:

- `_build_queue_item` tadinya melakukan ±4 query per baris antrian. Dengan 121
  baris dan polling 10 detik itu ratusan query per putaran. Sekarang tiga bulk
  query, berapa pun ukuran halamannya.
- `transcript_text` di kartu antrian tadinya berisi gabungan **seluruh** teks
  segmen. Satu segmen TVRI bisa berisi 341 kalimat, jadi response antrian bisa
  membengkak ke megabyte. Sekarang dipotong 240 karakter (FE memang hanya
  menampilkan satu baris).

### Berkas yang berubah

**Backend** (`jbi-service`)

- `app/api/v1/annotations.py` — query param `job_id`, `page_size` maks 500
- `app/repositories/annotation_queue_repository.py` — filter `job_id`, urutan deterministik
- `app/services/annotation_queue_service.py` — prefetch bulk, `segment_index`, potong preview transkrip
- `app/schemas/annotation.py` — field `segment_index`
- `app/services/voice_annotation_service.py` — jangan turunkan status job yang sudah di-assign
- `scripts/import_tvri_dataset.py` — **baru**, importer

**Frontend** (`anotasi.ai-FE`)

- `src/features/annotation/annotation-api.ts` — `getQueueForJob()`
- `src/features/annotation/annotation-types.ts` — `segment_index`
- `src/features/annotation/components/annotation-page.tsx` — pakai `getQueueForJob`, urut pakai `segment_index`
- `src/features/annotation/components/annotation-queue.tsx` — `page_size` 200

---

## 4. Yang **tidak** perlu disentuh

- **Klasifikasi & Pipeline** — sudah otomatis read-only untuk dataset non-iNews
  (`isProcessedDataset` di `src/features/dataset/utils/dataset-mode.ts`), dengan
  keterangan pengganti. Selama nama dataset **tidak mengandung kata "inews"**,
  gating ini aktif sendiri.
- **3 AI service** (CV1 / ASR / CV2) — tidak dijalankan sama sekali.
- **Anotasi Suara** — halaman ini memfilter per dataset dan tidak butuh gating
  khusus. Tanpa WAV, pemutar audio kosong tapi teksnya tetap bisa diedit
  (objektif internal 3 & 4 yang akan mengisi WAV-nya).
- **Skema DB** — tidak ada kolom baru. `tvri_source` hanya key tambahan di dalam
  `annotation_edits.utterance_corrections` yang tipenya sudah JSONB.

---

## 5. Menyiapkan klip video dari Google Drive

Importer butuh satu folder datar berisi file `.mp4` dengan **nama persis seperti
kolom A**. Langkahnya:

### 5a. Buat daftar file yang dibutuhkan

```bash
python scripts/import_tvri_dataset.py \
  --xlsx "dataset TVRI/Annotator Sign Video + Transcript BISINDO.xlsx" \
  --category BISINDO --dry-run \
  --manifest /tmp/tvri_bisindo_clips.txt

python scripts/import_tvri_dataset.py \
  --xlsx "dataset TVRI/Annotator Sign Video + Transcript SIBI.xlsx" \
  --category SIBI --dry-run \
  --manifest /tmp/tvri_sibi_clips.txt
```

Hasilnya 7.200 dan 6.141 nama file. Simpan — ini juga alat verifikasi setelah
download.

### 5b. Download dari Drive

Pakai `rclone` (paling tahan untuk belasan ribu file kecil):

```bash
rclone config                       # sekali saja, buat remote bernama gdrive
rclone copy "gdrive:TVRI/BISINDO" /data/tvri/bisindo \
  --drive-shared-with-me --transfers 8 --checkers 16 --progress
```

Kalau folder Drive-nya bertingkat per siaran, ratakan dulu:

```bash
mkdir -p /data/tvri/bisindo_flat
find /data/tvri/bisindo -name '*.mp4' -exec mv -n {} /data/tvri/bisindo_flat/ \;
```

### 5c. Verifikasi kelengkapan sebelum impor

```bash
cd /data/tvri/bisindo_flat
ls > /tmp/have.txt
comm -23 <(sort /tmp/tvri_bisindo_clips.txt) <(sort /tmp/have.txt) > /tmp/missing.txt
wc -l /tmp/missing.txt        # harapan: 0
```

File yang hilang tidak menggagalkan impor — barisnya tetap masuk DB dengan
`video_path` menunjuk key yang benar, jadi klipnya bisa diunggah menyusul ke key
yang sama. Tapi selama belum ada, kalimat itu tidak bisa dibuka di workspace.

---

## 6. Menjalankan importer

Skrip ini memakai koneksi DB dan MinIO dari environment aplikasi, jadi
**jalankan di dalam container API di server**, bukan dari laptop.

### 6a. Kirim workbook + klip ke server

```bash
scp "dataset TVRI/Annotator Sign Video + Transcript BISINDO.xlsx" user@server:/srv/tvri/
rsync -av --progress /data/tvri/bisindo_flat/ user@server:/srv/tvri/clips_bisindo/
```

Lalu mount foldernya ke container (tambahkan di `docker-compose.yml` service
`api` / `api-gpu`, atau pakai `docker cp` untuk sekali jalan):

```yaml
    volumes:
      - /srv/tvri:/srv/tvri:ro
```

### 6b. Dry run — tidak menulis apa pun

```bash
docker compose exec -T api python scripts/import_tvri_dataset.py \
  --xlsx "/srv/tvri/Annotator Sign Video + Transcript BISINDO.xlsx" \
  --category BISINDO --dry-run
```

Harapan output:

```
INFO Parsed …BISINDO.xlsx: 24 recordings, 121 segments, 7200 utterances (2399 need alignment)
```

### 6c. Impor sungguhan

```bash
docker compose exec -T api python scripts/import_tvri_dataset.py \
  --xlsx "/srv/tvri/Annotator Sign Video + Transcript BISINDO.xlsx" \
  --category BISINDO \
  --dataset-name "TVRI 2026" \
  --clips-dir /srv/tvri/clips_bisindo

docker compose exec -T api python scripts/import_tvri_dataset.py \
  --xlsx "/srv/tvri/Annotator Sign Video + Transcript SIBI.xlsx" \
  --category SIBI \
  --dataset-name "TVRI 2026" \
  --clips-dir /srv/tvri/clips_sibi
```

> **Nama dataset tidak boleh mengandung kata "inews"** — itulah yang memicu mode
> read-only untuk Pipeline/Klasifikasi dan penguncian glosa.

Kedua bahasa isyarat masuk ke **satu** dataset `TVRI 2026` (yang sudah ada di
server) dan dibedakan lewat kolom `pipeline_jobs.category`. Ini aman karena
tidak ada satu pun ID rekaman yang dipakai oleh BISINDO dan SIBI sekaligus —
sudah diperiksa: 24 rekaman masing-masing, irisan nol.

Tiap rekaman di-commit terpisah, jadi kalau prosesnya terputus, jalankan ulang
perintah yang sama: rekaman yang sudah masuk akan dilewati (dicek dari
`original_filename` dalam dataset yang sama).

### Opsi lain

| Flag | Kegunaan |
|---|---|
| `--skip-clips` | isi DB dulu, unggah video menyusul |
| `--annotator-email x@y` | sekalian buat baris `annotation_queue` (objektif 5 & 6) |
| `--lock-all` | tandai semua kalimat `OK`, termasuk yang "Kesalahan Waktu" |
| `--manifest FILE` | tulis daftar nama klip yang dibutuhkan |

### Yang ditulis importer

Per kalimat, klip diunggah ke **dua** key:

- `jobs/{job}/utterances/{segment}_utt_{i}.mp4` — sumber yang dipotong workspace
- `jobs/{job}/utterances_synced/{segment}_utt_{i}.mp4` — klip hasil akhir yang
  dibaca kurasi & ekspor

Alasannya: `_resolve_synced_key` (`app/api/v1/jobs.py`) menolak path yang bukan
di bawah `utterances_synced/`. Kalau klip TVRI hanya ada di `utterances/`,
seluruh kalimat berstatus OK — yang memang tidak pernah dipotong ulang — akan
kosong saat diekspor. Penyelarasan ulang menimpa key `utterances_synced/` yang
sama dengan hasil crop asli.

Selain itu:

- `pipeline_jobs.status = READY_FOR_ANNOTATION`, `category` = BISINDO/SIBI,
  `release_date` diambil dari id rekaman (`…-20191111Z…` → `20191111`)
- `pipeline_segments.cropped_video_path = NULL` — tidak ada video segmen; FE
  jatuh ke tape gabungan, dan urutan segmen kini dari `segment_index` (§3 poin 3)
- `voice_annotations` diimpor sebagai `CLEAN` dengan `flagged_words = []`.
  Transkripnya sudah diverifikasi manusia; menjalankannya lewat KBBI hanya akan
  menandai nama orang/tempat dan mengunci job-nya.
- 306 baris BISINDO + 16 baris SIBI tidak punya glosa. Nilai kosong akan
  ditolak `UtteranceCorrection` (`min_length=1`) sehingga **penyimpanan draft
  pertama oleh annotator gagal untuk seluruh segmen itu**. Karena itu diisi
  placeholder `(glosa belum diisi)`.

---

## 7. WAV per kalimat (objektif internal 3 & 4)

Dataset TVRI tidak menyertakan WAV sama sekali. `pipeline_transcripts.audio_path`
diisi `NULL` oleh importer, dan halaman Anotasi Suara menampilkan *"Audio WAV
belum tersedia"*. Skrip `scripts/generate_tvri_wav.py` yang mengisinya.

### Kenapa tidak sekadar memotong audio dari klipnya

Tiap baris membawa **dua** rentang waktu yang berbeda:

```
Rentang Waktu Audio : 21.98s -> 25.14s      <- yang DIUCAPKAN
Rentang Waktu JBI   : 22.98  -> 26.50       <- yang ADA DI KLIP
```

Bedanya karena CV2 menggeser tiap klip non-pertama maju satu detik
(`S_i = A_i + 1.0`) untuk menangkap jeda penerjemah. Di dataset ini
selisihnya **tepat 1,00 detik untuk 95% baris** (6.871 dari 7.200 BISINDO,
5.831 dari 6.141 SIBI).

Artinya: **memotong audio klip dari awal sampai akhir akan membuang satu detik
pertama ucapan** — biasanya satu-dua kata pertama — di hampir setiap kalimat.
Itu jelas tidak bisa dipakai sebagai ground truth suara.

### Cara yang dipakai: rekonstruksi dari rantai klip

Detik yang hilang itu tidak benar-benar hilang. CV2 juga menyusun klip
berurutan tanpa lubang (`E_i = A_{i+1} + 1.0 = S_{i+1}`), jadi audio milik
kalimat N justru duduk di **ekor klip N-1**. Menelusuri mundur rantai klip
merekonstruksi jendela ucapan yang persis:

| | jendela audio tercakup penuh | tidak penuh |
|---|---|---|
| BISINDO | **7.185 (99,8%)** | 15 |
| SIBI | **6.125 (99,7%)** | 16 |

31 kalimat sisanya adalah anomali entri di sheet (misal klip 1,2 detik dengan
rentang audio 28 detik). Skrip melaporkannya, bukan mendiamkannya.

Jadi **tidak perlu mengunduh apa pun selain klip yang sudah diunduh untuk
impor**. Tidak perlu rekaman siaran asli, tidak perlu API, tidak ada biaya
tambahan.

> Ini juga satu-satunya jalan yang tersedia: rentang waktu di workbook relatif
> terhadap **segmen**, sedangkan workbook tidak mencatat di detik ke berapa tiap
> segmen mulai di dalam siaran. Jadi rekaman siaran asli pun tidak cukup tanpa
> offset segmen.

### Cara kerja teknisnya

Per segmen, satu lintasan:

1. `ffmpeg -vn` tiap klip sekali → PCM 16 kHz mono (format yang sama dengan
   `VideoProcessor.extract_audio` untuk iNews)
2. buffer PCM disusun di **timeline segmen**, tiap klip ditempatkan pada offset
   nominalnya; jeda antar klip diisi silence supaya waktu lokal == waktu segmen
3. tiap kalimat dipotong dari buffer itu dengan `[audio_start, audio_end]` —
   ini murni pemotongan byte, tanpa ffmpeg lagi
4. diunggah ke `jobs/{job}/audio/{segment_id}_utt_{i}.wav`, lalu
   `pipeline_transcripts.audio_path` diisi

Biayanya: satu decode ffmpeg pendek per klip (±13.300 untuk seluruh dataset),
selebihnya operasi memori.

**Kenapa offset nominal, bukan disambung berurutan:** hasil decode AAC beberapa
puluh milidetik lebih panjang dari rentang nominalnya (padding encoder). Diukur
±19 ms per klip — kalau klip disambung ujung-ke-ujung, pada segmen TVRI berisi
341 klip errornya menumpuk jadi beberapa detik dan semua potongan berikutnya
meleset. Dengan menempatkan tiap klip di offset nominalnya, error terkurung di
dalam satu klip. Diuji pada klip sintetis yang nada audionya menyandi
timestamp-nya sendiri: hasilnya presisi sub-frame (error ≤13 ms, dan itu batas
resolusi alat ukurnya).

### PRASYARAT: klip harus punya track audio

Ini satu-satunya asumsi yang belum bisa saya verifikasi — klipnya belum ada di
sini. **Cek ini dulu sebelum apa pun:**

```bash
ffprobe -v error -select_streams a -show_entries stream=codec_name \
  -of csv=p=0 /srv/tvri/clips_bisindo/MEM001M-20191111Z103928_0_0.40_7.66.mp4
```

- Keluar `aac` (atau codec lain) → **aman**, lanjutkan.
- Keluar kosong → klipnya bisu. Pendekatan ini tidak bisa dipakai dan kita perlu
  rekaman siaran asli **beserta** offset tiap segmen. Beri tahu saya kalau ini
  yang terjadi.

Skrip juga memeriksa ini sendiri dan berhenti tanpa menulis apa pun kalau
klipnya bisu.

### Menjalankan

```bash
# 1. Analisis dulu — tidak menulis apa pun
docker compose exec -T api python scripts/generate_tvri_wav.py \
  --xlsx "/srv/tvri/Annotator Sign Video + Transcript BISINDO.xlsx" \
  --dataset-name "TVRI 2026" \
  --clips-dir /srv/tvri/clips_bisindo \
  --report-only

# 2. Sungguhan
docker compose exec -T api python scripts/generate_tvri_wav.py \
  --xlsx "/srv/tvri/Annotator Sign Video + Transcript BISINDO.xlsx" \
  --dataset-name "TVRI 2026" \
  --clips-dir /srv/tvri/clips_bisindo

# 3. Ulangi untuk SIBI
```

Harus dijalankan **setelah** importer, karena skrip ini mencari job berdasarkan
dataset + `original_filename`. Aman diulang: menjalankan lagi hanya menimpa WAV
dengan isi yang sama.

### Bug yang ikut diperbaiki

`app/api/v1/assets.py` mengizinkan ekstensi `.wav` tapi **tidak punya entri MIME
untuk wav**, jadi WAV disajikan sebagai `application/octet-stream` — elemen
`<audio src>` tidak mau memutarnya. Ini juga memengaruhi WAV iNews yang sudah
ada, bukan hanya TVRI. Sekarang `wav`/`mp3`/`m4a` dipetakan dengan benar.

---

## 8. Verifikasi setelah impor

### A. Angka di DB

```sql
SELECT d.name, j.category, count(DISTINCT j.id) AS jobs,
       count(DISTINCT s.id) AS segments, count(t.id) AS utterances
FROM datasets d
JOIN pipeline_jobs j        ON j.dataset_id = d.id
JOIN pipeline_segments s    ON s.job_id = j.id
JOIN pipeline_transcripts t ON t.segment_id = s.id
WHERE d.name = 'TVRI 2026'
GROUP BY d.name, j.category;
```

Harapan: `BISINDO` → 24 / 121 / 7200, `SIBI` → 24 / 100 / 6141.

### B. Sebaran status kalimat

```sql
SELECT d.name,
       count(*) FILTER (WHERE u->>'status' = 'OK')  AS terkunci,
       count(*) FILTER (WHERE u->>'status' IS NULL) AS perlu_penyelarasan
FROM datasets d
JOIN pipeline_jobs j     ON j.dataset_id = d.id
JOIN pipeline_segments s ON s.job_id = j.id
JOIN annotation_edits e  ON e.segment_id = s.id AND e.is_deleted = false
CROSS JOIN LATERAL jsonb_array_elements(e.utterance_corrections) AS u
WHERE d.name LIKE 'TVRI%'
GROUP BY d.name;
```

Harapan: BISINDO 4801 / 2399, SIBI 5270 / 871.

### C. Klip benar-benar ada di MinIO

```bash
docker compose exec -T api python -c "
import asyncio
from app.services.minio_service import get_minio_service
m = get_minio_service()
print(asyncio.run(m.object_exists('jobs/<JOB_ID>/utterances/<SEGMENT_ID>_utt_0.mp4')))"
```

### D. WAV terisi

```sql
SELECT d.name,
       count(*) FILTER (WHERE t.audio_path IS NOT NULL) AS ada_wav,
       count(*) FILTER (WHERE t.audio_path IS NULL)     AS belum
FROM datasets d
JOIN pipeline_jobs j        ON j.dataset_id = d.id
JOIN pipeline_segments s    ON s.job_id = j.id
JOIN pipeline_transcripts t ON t.segment_id = s.id
WHERE d.name LIKE 'TVRI%'
GROUP BY d.name;
```

Lalu dengarkan satu file lewat browser (harus terunduh sebagai `audio/wav`,
bukan `application/octet-stream`):

```bash
curl -sI "https://<api>/api/v1/assets/jobs/<JOB_ID>/audio/<SEGMENT_ID>_utt_0.wav" \
  | grep -i content-type
```

### E. Lewat UI

1. Pilih dataset **TVRI 2026** di pemilih dataset.
2. Buka **Pipeline** dan **Klasifikasi** → harus tampil keterangan read-only,
   bukan kanvas pipeline.
3. Assign satu job ke annotator lewat **Admin → Assign JBI** (job harus muncul
   di daftar karena statusnya `READY_FOR_ANNOTATION`).
4. Buka **Anotasi JBI** sebagai annotator itu → job muncul, seluruh segmennya
   termuat, kalimat urut sesuai `segment_index`.
5. Kalimat berstatus OK → filmstrip terkunci, glosa terkunci, tombol lookback
   tidak muncul.
6. Kalimat "Kesalahan Waktu" → filmstrip bisa digeser, glosa tetap terkunci,
   tombol **Simpan & Lanjut** aktif.
7. Geser handle lalu **Simpan & Lanjut** → log BE menampilkan `Crop utt …`, dan
   `jobs/{job}/utterances_synced/{segment}_utt_{i}.mp4` ditimpa.

---

## 9. Yang belum dikerjakan

| Hal | Status |
|---|---|
| Objektif 1 & 2 (gabung dataset) | importer + perbaikan siap; menunggu file klip dari Drive |
| Objektif 3 & 4 (lengkapi WAV) | skrip siap & logikanya teruji; **tergantung klip punya track audio** (§7) |
| Objektif 5 & 6 (annotator assignment) | tidak dikerjakan sesuai permintaan; tersedia via `--annotator-email` atau halaman Admin → Assign JBI |
| Objektif 7 & 8 (penyelarasan) | jalur kerjanya sudah terverifikasi, tinggal dijalankan annotator |
| Uji end-to-end di data nyata | **belum** — belum ada klip untuk diuji |
| Commit & push, redeploy | **belum** |

Perlu diingat: **tanpa baris `annotation_queue`, workspace Anotasi JBI tidak bisa
membuka segmen sama sekali** (`get_segment_for_annotation` menolak segmen yang
tidak ter-assign). Jadi objektif 5 & 6 adalah prasyarat objektif 7 & 8, walaupun
sekarang belum dikerjakan.

---

## 10. Deploy

Tidak ada perubahan skema. Kolom yang dipakai skrip semuanya sudah ada:
`pipeline_transcripts.audio_path` sejak migrasi `017`, `pipeline_jobs.dataset_id`
sejak `021`, dan `tvri_source` hanya key JSON tambahan di dalam
`annotation_edits.utterance_corrections` yang tipenya sudah JSONB.

```bash
# di server, folder repo BE
cd <folder-jbi-service>
git pull

# cek profile mana yang dipakai
docker compose ps

docker compose --profile cpu up -d --build     # kalau service-nya "api"
docker compose --profile gpu up -d --build     # kalau service-nya "api-gpu"
```

`--build` **wajib** — `requirements.txt` bertambah `openpyxl`. Tanpa rebuild,
kedua skrip akan gagal dengan `ModuleNotFoundError`.

FE ada di repo terpisah; push ke GitHub sudah cukup kalau auto-deploy Vercel
aktif. **Deploy BE dulu, FE menyusul** — FE baru mengirim `job_id` ke endpoint
antrian, yang akan diabaikan BE lama sehingga job TVRI besar gagal termuat.

Perubahan ini satu batch dengan dua dokumen lain:

- [`LOOKBACK_TRIM_IN.md`](./LOOKBACK_TRIM_IN.md) — tanpa SQL
- [`MIGRASI_GESTURA_KE_ANOTASI.md`](./MIGRASI_GESTURA_KE_ANOTASI.md) — **ada SQL
  manual**, jalankan juga kalau belum pernah dijalankan

## 11. Rollback

Kode: `git revert` + rebuild, tidak ada data yang perlu dipulihkan.

Data hasil impor menempel pada dataset-nya sendiri, jadi menghapus dataset akan
menghapus seluruh job/segmen/transkrip/edit-nya lewat cascade FK:

```sql
-- CEK DULU jumlahnya, ini menghapus seluruh isi dataset
SELECT count(*) FROM pipeline_jobs
WHERE dataset_id = (SELECT id FROM datasets WHERE name = 'TVRI 2026');

BEGIN;
DELETE FROM pipeline_jobs
WHERE dataset_id = (SELECT id FROM datasets WHERE name = 'TVRI 2026');
DELETE FROM datasets WHERE name = 'TVRI 2026';
COMMIT;
```

Objek MinIO tidak ikut terhapus:

```bash
docker compose exec -T api python -c "
import asyncio
from app.services.minio_service import get_minio_service
print(asyncio.run(get_minio_service().delete_objects_by_prefix('jobs/<JOB_ID>/')))"
```
