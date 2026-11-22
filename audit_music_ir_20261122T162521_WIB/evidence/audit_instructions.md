# Prompt audit fakta pipeline dan evaluasi Music IR

Anda adalah engineer yang mengaudit aplikasi Music IR di repository ini. Tugas Anda adalah mengumpulkan **data dan informasi faktual yang cukup untuk menyusun ulang laporan UAS Temu Kembali Informasi**. Penulisan laporan akademik akan dilakukan oleh pihak lain setelah menerima paket bukti Anda.

Kerjakan pembacaan kode, pemeriksaan konfigurasi aktif, dan pengujian yang dapat dijalankan. Hasil akhir harus menjelaskan dengan sederhana: **aplikasi mengerjakan apa, pipeline aktualnya bagaimana, metode apa yang benar-benar dipakai, apa hasil evaluasinya, dan apa batas kesimpulannya**.

## 1. Aturan kerja

1. Jadikan kode aktif, konfigurasi yang dimuat, dan keluaran eksekusi sebagai dasar fakta. Laporan lama serta README hanya menjadi bahan pembanding; isinya mungkin tidak sesuai implementasi terakhir.
2. Jangan mengubah metode, bobot, ambang, routing, atau query agar hasil terlihat lebih baik selama audit. Jangan menambahkan model maupun fitur baru. Pertahankan pekerjaan pengguna.
3. Boleh membuat skrip audit, fixture kecil, dan ekspor hasil yang terpisah. Jika menemukan bug, catat lokasi, dampak, dan bukti reproduksinya. Jangan mencampurkan hasil sebelum dan sesudah perbaikan. Perbaikan aplikasi dikerjakan sebagai pekerjaan lanjutan yang terpisah.
4. Jangan mengarang angka, hasil run, versi paket, spesifikasi komputer, sumber lirik, label relevansi, ataupun hasil terbaik. Nilai yang belum diketahui diberi `null` pada JSON dan dijelaskan alasannya.
5. Bedakan empat status: **terverifikasi lewat eksekusi saat audit**, **ditemukan dalam kode tetapi belum dijalankan**, **hanya tercatat pada artefak historis**, dan **belum tersedia/tidak dapat diverifikasi**.
6. Pengujian yang lulus tidak sama dengan akurasi pencarian. Skor ranking tidak sama dengan probabilitas atau persentase relevansi.
7. Jangan menyusun ulang Bab 1–5, menulis daftar pustaka baru, atau menambahkan narasi promosi. Berikan bahan faktual dan bukti yang mudah diperiksa.
8. Jika suatu layanan atau data tidak tersedia, lanjutkan audit bagian lain. Catat hambatan secara konkret, tanpa menyatakan bagian tersebut berhasil diuji.

## 2. Identifikasi snapshot yang diaudit

Sebelum menjalankan pengujian, catat:

- Root proyek, tanggal/jam dan zona waktu audit, commit Git jika tersedia, serta status perubahan yang belum di-commit.
- Hash berkas konfigurasi, corpus aktif, dan berkas kode utama yang menentukan pipeline.
- Command aktual untuk menjalankan backend, frontend, dan evaluasi.
- Nama aplikasi, endpoint pencarian yang dipanggil frontend, mode default, dan nilai `top_k` yang benar-benar dikirim.
- Konfigurasi yang efektif saat runtime, bukan hanya nilai default pada contoh konfigurasi.

Ambil versi Python, Node.js, paket backend, frontend, dan library model dari lingkungan aktual. Bedakan versi terpasang, versi lockfile, dan rentang dependensi yang dideklarasikan. Jangan menebak versi dari dokumentasi lama.

Catat OS tempat engine berjalan, CPU, RAM, GPU/VRAM bila ada, device inferensi, dan dtype. Jika aplikasi diakses dari Windows tetapi engine berjalan di WSL/container/mesin lain, jelaskan lokasi komputasinya. Jangan memasukkan token, credential, atau nilai rahasia `.env` ke paket audit.

## 3. Jelaskan proyek dalam bahasa sederhana

Buat ringkasan maksimal satu halaman yang menjawab:

