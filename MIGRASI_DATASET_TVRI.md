# Migrasi Dataset TVRI ke anotasi.ai

Dokumen ini menjelaskan bentuk data TVRI, bagaimana ia dipetakan ke skema
anotasi.ai, apa yang sudah diperbaiki supaya sistem sanggup menampungnya, dan
langkah persis untuk menginjeksikan datanya.

**Jawaban singkat soal deploy: tidak ada `ALTER TABLE` dan tidak ada migrasi
Alembic.** Yang dibutuhkan hanya `git pull` + rebuild Docker, lalu menjalankan
satu skrip importer di dalam container API.

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
  --dataset-name "TVRI BISINDO" \
  --clips-dir /srv/tvri/clips_bisindo

docker compose exec -T api python scripts/import_tvri_dataset.py \
  --xlsx "/srv/tvri/Annotator Sign Video + Transcript SIBI.xlsx" \
  --category SIBI \
  --dataset-name "TVRI SIBI" \
  --clips-dir /srv/tvri/clips_sibi
```

> **Nama dataset tidak boleh mengandung kata "inews"** — itulah yang memicu mode
> read-only untuk Pipeline/Klasifikasi dan penguncian glosa.

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

## 7. Verifikasi setelah impor

### A. Angka di DB

```sql
SELECT d.name, count(DISTINCT j.id) AS jobs,
       count(DISTINCT s.id) AS segments, count(t.id) AS utterances
FROM datasets d
JOIN pipeline_jobs j        ON j.dataset_id = d.id
JOIN pipeline_segments s    ON s.job_id = j.id
JOIN pipeline_transcripts t ON t.segment_id = s.id
WHERE d.name LIKE 'TVRI%'
GROUP BY d.name;
```

Harapan: `TVRI BISINDO` → 24 / 121 / 7200, `TVRI SIBI` → 24 / 100 / 6141.

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

### D. Lewat UI

1. Pilih dataset **TVRI BISINDO** di pemilih dataset.
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

## 8. Yang belum dikerjakan

| Hal | Status |
|---|---|
| Objektif 1 & 2 (gabung dataset) | importer + perbaikan siap; menunggu file klip dari Drive |
| Objektif 3 & 4 (lengkapi WAV) | **belum** — `pipeline_transcripts.audio_path` diisi `NULL` |
| Objektif 5 & 6 (annotator assignment) | tidak dikerjakan sesuai permintaan; tersedia via `--annotator-email` atau halaman Admin → Assign JBI |
| Objektif 7 & 8 (penyelarasan) | jalur kerjanya sudah terverifikasi, tinggal dijalankan annotator |
| Uji end-to-end di data nyata | **belum** — belum ada klip untuk diuji |
| Commit & push, redeploy | **belum** |

Perlu diingat: **tanpa baris `annotation_queue`, workspace Anotasi JBI tidak bisa
membuka segmen sama sekali** (`get_segment_for_annotation` menolak segmen yang
tidak ter-assign). Jadi objektif 5 & 6 adalah prasyarat objektif 7 & 8, walaupun
sekarang belum dikerjakan.

---

## 9. Deploy

Tidak ada perubahan skema, jadi urutannya:

```bash
# di server, folder repo BE
cd <folder-jbi-service>
git pull
docker compose --profile cpu up -d --build     # atau --profile gpu
```

FE ada di repo terpisah; push ke GitHub sudah cukup kalau auto-deploy Vercel
aktif. **Deploy BE dulu, FE menyusul** — FE baru mengirim `job_id` ke endpoint
antrian, yang akan diabaikan BE lama sehingga job TVRI besar gagal termuat.

Perubahan ini satu batch dengan dua dokumen lain yang juga belum di-push:

- [`LOOKBACK_TRIM_IN.md`](./LOOKBACK_TRIM_IN.md) — tanpa SQL
- [`MIGRASI_GESTURA_KE_ANOTASI.md`](./MIGRASI_GESTURA_KE_ANOTASI.md) — **ada SQL
  manual**, jalankan juga kalau di-push bersamaan

## 10. Rollback

Kode: `git revert` + rebuild, tidak ada data yang perlu dipulihkan.

Data hasil impor menempel pada dataset-nya sendiri, jadi menghapus dataset akan
menghapus seluruh job/segmen/transkrip/edit-nya lewat cascade FK:

```sql
-- CEK DULU jumlahnya, ini menghapus seluruh isi dataset
SELECT count(*) FROM pipeline_jobs
WHERE dataset_id = (SELECT id FROM datasets WHERE name = 'TVRI BISINDO');

BEGIN;
DELETE FROM pipeline_jobs
WHERE dataset_id = (SELECT id FROM datasets WHERE name = 'TVRI BISINDO');
DELETE FROM datasets WHERE name = 'TVRI BISINDO';
COMMIT;
```

Objek MinIO tidak ikut terhapus:

```bash
docker compose exec -T api python -c "
import asyncio
from app.services.minio_service import get_minio_service
print(asyncio.run(get_minio_service().delete_objects_by_prefix('jobs/<JOB_ID>/')))"
```
