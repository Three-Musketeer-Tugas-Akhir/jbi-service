# Migrasi Data: `gestura.ai` → `anotasi.ai`

Dokumen ini berisi query SQL yang perlu dijalankan **manual di server via SSH** setelah pull + rebuild Docker.

Perubahan kode (sudah dilakukan, tinggal pull):
- `app/services/user_service.py:591` — auto-generate email user baru sekarang pakai `@anotasi.ai`
- FE: semua teks brand `Gestura.ai` → `Anotasi.ai`, auto-generate email di form kelola user → `@anotasi.ai`

Data lama di DB **tidak** ikut berubah oleh rebuild. Harus di-`UPDATE` manual.

---

## PERINGATAN

Query di bawah mengubah kolom `auth_users.email`, yang merupakan **kredensial login**. Setelah diubah:

- User yang emailnya berakhiran `@gestura.ai` **tidak bisa login lagi dengan email lama**. Mereka harus login dengan email `@anotasi.ai` yang baru.
- Password **tidak** berubah.
- Kolom `auth_users.email` punya **unique constraint**. Kalau sudah ada user lain dengan email `@anotasi.ai` yang identik, UPDATE akan gagal dengan error unique violation. Jalankan langkah 2 (pre-check) dulu.

Backup dulu (langkah 1) sebelum menjalankan UPDATE apa pun.

---

## Langkah 0 — Masuk ke psql

```bash
# di dalam folder repo BE di server
docker compose exec db psql -U postgres -d anotasi_db
```

Kalau mau jalankan satu query tanpa masuk shell interaktif:

```bash
docker compose exec -T db psql -U postgres -d anotasi_db -c "SELECT 1;"
```

---

## Langkah 1 — Backup (WAJIB, jalankan sebelum UPDATE)

```bash
docker compose exec -T db pg_dump -U postgres -d anotasi_db \
  > ~/backup_anotasi_db_$(date +%Y%m%d_%H%M%S).sql
```

Verifikasi file backup tidak kosong:

```bash
ls -lh ~/backup_anotasi_db_*.sql
```

---

## Langkah 2 — Pre-check (read-only, aman)

### 2a. Lihat user mana saja yang kena

```sql
SELECT id, email, is_active, created_at
FROM auth_users
WHERE email LIKE '%@gestura.ai'
ORDER BY created_at;
```

### 2b. Cek bentrok unique constraint

Query ini harus mengembalikan **0 baris**. Kalau ada baris, artinya email tujuan sudah dipakai user lain — selesaikan manual dulu (hapus/rename salah satu) sebelum lanjut.

```sql
SELECT u.email AS email_lama,
       replace(u.email, '@gestura.ai', '@anotasi.ai') AS email_baru
FROM auth_users u
WHERE u.email LIKE '%@gestura.ai'
  AND EXISTS (
      SELECT 1 FROM auth_users x
      WHERE x.email = replace(u.email, '@gestura.ai', '@anotasi.ai')
  );
```

### 2c. Scan seluruh tabel teks lain yang mungkin menyimpan `gestura.ai`

```sql
-- audit log (email disimpan di dalam JSONB details)
SELECT count(*) AS audit_logs_kena
FROM audit_logs
WHERE details::text LIKE '%gestura.ai%';

-- notifikasi
SELECT count(*) AS notifications_kena
FROM notifications
WHERE title LIKE '%gestura.ai%' OR message LIKE '%gestura.ai%';

-- chat
SELECT count(*) AS chat_messages_kena
FROM chat_messages
WHERE content LIKE '%gestura.ai%';

-- komentar anotasi
SELECT count(*) AS annotation_comments_kena
FROM annotation_comments
WHERE comment LIKE '%gestura.ai%';
```

Catat angkanya. Tabel dengan hasil `0` boleh dilewati di Langkah 3.

---

## Langkah 3 — UPDATE data

Semua dibungkus transaksi supaya bisa di-`ROLLBACK` kalau hasilnya tidak sesuai.

```sql
BEGIN;

-- 3a. Email user (kredensial login)
UPDATE auth_users
SET email = replace(email, '@gestura.ai', '@anotasi.ai'),
    updated_at = now()
WHERE email LIKE '%@gestura.ai';

-- 3b. Audit log (JSONB details)
UPDATE audit_logs
SET details = replace(details::text, 'gestura.ai', 'anotasi.ai')::jsonb
WHERE details::text LIKE '%gestura.ai%';

-- 3c. Notifikasi
UPDATE notifications
SET title   = replace(title, 'gestura.ai', 'anotasi.ai'),
    message = replace(message, 'gestura.ai', 'anotasi.ai')
WHERE title LIKE '%gestura.ai%' OR message LIKE '%gestura.ai%';

-- 3d. Chat
UPDATE chat_messages
SET content = replace(content, 'gestura.ai', 'anotasi.ai')
WHERE content LIKE '%gestura.ai%';

-- 3e. Komentar anotasi
UPDATE annotation_comments
SET comment = replace(comment, 'gestura.ai', 'anotasi.ai')
WHERE comment LIKE '%gestura.ai%';
```

**Belum di-commit.** Cek dulu hasilnya di transaksi yang sama:

```sql
SELECT count(*) AS sisa_gestura FROM auth_users WHERE email LIKE '%gestura.ai%';
SELECT id, email FROM auth_users ORDER BY created_at;
```

Kalau hasil sudah benar:

```sql
COMMIT;
```

Kalau ada yang salah:

```sql
ROLLBACK;
```

---

## Langkah 4 — Verifikasi akhir

Semua query di bawah harus mengembalikan `0`.

```sql
SELECT count(*) FROM auth_users            WHERE email LIKE '%gestura.ai%';
SELECT count(*) FROM audit_logs            WHERE details::text LIKE '%gestura.ai%';
SELECT count(*) FROM notifications         WHERE title LIKE '%gestura.ai%' OR message LIKE '%gestura.ai%';
SELECT count(*) FROM chat_messages         WHERE content LIKE '%gestura.ai%';
SELECT count(*) FROM annotation_comments   WHERE comment LIKE '%gestura.ai%';
```

Lalu tes login dengan salah satu akun yang emailnya berubah, pakai password lama.

---

## Langkah 5 — Sanity check teks brand (opsional)

Kalau ada teks brand lain (bukan email) yang tersimpan di DB, cari dengan:

```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND data_type IN ('text', 'character varying', 'jsonb');
```

Lalu cek manual kolom yang kelihatan menyimpan teks bebas. Berdasarkan pemeriksaan kode, hanya tabel di Langkah 3 yang realistis menyimpan string `gestura.ai`.

---

## Urutan deploy yang disarankan

1. Pull perubahan kode di server: `git pull`
2. Backup DB (Langkah 1)
3. Pre-check (Langkah 2)
4. Rebuild + restart: `docker compose up -d --build`
5. Jalankan UPDATE (Langkah 3), commit
6. Verifikasi (Langkah 4) + tes login

Urutan ini aman karena kode baru tetap bisa membaca email lama maupun baru — perubahan kode hanya memengaruhi email yang **baru dibuat**, bukan yang sudah ada.