1. Siapa pengguna aplikasi dan kebutuhan pencarian apa yang dilayani?
2. Apa input pengguna dan apa bentuk keluarannya?
3. Apakah pencarian berdasarkan judul, artis, lirik, tema, genre, fitur audio, atau kombinasi?
4. Apa yang dimaksud fitur audio: angka dari dataset atau pemrosesan rekaman suara?
5. Apa peran embedding, BM25, aturan, dan pemeringkatan dalam sistem?
6. Apakah ada LLM generatif, fine-tuning, cross-encoder, atau rekomendasi personal? Sebutkan hanya jika benar-benar ditemukan.

Bedakan agent coding yang membangun program dari algoritme yang berjalan di dalam aplikasi. Jangan menyebut aplikasi sebagai sistem agentic AI hanya karena dibangun menggunakan agent coding.

## 4. Rekonstruksi pipeline aktual dari jalur kode

Telusuri satu request dari UI sampai hasil tampil. Jangan memaksakan diagram lama jika implementasi berbeda. Berikan dua tingkat penjelasan:

- **Alur ringkas:** langkah utama yang mudah dimengerti pembaca laporan.
- **Alur teknis:** urutan fungsi, kondisi percabangan, input/output, dan konfigurasi yang mengontrol setiap langkah.

Gunakan tabel berikut:

| Tahap | Fungsi/tugas | Input | Proses/metode aktual | Output | Aktif pada kondisi apa | Lokasi kode dan bukti run |
|---|---|---|---|---|---|---|

Pisahkan persiapan offline dari pencarian online. Tentukan posisi sebenarnya dari:

- Audit dan penggabungan data; indexing; embedding dokumen; persiapan distribusi fitur.
- Normalisasi query, perlindungan kutipan, parsing metadata/intent, dan transformasi query untuk encoder.
- Pencarian katalog, BM25, embedding teks, pencocokan lirik, dan pencarian fitur audio jika tersedia.
- Filter metadata/audio: sebelum retrieval, setelah penggabungan, atau di beberapa tempat.
- Union, deduplikasi, fusion, batas kandidat, reservasi kandidat, serta pemecahan skor seri.
- Reranking dokumen/bagian lirik dan pemisahan hasil utama dari hasil serupa.
- Cache, fallback, dan penyajian alasan kecocokan.

Untuk setiap jalur, jelaskan apakah independen, kondisional, berurutan, atau benar-benar dieksekusi konkuren. Jangan menyebut semua jalur berjalan sejajar bila kode hanya memilih salah satunya.

Buat diagram Mermaid yang mencerminkan pipeline aktual, dengan label pendek. Sertakan gambar hasil render bila renderer tersedia. Diagram harus konsisten dengan tabel tahapan dan contoh trace.

## 5. Bedakan AUTO dan E1–E5 berdasarkan implementasi

Cari apakah AUTO dan E1–E5 benar-benar tersedia. Untuk setiap mode, laporkan:

| Mode | Entry point dan konfigurasi | Retrieval aktif | Posisi filter | Fusion | Reranking | Kebijakan tambahan | Status eksekusi |
|---|---|---|---|---|---|---|---|

Jawab secara eksplisit:

- Mode apa yang dipakai pengguna pada pencarian biasa?
- Apakah AUTO sama dengan E5 atau memiliki aturan tambahan?
- Apakah E3 dan E4 benar-benar menerima himpunan ID kandidat yang sama?
- Apakah E5 sama dengan E4 pada query tanpa intent audio?
- Apakah jalur audio mengambil kandidat dari seluruh corpus atau hanya menyaring kandidat teks?
- Backend BM25 aktual memakai implementasi lokal, Elasticsearch, atau adapter lain? Buktikan dari runtime. Keberadaan adapter tidak membuktikan adapter dipakai.
- Apakah perilaku fallback dan tie-break sama pada mode aplikasi dan mode eksperimen?

Pemeriksaan sifat-sifat tersebut harus memiliki hasil aktual atau status belum diuji. Jika kode berbeda dari rancangan lama, jelaskan perbedaannya tanpa mengubah kode untuk membuatnya cocok.

