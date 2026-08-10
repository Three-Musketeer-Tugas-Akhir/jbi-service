# Lookback Trim-In — Sisa Potongan Kalimat N-1 di Workspace Anotasi JBI

Dokumen ini menjelaskan perubahan yang sudah dikerjakan, hasil akhirnya seperti apa,
dan apa saja yang perlu dijalankan di server SSH.

**Jawaban singkat untuk pertanyaan deploy: cukup `git pull` + rebuild Docker. Tidak ada
`ALTER TABLE`, tidak ada migrasi Alembic, tidak ada kolom DB baru.**

---

## 1. Masalah yang diperbaiki

Workspace anotasi untuk kalimat N berisi tape hasil merge fisik `[klip N | klip N+1]`.
Handle **start** praktis tidak bisa digeser ke kiri, karena batas kirinya dikunci di
`mergedBase = global_start − head_offset`, dan `head_offset = 0` untuk kalimat yang
belum pernah di-trim.

Akibatnya, kalau **kalimat N-1 dipendekkan** (annotator menarik handle *end* N-1 ke
kiri saat sinkronisasi), potongan yang dilepas jadi **yatim**: N-1 sudah tidak
memilikinya, dan N tidak bisa menjangkaunya. Padahal potongan itu duduk persis
sebelum klip N dan bisa memuat awal gerakan isyarat untuk kalimat N.

Ini sesuai permintaan Bu Efi: kalimat 3 sekarang berisi `video 3 + video 4`, seharusnya
`potongan video 2 (kalau ada terjadi trim in) + video 3 + video 4`.

### Kenapa ini berlaku untuk semua dataset, bukan cuma TVRI

Asumsi awal "CV1 memecah segment saat silence sehingga kasus ini jarang terjadi"
**tidak terbukti**. CV1 tidak menyentuh audio sama sekali — segment dipecah murni dari
kehadiran bounding box JBI, di-sample 1 frame per detik
(`app/pipeline/stages/stage1_detection.py:49-50, 163-192`). ASR juga jalan tanpa
`vad_filter` (`app/pipeline/models/transcriber.py:179-186`), jadi Whisper normalnya
mengeluarkan utterance yang kontigu.

Yang menentukan justru CV2 (`app/workers/cropping_worker.py:422-454`):

```python
is_first = utterance_index == 0
if not is_first:
    current_start += 1.0          # S_i = A_i + 1.0
...
gap = next_start - current_end
if gap > 2.0:  current_end = current_end + 2.0
else:          current_end = next_start + 1.0     # E_i = A_{i+1} + 1.0
```

Untuk kasus umum `gap ≤ 2s`:

- `S_i = A_i + 1.0` — klip N mulai **satu detik setelah** audio N mulai. Kalau jeda
  isyarat penerjemah lebih pendek dari 1 detik, awal gerakan kalimat N sudah lewat
  sebelum klip N dimulai.
- `E_i = A_{i+1} + 1.0 = S_{i+1}` — **klip N-1 dan klip N bersambung persis tanpa
  lubang**, sehingga menyambungkan ekor N-1 ke kepala N tidak menimbulkan jump cut.

Keduanya berlaku di semua dataset, termasuk iNews. Jadi mekanisme ini **tidak digating
per-dataset**.

---

## 2. Model yang dipakai: "Ekor Yatim"

Yang disambung ke workspace N **bukan** potongan berdurasi tetap dari N-1, melainkan
**persis bagian yang dilepas N-1** — jadi tidak ada frame yang dipakai dua kali.

```
klip N-1: [ prev.start ═══════════════ prev.end ]
                            e ──────────────┤        e = end efektif N-1 (dari draft)
                            └─ EKOR YATIM ──┘
klip N:                                     [ curr.start ═══════ curr.end ]
                                            ↑ curr.start == prev.end (kasus gap ≤ 2s)
```

- `orphan = max(0, prev.end − e)` — nol kalau N-1 belum pernah dipendekkan
- Tape lookback jadi `[ekor yatim | N | N+1]`

Konsekuensinya:

| Hal | Perilaku |
|---|---|
| Cascade kiri | **Tidak ada.** `end` dan status kalimat N-1 tidak pernah disentuh. |
| Batas kiri handle | Berhenti tepat di `e`. Melewati itu berarti mengambil frame yang masih milik N-1. |
| Pemicu | Tombol opt-in, **disabled kalau `orphan = 0`**. Tape default tetap `[N \| N+1]`. |
| Panjang | Dinamis, sepanjang `orphan`. |