## 6. Audit dataset dan representasi

Hitung ulang dari sumber yang benar-benar dipakai:

- Nama berkas, hash, jumlah baris dan kolom, ID unik, serta ID hilang/tidak valid.
- Jumlah baris identik dan kemunculan tambahan dari ID berulang; jangan menyamakan kedua jenis duplikasi.
- Aturan penggabungan per field, konflik nilai, dan jumlah dokumen akhir.
- Jumlah lagu dengan/tanpa lirik dan lirik pendek; gunakan lagu unik sebagai penyebut cakupan.
- Field judul, artis, album, playlist, genre, popularitas, dan fitur audio yang dipakai.
- Nilai hilang, tipe, satuan, dan rentang fitur numerik yang masuk ke filter/skor.
- Apakah genre merupakan genre lagu atau label playlist? Apakah satu lagu memiliki beberapa label?
- Asal metadata/lirik yang dapat dibuktikan. Nama file bukan bukti metode pengambilan atau ketepatan pasangan lirik.

Angka historis 1.686 baris, 1.437 lagu unik, dan 1.404 lagu dengan lirik hanya boleh menjadi pembanding. Gunakan angka hasil audit saat ini dan jelaskan jika berubah.

Untuk embedding, laporkan model ID, revision aktual, dimensi, bentuk matriks, dtype, device, urutan serialisasi teks, normalisasi vektor, batas token, kebijakan chunking, jumlah dokumen yang benar-benar di-chunk, dan identitas corpus cache. Bedakan embedding dokumen dengan embedding bagian lirik.

Jika tidak ada fine-tuning, tulis bahwa encoder pretrained digunakan tanpa pelatihan ulang. Jangan menyebut pembuatan embedding sebagai training.

## 7. Uraikan metode dan skor secara operasional

Catat rumus, parameter aktif, sumber nilainya, dan lokasi kode. Jangan menyalin rumus teori jika implementasinya berbeda.

Periksa komponen yang benar-benar ada, antara lain:

- BM25: tokenisasi, variasi IDF, k1, b, field dan bobot, serta cara penggabungan skor field.
- Semantik: exact/approximate search, cosine atau metrik lain, cakupan dokumen, dan transformasi skor dari backend.
- Fitur audio: operator batas, perlakuan nilai hilang, definisi persentil dan nilai seri, preferensi tinggi/rendah, serta arti skor konstan.
- Fusion: daftar yang digabungkan, rank mulai dari nol/satu, konstanta RRF, posisi pemotongan, dan deduplikasi.
- Reranking: fitur, normalisasi, bobot, rentang skor, bonus/penalti, dan tie-break.
- Katalog/lirik: exact match, toleransi kesalahan, ambang, anggaran edit, serta apakah bukti tertentu diprioritaskan.
- Tema/suasana: query expansion, deskripsi pembanding, ukuran bagian, overlap, batas kandidat, pooling, penanda konteks, dan penggunaan valence/energy jika ada.
- Cache: kunci, lokasi, invalidasi, kapan encoding terjadi, serta pengaruh miss/hit terhadap hasil dan waktu.
- Fallback: kapan terjadi, apa yang dinonaktifkan, bagaimana bobot berubah, dan peringatan yang dikirim.

Pisahkan parameter awal, parameter yang dipilih dari kasus pengembangan, dan parameter hasil tuning pada development set berlabel. Sebutan `tuned=true/false` dalam konfigurasi perlu diperiksa terhadap log kegiatan tuning, bukan dipercaya sendiri.

Untuk sedikitnya tiga hasil pencarian yang mewakili jenis skor berbeda, ekspor seluruh kontribusi angka dan buktikan bahwa rumus menghasilkan skor akhir dalam toleransi numerik yang dinyatakan. Jika skor dapat melebihi satu, jelaskan komponennya. Jika skor satu hanya berarti lolos syarat, jangan menafsirkannya sebagai relevansi 100%.

## 8. Jalankan validasi fungsional dan studi kasus

Jalankan tes yang tersedia dan simpan log lengkap beserta command, durasi, environment, serta jumlah passed/failed/skipped. Jelaskan alasan tes yang dilewati dan dependensi yang tidak diuji.

Susun daftar kasus sebelum menjalankannya. Sertakan jenis pencarian yang didukung: judul, artis/kolaborasi, kutipan lirik, kesalahan ingatan terbatas, tema, genre, audio murni, campuran teks–audio, dan kasus gagal/hasil kosong. Tambahkan pemeriksaan query kosong, Unicode, lagu tanpa lirik, beberapa batas, nilai ambang, deduplikasi, dan fallback bila relevan.

Query yang pernah digunakan untuk memperbaiki aturan harus diberi label **kasus pengembangan/regresi**, bukan test independen. Jangan mengarang riwayat perubahan atau hasil sebelum perbaikan jika log historis tidak ada.

Gunakan tabel:

| Case ID | Query/input | Asal kasus | Perilaku yang diharapkan dan dasarnya | Mode/backend | Hasil aktual | Status | Bukti |
|---|---|---|---|---|---|---|---|

Simpan keluaran JSON aktual, ID dan urutan hasil, intent, filter, asal kandidat, skor, serta alasan. Bila aplikasi memiliki daftar utama/serupa, ekspor keduanya secara terpisah.

Assertion tentang kecocokan artis, batas tempo, atau keberadaan frasa merupakan pemeriksaan fungsi. Jangan mengubahnya menjadi label relevansi semantik keseluruhan.

## 9. Tentukan status evaluasi efektivitas retrieval

Periksa berkas dan penyimpanan evaluasi yang sebenarnya. Jangan menganggap draft query sudah dinilai. Laporkan:

1. Jumlah query draft, telah direview, dan layak evaluasi; komposisi kategori dan split aktual.
2. Sumber query, group_id, kebocoran antar-split, dan pemakaian query saat mengubah aturan.
3. Jumlah pasangan query–dokumen dengan judgment, query yang memiliki judgment, serta query yang mempunyai setidaknya satu dokumen relevan.
4. Asal label: manusia, aturan metadata, keluaran model, atau data sintetis. Catat skala dan pedoman anotasinya.
5. Jumlah penilai, pemeriksaan silang, dan adjudikasi yang benar-benar dilakukan.
6. Cara pooling kandidat dan proporsi hasil yang belum dinilai. Bedakan unjudged dari label manusia 0.
7. Definisi ranking yang dinilai: kandidat retrieval, hasil utama, hasil serupa, atau gabungan tampilan.

### Jika qrels manusia yang layak tersedia

- Jalankan seluruh mode pembanding yang tersedia pada corpus, query, dan qrels yang sama dengan konfigurasi dibekukan. Pisahkan AUTO dari E5 jika implementasinya berbeda.
- Laporkan nDCG@10, MRR@10, Recall@100 atau metrik yang benar-benar didukung. Jelaskan rumus gain nDCG, ambang relevansi biner, penyebut, penanganan hasil kosong, serta query tanpa relevan.
- Periksa evaluator dengan fixture hitungan manual yang terpisah dari data penelitian. Jangan menyamakan skor fixture dengan hasil dataset nyata.
- Ekspor ranking sampai kedalaman yang diperlukan, metric per query, agregat makro, dan per kategori. Jangan membandingkan Recall@100 kandidat dengan Recall daftar utama yang dibatasi 24 sebagai objek yang sama.
- Pertahankan daftar query wajib. Query gagal tidak boleh dibuang diam-diam; catat kegagalan, sertakan ringkasan diagnostiknya, dan tandai run `incomplete` bila ada kegagalan wajib.
- Jelaskan apakah dataset evaluasi independen dari pengembangan. Bila label atau query dipakai untuk menyusun aturan, nyatakan keterbatasannya.

### Jika qrels manusia belum tersedia atau tidak layak