---

## 3. Yang berubah — Backend (repo `jbi-service`)

### `app/services/utterance_merge_service.py`

- **Helper baru `_prev_orphan_geometry(db, segment, utterance_index)`** — mencari
  kalimat N-1 (lintas segment, mirror dari query `next` yang sudah ada), membaca `end`
  efektifnya dari `AnnotationEdit` milik segment N-1, dan mengembalikan
  `(prev_transcript, prev_effective_end, orphan_seconds)`.
- **`get_or_create_merged_video(..., include_prev: bool = False)`** — ketika
  `include_prev` dan ada ekor yatim, ekor itu dipotong dari klip N-1 lalu disambung di
  depan tape jadi `[ekor | N | N+1]`.
- Varian lookback disimpan di key MinIO terpisah
  `jobs/{job}/utterances_merged/{segment}_utt_{i}_lb.mp4` dan **tidak ditulis ke kolom
  cache DB**, supaya tampilan normal `[N | N+1]` tidak ikut berubah.
- Response bertambah dua field: `prev_offset` (ekor yang benar-benar disambung) dan
  `prev_available` (ekor yang tersedia — dikembalikan di **setiap** panggilan supaya FE
  tahu tombolnya perlu aktif tanpa request kedua).

Dua bug lama ikut ditutup sekalian:

- Nama file temp sekarang membawa nonce per-request. Sebelumnya nama deterministik,
  padahal `get_video_duration` (`app/pipeline/utils/video.py:343-353`) punya cache
  by-path yang tidak pernah di-invalidate — jadi setelah re-trim, durasi merge lama
  bisa terpakai untuk file baru.
- Kalau lookback gagal dipotong **dan** tidak ada kalimat N+1, sekarang responsnya
  kembali ke jalur single-video, bukan menyimpan satu klip tunggal sebagai "merged"
  ke cache DB.

### `app/api/v1/annotations.py`

Endpoint `GET /annotations/segments/{segment_id}/utterances/{utterance_index}/merged-video`
menerima query param baru `include_prev` (default `false`). Sisanya tidak berubah.

### `app/services/utterance_cropping_service.py`

Ini bagian yang membuat hasilnya benar-benar tersimpan, bukan cuma tampilan.

Sebelumnya crop fisik meng-clamp keras:

```python
if start_time < orig_start:
    logger.warning(f"Trim-in before orig_start ... Clamping to orig_start.")
    start_time = orig_start
```

Artinya kalau FE dibuat bisa menggeser handle ke kiri, draft tersimpan dengan `start`
lebih awal tapi crop fisiknya diam-diam membuang bagian itu — output dataset tidak akan
sama dengan yang dilihat annotator. Sekarang:

- `clamped_left = min(left_overlap, prev_orphan)` — tidak pernah mengambil frame yang
  masih dimiliki N-1
- **Part Z** dipotong dari ujung klip N-1 lalu di-concat di depan hasil crop normal.
  Ini mirror dari logika Part A / Part B yang sudah ada untuk arah kanan, dan keduanya
  bisa berlaku pada crop yang sama.
- `pre_trim_snapshot` bertambah `consumed_from_prev` supaya revert bisa membedakan trim
  biasa dari trim yang menjangkau mundur.
- **Tidak ada cascade kiri** — `_cascade_set_next_start` tidak disentuh.

---

## 4. Yang berubah — Frontend (repo `anotasi.ai-FE`)

### `src/features/annotation/annotation-api.ts`

`getMergedVideo(segmentId, utteranceIndex, includePrev = false)` — meneruskan
`include_prev` sebagai query param, dan tipe response bertambah `prev_offset` /
`prev_available`.

### `src/features/annotation/components/annotation-page.tsx`

State baru `lookbackOn` / `prevOffset` / `prevAvailable`, plus handler
`handleToggleLookback`. Inti perubahannya satu baris:

```ts
setMergedBase((utt.global_start ?? utt.start ?? 0) - (merged.head_offset ?? 0) - prepended);
```

Karena `startFloor = mergedBase`, `windowStart = mergedBaseGlobal`, dan
`videoOffset = -mergedBase`, seluruh matematika window, filmstrip, playhead, dan batas
drag **ikut bergeser otomatis**. Tidak ada rumus lain yang perlu diubah.

`lookbackOn` di-reset setiap ganti kalimat, jadi setiap kalimat mulai dari tape polos.

### `src/features/annotation/components/timeline-editor.tsx`

- Prop baru `lookbackSeconds` / `lookbackAvailable` / `lookbackOn` / `onToggleLookback`
- Tombol di header filmstrip
- Zona biru menandai ekor yatim; pita amber "↤ bisa ditarik kembali" (trim-in milik
  sendiri) digeser ke kanan supaya tidak tumpang tindih
- Penanda sambungan `✂️` pindah ke `windowStart + lookbackSeconds + videoNDuration`

---

## 5. Jadinya seperti apa sekarang

**Alur normal (tidak ada ekor yatim)** — tidak ada perubahan sama sekali. Tape tetap
`[N | N+1]`, cache merge di DB tetap dipakai, tombol lookback tampil tapi *disabled*
dengan tooltip "Kalimat sebelumnya tidak menyisakan potongan yang bisa disambung".

**Alur dengan ekor yatim:**

1. Annotator memendekkan kalimat 2 (tarik handle *end* ke kiri ~2 detik), klik
   **Simpan & Lanjut**.
2. Masuk ke kalimat 3. Tombol di header filmstrip aktif:
   `‹ Konteks sebelumnya (2.0s)`.
3. Klik tombol. Overlay "Video sedang diproses" muncul sebentar, lalu filmstrip
   memanjang ~2 detik ke kiri dengan zona biru berlabel `sisa kalimat sebelumnya`.
   Label tombol berubah jadi `‹ Konteks aktif (2.0s)`.
4. Handle *start* sekarang bisa ditarik mundur ke dalam zona biru, dan **berhenti tepat
   di batas kiri zona** — tidak bisa lebih, karena di luar itu masih milik kalimat 2.
5. Klik **Simpan & Lanjut**. Crop fisik menyambung Part Z (potongan dari klip 2) di
   depan hasil crop kalimat 3.
6. Kalimat 2 **tidak berubah**: `end`-nya tetap, statusnya tetap `OK`, `cropped_video_path`-nya
   tidak dihapus.

Tombol lookback juga otomatis tersembunyi kalau filmstrip sedang terkunci — yaitu pada
kalimat berstatus `OK` di dataset non-iNews, sesuai mekanisme read-only yang dipasang
sebelumnya.

---

## 6. Yang harus dijalankan di server SSH

### Tidak perlu SQL

| Pertanyaan | Jawaban |
|---|---|
| Perlu `ALTER TABLE`? | **Tidak.** |
| Perlu `alembic upgrade`? | **Tidak.** |
| Ada kolom DB baru? | **Tidak.** |
| Ada bucket / folder MinIO baru? | **Tidak** — file `_lb` masuk ke prefix `utterances_merged/` yang sudah ada. |

`consumed_from_prev` hanya key JSON tambahan di dalam
`annotation_edits.utterance_corrections`, yang tipenya sudah JSONB — tidak butuh migrasi.

### Langkah deploy

```bash
# 1. Masuk ke folder repo BE di server
cd <folder-jbi-service>

# 2. Cek profile mana yang dipakai (cpu atau gpu)
docker compose ps

# 3. Pull perubahan
git pull

# 4. Rebuild + restart.
#    Pilih SATU sesuai hasil langkah 2:
docker compose --profile cpu up -d --build      # kalau service-nya bernama "api"
docker compose --profile gpu up -d --build      # kalau service-nya bernama "api-gpu"
```

Perubahan ada di `app/services/` dan `app/api/v1/`, yang dipakai oleh container API
(crop fisik jalan sebagai `BackgroundTasks` di proses API, bukan di Kafka worker).
Semua service dibangun dari image yang sama, jadi `--build` sudah mencakup semuanya.

**Cache merge lama tidak perlu dibersihkan.** Bentuk tape kanonik `[N | N+1]` tidak
berubah, jadi `merged_video_path` yang sudah tersimpan tetap valid.

### Kalau sekalian mendeploy perubahan `gestura.ai` → `anotasi.ai`

Perubahan itu **memang butuh SQL manual**, dan langkahnya ada di dokumen terpisah:
[`MIGRASI_GESTURA_KE_ANOTASI.md`](./MIGRASI_GESTURA_KE_ANOTASI.md). Kedua perubahan ini
ada dalam satu batch yang belum di-commit, jadi kalau di-push bersamaan, jalankan juga
query di dokumen itu (backup dulu, ada peringatan soal email login di sana).