- Nyatakan alasannya secara spesifik dan gunakan `null` untuk metrik efektivitas yang belum dapat dihitung; jangan mengisinya dengan nol seolah-olah sistem telah dievaluasi.
- Jangan membuat ground truth dari output sistem sendiri, target_song_id saja, label otomatis LLM, atau kesukaan agent.
- Label berbasis aturan genre/tempo, jika digunakan, hanya menjadi evaluasi proksi yang diberi nama dan batasan tersendiri.
- Tetap selesaikan audit pipeline, validasi fungsi, dan pengukuran waktu yang memungkinkan.
- Siapkan lembar anotasi dari query aktual dengan kandidat dan ID yang dapat diperiksa manusia. Hilangkan nama mode/skor saat penilaian agar tidak mengarahkan penilai. Tandai query yang masih perlu review.
- Jelaskan pekerjaan manusia yang diperlukan untuk memperoleh evaluasi relevansi yang sah. Jangan menyatakan keunggulan E5/AUTO berdasarkan studi kasus terpilih.

## 10. Ukur latensi dengan batas yang jelas

Pisahkan data waktu historis dari pengukuran ulang saat audit. Jika lingkungan memungkinkan, lakukan pengukuran awal pada satu set query tetap yang sama untuk seluruh mode yang dibandingkan.

- Gunakan 10 request warm-up yang terdokumentasi dan sedikitnya lima pengulangan setiap query; satu request aktif untuk pengukuran dasar.
- Bila pengujian penuh terlalu lama, pilih satu subset tetap yang mencakup kategori yang didukung. Bekukan sebelum menjalankan semua mode dan laporkan ukuran serta keterbatasannya.
- Acak urutan mode dengan seed tercatat. Jangan memakai subset mudah yang berbeda untuk setiap mode.
- Laporkan cold start/model load, biaya embedding corpus, cache miss bagian lirik, cache hit, engine time, dan waktu request ujung ke ujung secara terpisah sejauh dapat diukur.
- Jelaskan persis kapan timer mulai/berakhir. Verifikasi apakah trace, encoding query, pembentukan alasan, dan serialisasi termasuk di dalamnya.
- Gunakan waktu klien HTTP untuk end-to-end hanya bila batas pengukurannya memang demikian. Jika termasuk penulisan file/log, beri nama waktu skrip, bukan latensi HTTP murni.
- Jangan menghapus cache pengguna untuk membuat kondisi cold. Gunakan namespace/cache audit terpisah bila didukung, atau jelaskan bahwa pengukuran cold tidak dapat dilakukan secara terkontrol.
- Jangan menyembunyikan response/query cache. Jika tidak dapat dinonaktifkan lewat opsi yang ada, laporkan keadaan tersebut.
- Sinkronkan pekerjaan GPU bila diperlukan untuk timing yang valid. Catat runtime hardware, threads, jumlah request, error, dan kondisi proses lain.
- Ekspor seluruh pengulangan, lalu hitung mean, median, p95, dan jumlah observasi dengan definisi agregasi yang jelas. Satu pengamatan sebelum/sesudah cache bukan distribusi benchmark.

Jangan menyatakan rasio percepatan umum dari satu pasangan query. Jika tahap berjalan konkuren, jumlah waktu tahap tidak perlu sama dengan total wall time; jelaskan overlapnya.

## 11. Rekam bukti yang dapat dikirim

Setiap angka atau klaim penting diberi ID bukti, command/prosedur, lokasi kode bila relevan, berkas hasil, snapshot, dan status verifikasi.

Contoh nilai status, bukan hasil yang boleh disalin sebagai fakta:

```json
{
  "claim_id": "CLM-001",
  "claim": "Backend yang dipakai pada run pencarian",
  "value": null,
  "verification_status": "not_verified",
  "code_reference": null,
  "evidence_file": null,
  "reason": "Diisi berdasarkan pemeriksaan nyata"
}
```

Jika frontend dapat dijalankan, ambil tangkapan layar asli: pencarian, satu contoh alasan/trace, hasil kosong, dan tampilan metrik/status evaluasi. Jangan menggambar ulang UI seolah-olah screenshot aplikasi. Jangan memasukkan credential atau informasi pribadi yang tidak diperlukan.

Jangan hanya memberikan tautan ke `../artifacts/...` yang tidak disertakan. Semua bukti yang dirujuk laporan fakta harus tersedia di paket keluaran, atau diberi label jelas belum disertakan.

## 12. Format keluaran