### Frontend

FE ada di repo terpisah (`anotasi.ai-FE`). Perubahannya perlu di-push ke GitHub. Kalau
auto-deploy sudah tersambung di dashboard Vercel/Netlify, push saja sudah cukup. Kalau
FE di-host sendiri via Docker di server yang sama, jalankan build ulang FE seperti biasa.

> Catatan: FE dan BE **tidak wajib** dideploy bersamaan. BE yang baru tetap kompatibel
> dengan FE lama (`include_prev` default `false` = perilaku lama persis). Tapi FE baru
> dengan BE lama akan menampilkan tombol yang selalu *disabled*, karena `prev_available`
> tidak ada di response. Jadi urutan amannya: **BE dulu, FE menyusul.**

---

## 7. Verifikasi setelah deploy

### A. Cek endpoint langsung

```bash
# Siapkan dulu: pendekkan kalimat 2 lewat UI, simpan.
# Lalu ganti SEG / TOKEN / API sesuai environment.

curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/annotations/segments/$SEG/utterances/2/merged-video" | jq '.prev_available, .prev_offset'
# harapan: prev_available ≈ 2.0, prev_offset = 0

curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/annotations/segments/$SEG/utterances/2/merged-video?include_prev=true" | jq '.prev_offset, .total_duration'
# harapan: prev_offset ≈ 2.0, total_duration naik ≈ 2.0 dibanding panggilan pertama
```

### B. Cek lewat UI

1. Kalimat 3 — tombol `‹ Konteks sebelumnya (2.0s)` **aktif**
2. Klik — filmstrip memanjang ke kiri, zona biru muncul
3. Tarik handle start ke kiri — berhenti tepat di batas zona
4. **Simpan & Lanjut** — di log BE harus muncul baris `Backward trim-in for utt ...
   reclaiming ...`, **bukan** `Clamping to orig_start`
5. Buka lagi kalimat 2 — `end` dan status `OK` harus tidak berubah

### C. Cek durasi hasil crop

```bash
docker compose exec -T api python -c "
import asyncio
from app.services.minio_service import get_minio_service
print(asyncio.run(get_minio_service().generate_presigned_url(
    'jobs/<JOB_ID>/utterances_synced/<SEGMENT_ID>_utt_3.mp4')))"

# lalu:
ffprobe -v error -show_entries format=duration -of csv=p=0 "<url-hasil-di-atas>"
```

Durasinya harus bertambah sesuai geseran handle.

### D. Kasus negatif

| Kondisi | Harapan |
|---|---|
| Kalimat yang N-1-nya belum pernah dipendekkan | tombol *disabled*, `prev_available = 0` |
| Kalimat pertama dari job (tidak punya N-1) | tombol *disabled*, tidak ada error di console |
| Kalimat `OK` di dataset non-iNews | tombol tidak muncul (filmstrip memang terkunci) |

### E. Regresi

Tanpa menekan tombol lookback, alur trim-out N ke N+1 harus persis seperti sebelumnya:
`prev_offset = 0`, tape tidak bergeser, dan `merged_video_path` di DB tetap terisi
varian dua-klip.

---

## 8. Rollback

Karena tidak ada perubahan skema maupun data, rollback cukup:

```bash
git log --oneline -5          # cari commit sebelum perubahan ini
git revert <commit>           # atau: git checkout <commit-lama>
docker compose --profile <cpu|gpu> up -d --build
```

Tidak ada data yang perlu dipulihkan. File `_lb` yang tertinggal di MinIO tidak dibaca
oleh kode lama dan aman dibiarkan; kalau mau dibersihkan:

```bash
docker compose exec -T minio mc rm --recursive --force \
  local/<bucket>/jobs --include "*_lb.mp4"
```

---

## 9. Status pekerjaan

| Sudah dikerjakan | Belum |
|---|---|
| Implementasi BE (3 file) + FE (3 file) | Uji end-to-end di data nyata |
| `python -m py_compile` semua file BE — lolos | Commit & push ke GitHub |
| `npx tsc --noEmit` FE — lolos | Deploy |
| `npx next build` FE — lolos | |

Kedua repo saat ini masih di branch `main` dengan perubahan **belum di-commit**.