Buat satu folder audit baru dengan timestamp, tanpa menimpa run lama. Isinya:

```text
audit_music_ir_<timestamp>/
  FAKTA_PROYEK_MUSIC_IR.md
  audit_summary.json
  pipeline_actual.mmd
  pipeline_actual.png             # jika dapat dirender
  config_snapshot.json            # konfigurasi efektif, tanpa secret
  evidence/
    data_audit.json
    verification_log.txt
    cases.jsonl
    search_traces.jsonl
    latency_raw.csv
    retrieval_metrics_per_query.csv  # hanya bila evaluasi sah dapat dijalankan
    retrieval_metrics_summary.json
    annotation_needed.csv           # bila penilaian belum lengkap
    screenshots/                    # tangkapan layar asli bila tersedia
```

Tambahan berkas boleh dibuat bila diperlukan, tetapi hindari keluaran yang tersebar dan berulang. File yang belum dapat dihasilkan harus dicatat status dan alasannya; jangan membuat file kosong seolah-olah berisi hasil.

Susunan wajib `FAKTA_PROYEK_MUSIC_IR.md`:

1. Ringkasan proyek dalam bahasa sederhana.
2. Snapshot kode, konfigurasi aktif, dan lingkungan runtime.
3. Dataset serta hasil audit aktual.
4. Pipeline offline dan online, diagram, serta tabel tahapan.
5. Metode, parameter, rumus skor, dan contoh perhitungan yang diverifikasi.
6. Perbedaan AUTO dan konfigurasi eksperimen yang benar-benar tersedia.
7. Hasil validasi fungsional dan studi kasus.
8. Status serta hasil evaluasi efektivitas retrieval.
9. Hasil pengukuran waktu dan kondisi cache.
10. Temuan ketidaksesuaian/bug beserta dampaknya.
11. Keterbatasan dan data yang belum tersedia.
12. Ringkasan bahan yang dapat digunakan untuk Bab 3, Bab 4, dan kesimpulan, disertai ID bukti.

Pada bagian terakhir, gunakan tabel:

| Pernyataan calon laporan | Dasar bukti | Status | Batas kesimpulan | Bagian laporan yang sesuai |
|---|---|---|---|---|

Tulislah tabel faktual dan penjelasan teknis yang runtut. Jangan menulis bab akademik lengkap. Hindari kata “terbukti unggul”, “optimal”, “akurat”, atau “100%” tanpa pengukuran dan penyebut yang mendukungnya.

## 13. Pemeriksaan sebelum menyerahkan

- Semua versi/angka berasal dari pembacaan atau run yang tercatat.
- Diagram, tabel metode, config efektif, dan trace menjelaskan pipeline yang sama.
- Rancangan lama, fitur yang ada di kode, dan jalur yang dijalankan tidak dicampur.
- Histori pengujian tidak dinyatakan sebagai run audit baru.
- Tes gagal/skipped, fallback, dan query gagal dilaporkan.
- Metrik tanpa label sah tidak diisi dengan hasil buatan.
- Klaim tentang relevansi dibedakan dari kepatuhan filter dan keberhasilan fungsi.
- Setiap berkas bukti yang dirujuk tersedia di folder atau jelas dinyatakan tidak tersedia.
- Tidak ada perubahan diam-diam pada pipeline, parameter, corpus asli, atau label pengguna.

Buat `PAKET_FAKTA_MUSIC_IR_<timestamp>.zip` dari folder tersebut. Jangan sertakan model weights, node_modules, virtual environment, cache vektor besar, atau seluruh lirik mentah yang tidak diperlukan untuk membaca bukti.

Respons akhir cukup memuat lokasi Markdown utama dan ZIP, snapshot yang diaudit, pengujian yang benar-benar dijalankan, status evaluasi retrieval, serta kekurangan terpenting. Jangan mengklaim audit selesai menyeluruh jika ada komponen yang belum dapat diverifikasi.

**Mulai dengan menelusuri jalur request dan konfigurasi aktif. Selesaikan paket fakta serta bukti yang dapat diperoleh; penyusunan ulang laporan UAS dilakukan setelah paket ini diperiksa.**
