# Music IR — Kelompok 4

Prototipe pencarian judul, artis, potongan lirik, dan query semantik berdasarkan **Laporan_UTS_TKI_Kelompok_4_Revisi (ril).pdf**. PDF sebelumnya tidak menjadi acuan implementasi.

## Status

- UI **React + TypeScript + Vite** dengan tata letak bergaya Spotify: sidebar koleksi, kartu sampul album, pencarian, daftar lagu, favorit, playlist lokal, detail lirik/fitur audio, dan pemutar Spotify embed. UI Streamlit telah diganti.
- Pencarian aplikasi, API, dan CLI memakai **satu pipeline otomatis (`AUTO`)**: BM25 berbobot + BGE-M3 → RRF → reranking teks dan fitur audio sesuai query. E1–E5 tersedia sebagai konfigurasi eksperimen untuk laporan.
- Corpus dari CSV pengguna: 1.686 baris → **1.437 lagu unik**, 33 tanpa lirik. Teks asli disimpan; metadata playlist digabung sebagai daftar. Hasil audit ada di `data/processed/audit.json`.
- **E1/E2** dapat berjalan langsung dengan BM25 lokal. Implementasi lokal adalah alat demo dan pengujian; analyzer serta skor tidak diklaim identik dengan Lucene/Elasticsearch.
- Adapter Elasticsearch tersedia untuk menjalankan eksperimen laporan. Server dapat dijalankan melalui distribusi Windows portabel di proyek atau Docker.
- **E3/E4/E5 dengan teks** memerlukan embedding BGE-M3 yang dibuat menggunakan perintah `embed`. Tidak ada pengganti semantik berbasis kata kunci jika model belum tersedia.
- **E5 audio murni** bisa berjalan tanpa embedding, misalnya `tempo > 120 BPM` atau `energi rendah`.
- Bobot pada `config.json` masih nilai awal, **belum hasil tuning**. Belum ada klaim efektivitas atau qrels hasil penilaian manusia.
- Jejak keputusan dapat diperiksa lewat panel pencarian atau `--trace`. Halaman **Benchmark & penilaian** menyediakan 160 draft query (40 dev / 120 test), peninjauan definisi, pool kandidat, nilai manusia 0–3 yang disimpan di backend, serta ekspor query/qrels. Draft dan pool awal **tidak memiliki label relevansi otomatis**.

## Instalasi Windows / PowerShell

Dari folder proyek:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
npm --prefix frontend ci
```

Node.js 22.12+ atau 24 LTS dan npm diperlukan untuk frontend; lingkungan proyek memakai Node 24. `frontend/package-lock.json` mengunci dependensi React. Chrome diperlukan untuk pengujian browser Playwright dengan konfigurasi bawaan.

`requirements.lock.txt` mencatat dependensi backend, model semantik, dan pengujian yang sudah diverifikasi pada Windows/Python 3.14. Untuk mereplikasi versi tersebut: `python -m pip install -r requirements.lock.txt`, lalu `python -m pip install -e . --no-deps` dalam `.venv`. Streamlit tidak lagi menjadi dependensi.

Lingkungan proyek memakai Python 3.14 dalam virtual environment terisolasi. Python 3.11+ didukung; ketersediaan wheel PyTorch bergantung platform.

Siapkan corpus (tidak mengubah CSV sumber):

```powershell
.\.venv\Scripts\python.exe -m music_ir prepare --csv "C:\Users\sumhel\Downloads\high_popularity_spotify_data_lrclib.csv"
```

Corpus disimpan sebagai JSON dan Parquet. Audit mencatat SHA-256 sumber dan corpus, konflik nilai, lirik pendek, serta cakupan lirik. Untuk record berulang dipilih nilai tidak kosong pertama; semua konflik dicatat agar dapat ditinjau. Lagu berbeda ID tidak digabung walaupun judulnya sama. Kecocokan lirik dengan rekaman masih berstatus `unknown` sampai diaudit manusia.

## Menjalankan aplikasi

Buka dua terminal dari folder proyek.

Terminal 1 — backend:

```powershell
.\run.ps1 api
```

Terminal 2 — antarmuka React:

```powershell
.\run.ps1 ui
```

Buka **http://127.0.0.1:8501**. Dokumentasi API berada di **http://127.0.0.1:8000/docs**. Jika eksekusi skrip PowerShell dibatasi, jalankan perintah berikut tanpa mengubah kebijakan eksekusi sistem:

```powershell
.\.venv\Scripts\python.exe -m uvicorn music_ir.api:app --host 127.0.0.1 --port 8000 --reload --reload-dir music_ir
# Terminal lain:
npm --prefix frontend run dev
```

`run.ps1 api` mengaktifkan reload untuk perubahan kode Python di `music_ir/`. Jika backend sudah berjalan sebelum pembaruan ini, hentikan proses lama dengan Ctrl+C lalu jalankan ulang sekali. Error validasi `mode=AUTO` dengan pola `^E[1-5]$` berarti backend masih menjalankan versi lama. Periksa `http://localhost:8000/health`: versi terbaru mencantumkan `"default_mode": "AUTO"`. UI mendeteksi backend lama dan menampilkan instruksi untuk memuat ulang backend.

Jika port 8501 masih dipakai Streamlit lama, hentikan terminal Streamlit dengan Ctrl+C sebelum menjalankan React. Vite memakai `strictPort`, sehingga tidak berpindah diam-diam ke port lain. Perubahan React/CSS langsung diperbarui melalui hot reload.

Build dan pratinjau hasil produksi lokal:

```powershell
.\run.ps1 build
.\run.ps1 preview
```

Frontend memanggil `/api/*` pada origin yang sama; Vite meneruskan request ke FastAPI `http://127.0.0.1:8000`. Untuk port backend lain, set `$env:MUSIC_IR_API = "http://127.0.0.1:<port>"` sebelum menjalankan frontend. Preview build juga memakai proxy ini. Jika meng-host `frontend/dist` dengan server lain, konfigurasikan reverse proxy `/api/*` ke FastAPI dan fallback SPA ke `index.html`. Perubahan `MUSIC_IR_API` memerlukan restart Vite.

## Fitur antarmuka React

- Beranda menampilkan lagu dari corpus, diurutkan berdasarkan popularitas pada CSV; ini bukan chart Spotify terkini atau rekomendasi personal yang sudah dilatih.
- Pencarian menerima judul, artis, potongan lirik, tema, dan batas audio. Tekan Enter atau pilih kartu suasana. Shortcut `Ctrl+K`/`Cmd+K` memfokuskan kolom pencarian.
- Sidebar menyediakan koleksi per genre, artis, Lagu yang Disukai, dan playlist. Favorit serta playlist dapat ditambah/dihapus dan disimpan melalui `localStorage` pada browser/origin yang sama; belum ada akun atau sinkronisasi antardevice.
- Klik judul/sampul untuk membuka detail, lirik lengkap, fitur audio, dan alasan kecocokan. Lirik berasal dari dataset pengguna; kualitas pencocokan rekaman tetap mengikuti batasan audit corpus.
- Tombol play membuka **Spotify embed** untuk lagu yang dipilih. Audio/pratinjau dan kontrol pemutaran mengikuti ketersediaan Spotify; dataset ini tidak menyimpan file audio. Tombol sebelum/berikutnya dan acak mengubah pilihan lagu dalam antrean halaman. Tidak ada simulasi audio atau progres pemutaran lokal.
- Pengaturan pencarian tersedia melalui ikon pengaturan, profil K4, atau indikator pencarian di sidebar. `AUTO` adalah default; E1–E5 tetap tersedia untuk eksperimen.
- Sampul 47 album populer dan font DM Sans dibundel lokal. Lagu tanpa sampul memakai cover CSS. Sumber dan lisensi tercatat di `frontend/public/ASSETS.md`; pemutaran embed tetap memerlukan internet. Untuk memperbarui cache sampul, jalankan `.\.venv\Scripts\python.exe scripts/fetch_artwork.py`.
- Layout responsif pada desktop/mobile, memiliki dialog dengan fokus keyboard, label tombol, tampilan loading/error, dan dukungan reduced motion.

Endpoint baru: `GET /catalog?limit=60&offset=0&genre=pop` untuk katalog berpaginasi dan jumlah per genre; `GET /tracks/{track_id}` untuk metadata serta lirik. `POST /search` sekarang juga mengembalikan `album_id`, durasi, genre, popularitas, dan tanggal rilis agar format lagu konsisten di seluruh UI. Sampul tidak diunduh di jalur pencarian.

CLI tanpa antarmuka:

```powershell
.\.venv\Scripts\python.exe -m music_ir search "Die With A Smile"
.\.venv\Scripts\python.exe -m music_ir search "Bruno Mars"
.\.venv\Scripts\python.exe -m music_ir search "tempo > 120 BPM"
```

## Satu pipeline untuk pengguna

E1–E5 adalah **konfigurasi eksperimen (ablasi)**, bukan lima model terpisah. E1/E2 mengukur pencarian kata dengan BM25; E3 menambahkan embedding BGE-M3; E4 menambahkan reranking berbasis fitur; E5 menambahkan fitur audio dari CSV. E1/E2 memang tidak melakukan semantic search karena berfungsi sebagai baseline pembanding.

Pengguna cukup memasukkan query tanpa memilih metode. `AUTO` menjalankan alur berikut:

1. Kenali judul, artis, genre playlist, kutipan lirik, query tema, teks biasa, serta permintaan audio. Kata audio dalam kutipan diperlakukan literal; pencarian judul persis tetap berjenis `title` walaupun judul juga muncul di lirik.
2. Query katalog memakai kecocokan metadata. Query teks lain memakai BM25 judul–artis–lirik dan cosine embedding BGE-M3. Query katalog dan audio murni tidak membutuhkan encoder. Filter katalog/audio AUTO diterapkan sebelum mengambil kandidat.
3. Gabungkan sumber kandidat dengan RRF dan urutkan sesuai intent. Pencarian tema menilai bagian lirik dengan encoder yang sama; potongan lirik persis/mirip tetap mendapat prioritas tersendiri. Kandidat teks biasa memakai fitur berbobot, dan batas audio tetap wajib.
4. Tampilkan kecocokan langsung terpisah dari `related_results`. `top_k` adalah batas maksimum gabungan kedua kelompok, sehingga hasil judul/artis tidak diisi lagu lain untuk memenuhi 30 baris.

Pencarian artis mencocokkan nama/urutan kredit lengkap, termasuk kolaborasi dan nama yang mengandung koma. Sumber CSV belum memiliki ID artis per anggota, sehingga pemisahan kredit tetap berbasis teks. Judul memakai normalisasi token; toleransi judul multikata terbatas pada similarity urutan token >=0,75, minimal tiga kata bersama dan maksimal satu edit kata, lalu memilih kecocokan terbaik. Kutipan lirik tidak ditulis ulang oleh aturan judul. `rock song`, `lagu rock`, dan `genre rock` memakai `playlist_genre`, bukan kemunculan kata rock pada judul. Label tersebut adalah kategori playlist dan belum menjamin genre rekaman yang sebenarnya. Kandidat katalog dengan kecocokan sama diurutkan menurut popularitas CSV, lalu ID sebagai tie-break stabil.

`AUTO` mengenali awalan `lirik`, `potongan lirik`, `lagu yang liriknya`, `lyrics`, atau kutipan ganda sebagai pencarian lirik. Potongan yang cocok juga dapat ditemukan tanpa awalan. Pencocokan memakai normalisasi Unicode/apostrof, ekspansi kontraksi umum, lalu jendela token berurutan. Jika tidak ada frasa persis, query 4–32 token dengan sedikitnya tiga token unik dapat memakai toleransi terbatas: minimal 60% token unik mendukung kandidat (minimal tiga), paling banyak 200 kandidat diperiksa, anggaran satu edit token untuk query sampai enam token atau dua untuk query lebih panjang, dan similarity minimal 0,76. Typo satu karakter atau transposisi pada kata minimal empat karakter mendapat biaya substitusi 0,35. Similarity ini jarak teks, bukan probabilitas relevansi.

Kandidat dengan bukti lirik dicadangkan dalam batas kandidat dan tetap melewati filter audio. Setelah skor dasar, frasa persis memperoleh tambahan 4; kecocokan mirip memperoleh tambahan `2 × similarity`. Ini aturan prioritas yang belum dituning; skor dapat melebihi 1. Teks sumber tidak diubah. Respons `lyric_match` menyebut `exact` atau `approximate`; cuplikan diambil dari bagian yang dicocokkan. Bukti lirik tambahan pada judul katalog tidak mengubah jenis query atau menambahkan bonus lirik. Hasil tanpa bukti kutipan dipisahkan ke `related_results`, termasuk saat kutipan eksplisit belum cocok sama sekali. Frasa yang sama dapat dimiliki beberapa lagu sehingga tidak selalu mengidentifikasi satu rekaman.

Awalan `lagu tentang`, `lagu bertema`, `lagu bermakna`, atau `a song about` dibersihkan sebelum retrieval. Query suasana yang dikenali, seperti `lagu happy/bahagia/ceria/gembira`, `lagu sad/sedih/galau`, dan `lagu bermakna sedih`, memakai perluasan deskripsi tema yang tetap di `music_ir/query.py`. Misalnya, `lagu happy` memakai `happiness, joy, feeling happy and celebrating life` untuk encoder. Judul atau artis yang persis ada di corpus serta kutipan lirik dilindungi dari aturan suasana. Parser ini masih berbasis pola terbatas. Tanpa semantik, fallback tetap diberitahukan.

Jika embedding belum siap/tidak cocok, atau encoder gagal dijalankan, `AUTO` tetap mencari memakai kata kunci dan fitur audio. Respons menyediakan `warnings` dan `pipeline.degraded=true`; UI menampilkan pemberitahuan tersebut. Fitur cosine dihapus dari skor dan bobot teks yang tersisa dinormalisasi ulang. Jika seluruh bobot awal hanya untuk cosine, fallback memakai BM25. Hasil fallback **tidak diklaim semantik** dan query berbasis makna dapat tidak menemukan lagu yang relevan.

`AUTO` memiliki aturan lirik/tema tambahan sehingga tidak lagi selalu identik dengan E5. E1–E5 mempertahankan algoritma pembanding semula dan tidak fallback agar eksperimen dapat direproduksi; E3/E4/E5 dengan query teks menghasilkan error jika semantik gagal. Pilihan tersebut tersedia dalam dialog **Pengaturan pencarian** pada UI React. Evaluasi dapat menyertakan `--modes E1 E2 E3 E4 E5 AUTO`; run evaluasi AUTO menolak fallback pada query yang membutuhkan semantik agar hasil degradasi tidak tercampur sebagai eksperimen penuh.

API menerima `POST /search` dengan `{"query": "lagu tentang kehilangan"}`; `mode` opsional dengan default `AUTO`. Respons mencatat komponen pada `pipeline`, jenis query pada `query_type`, teks encoder pada `semantic_query`, bukti per hasil pada `lyric_match`, dan pemberitahuan pada `warnings`. `/health` melaporkan `default_mode` dan `semantic_ready`; `semantic_ready` menunjukkan artefak embedding cocok, sedangkan pemuatan encoder diuji saat query teks pertama. Kegagalan encoder tidak menghalangi startup API atau pencarian kata kunci/audio.

BM25 dan embedding tetap menjadi komponen internal yang saling melengkapi: [dokumentasi Elastic](https://www.elastic.co/docs/solutions/search/hybrid-search) menjelaskan penggabungan lexical–semantic dengan RRF. [BGE-M3](https://huggingface.co/BAAI/bge-m3) mendukung dense, sparse, dan multi-vector retrieval, tetapi proyek ini saat ini hanya memakai dense embedding melalui SentenceTransformer. Mengganti BM25 dengan sparse BGE-M3 adalah eksperimen tambahan yang perlu pengukuran, bukan syarat untuk menyatukan pengalaman pencarian.

Untuk query katalog persis (misalnya `rock song` atau nama artis) dan filter audio murni (misalnya `tempo > 120 BPM`), hasil dapat sama-sama memiliki `score=1`. Ini **indikator bahwa syarat terpenuhi**, bukan kemiripan semantik atau akurasi 100%. Query `tempo > 120 BPM` tidak meminta tempo setinggi mungkin maupun tempo yang paling dekat dengan 120; semua lagu di atas batas itu memenuhi syarat yang sama. `tempo cepat` merupakan preferensi berbeda yang memberi skor berdasarkan percentile tempo.

Respons `ranking` dan `trace.decisions.ranking` menjelaskan `score_kind`, `score_meaning`, serta `order_by`. Pada katalog/filter murni AUTO, urutan skor seri memakai **popularitas dari CSV menurun**, kemudian ID lagu. Pemilihan kandidat audio dengan skor konstan juga memakai popularitas sebelum batas 100 kandidat diterapkan, sehingga lagu populer tidak tersisih hanya karena ID-nya lebih besar. Popularitas kosong diperlakukan sebagai 0 untuk pengurutan. Kombinasi dengan preferensi audio tetap memakai skor komponen terlebih dahulu. E1–E5 mempertahankan algoritma pengurutan eksperimen sebelumnya.

Panel audit menampilkan **Memenuhi syarat** untuk skor indikator, disertai nilai numerik dan popularitas. Nilai 1 tetap disimpan pada JSON untuk menjaga arti indikator dan kompatibilitas; variasi skor tidak dibuat-buat. `ordering_values` mencatat nilai setiap kandidat, dan `eligible_after_filters` mencatat jumlah lagu yang lolos sebelum pembatasan kandidat (contoh corpus saat ini: 730 untuk `tempo > 120 BPM`, 212 untuk label genre rock).

## Menyiapkan semantik

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[semantic]"
.\.venv\Scripts\python.exe -m music_ir embed --batch-size 4
```

BGE-M3 diunduh pada pemakaian pertama, membutuhkan koneksi internet, ruang disk beberapa GB, dan waktu komputasi yang bergantung CPU/GPU. Ini **inferensi model pretrained**, bukan pelatihan dari nol. Pada CPU, pembentukan seluruh corpus dapat memerlukan puluhan menit hingga beberapa jam. Progres tersedia dalam dialog **Pengaturan pencarian** (tekan **Perbarui status model**) dan `artifacts/semantic/progress.json`. Backend mendeteksi embedding lengkap secara otomatis; pemuatan model pada query semantik pertama tetap memerlukan waktu.

Setiap batch disimpan sebagai checkpoint. Jika proses terhenti, jalankan perintah `embed` yang sama untuk melanjutkan potongan yang tersisa. Identitas corpus, teks, dan revisi model diperiksa sebelum checkpoint dipakai ulang. Setelah unduhan model selesai, `embed --local-files-only` dapat dipakai untuk melanjutkan tanpa koneksi internet. Jangan menjalankan dua proses embed bersamaan; file lock mencegah penulisan bersamaan.

Representasi dokumen: `Judul: <judul>\nArtis: <artis>\nLirik: <lirik>`. Lagu tanpa lirik memakai metadata. Teks sampai 8.192 token diproses utuh; teks lebih panjang dibagi menjadi 512 token dengan overlap 64, embedding potongan dirata-ratakan lalu dinormalisasi. Embedding query menggunakan model dan commit yang sama dengan dokumen. Revisi model diselesaikan menjadi commit sebelum build; hash corpus dan urutan ID disimpan bersama vektor. Artefak yang berbeda corpus ditolak.

AUTO menambahkan penilaian tema berbasis **lirik saja** untuk maksimal `theme.candidate_limit=24` kandidat awal. Lirik dibagi menjadi 160 kata dengan overlap 40; embedding bagian dibuat oleh BGE-M3 yang sudah tersedia dan disimpan di `artifacts/semantic/passages.sqlite3`. Kunci cache mencakup teks, nama/revisi model, dan versi representasi sehingga perubahan sumber/model tidak memakai vektor lama. Bagian lirik dengan dukungan tertinggi menjadi cuplikan UI/trace. Bobot awal `theme.document_weight=0.4` menggabungkan embedding lagu dan bukti bagian lirik; bobot ini belum dituning.

Tema cinta dan sulit move on memiliki perluasan query serta deskripsi tema pembanding yang eksplisit di kode. Pada profil tersebut, sinyal bagian lirik memakai margin cosine tema terhadap tema pembanding (dibagi dua agar tetap dalam rentang cosine). Contohnya, cinta dibandingkan dengan pesta/pamer/kekerasan, sedangkan sulit move on dibandingkan dengan hubungan bahagia atau pencarian pasangan baru. Ini inferensi encoder tetap, tanpa pelatihan tambahan atau model kedua.

Untuk profil sulit move on, kandidat utama juga memerlukan penanda perpisahan/kehilangan dari aturan terbatas Indonesia, Inggris, Spanyol, atau Prancis. Kandidat tanpa penanda, serta kandidat tanpa bukti lirik, tetap dapat muncul sebagai **Hasil serupa**. Aturan ini memiliki keterbatasan bahasa/konteks dan tidak menjamin interpretasi tema benar. `theme_evidence` mencatat cuplikan, cosine, tema pembanding, dan penanda; kontribusi skor dapat diperiksa pada trace. Kandidat di luar batas pemeriksaan bagian lirik tidak dipromosikan sebagai hasil yang telah diperiksa.

Pencarian tema pertama dapat memerlukan puluhan detik pada CPU ketika bagian lirik kandidat belum di-cache; pencarian berikutnya memakai ulang vektor. Cache tidak memerlukan pengulangan build embedding seluruh corpus. Kegagalan pemeriksaan bagian lirik menghasilkan peringatan dan fallback ke embedding lagu. E1–E5 mempertahankan perhitungan eksperimen sebelumnya.

Pemeriksaan regresi tujuh kasus pengguna ditambah dua penjaga lirik/mood dapat dijalankan setelah API aktif. Ini pemeriksaan fungsional dan perbandingan trace, tanpa menghasilkan label relevansi atau mengklaim skor akurasi:

```powershell
.\.venv\Scripts\python.exe scripts/check_search_cases.py
# Opsional: baca tujuh export lama untuk menyertakan perbandingan sebelum/sesudah.
.\.venv\Scripts\python.exe scripts/check_search_cases.py --baseline-dir "$env:USERPROFILE\Downloads"
```

Hasil dan trace baru disimpan ke `artifacts/regressions/search-cases/`; file export asli tidak diubah.

```powershell
.\.venv\Scripts\python.exe -m music_ir search "lagu tentang sulit melupakan seseorang"
```

Untuk query suasana yang dikenali, AUTO memakai **Makna + musik** secara default sesuai kebutuhan pencarian lirik sedih sekaligus musik sendu. UI menyediakan tiga pilihan; API menerima `mood_basis`, dan CLI menerima `--mood-basis`:

- `both` / **Makna + musik**: kandidat disaring berdasarkan perkiraan nuansa audio, lalu diurutkan berdasarkan kemiripan makna teks.
- `lyrics` / **Makna lirik**: mengurutkan makna teks tanpa menambahkan batas suasana audio. Lagu dengan lirik sedih tetapi musik ceria masih bisa muncul.
- `audio` / **Nuansa musik**: mengurutkan valence/energy tanpa menilai makna lirik dan tanpa membutuhkan encoder semantik.

Kebijakan awal di `config.json` bagian `mood` memakai `sad_max_valence=0.5` dan `sad_max_energy=0.65` untuk suasana sedih/sendu; suasana ceria memakai `happy_min_valence=0.5`. Ini **heuristik yang dapat dikonfigurasi**, belum dituning atau divalidasi sebagai pengenal emosi. Valence rendah dan energy rendah hanya perkiraan nuansa; kemiripan embedding juga belum membuktikan bahwa makna lirik pasti sedih. Data audio berasal dari CSV yang sudah tersedia, sehingga tidak memerlukan Spotify Web API atau pelatihan model.

AUTO menerapkan batas audio sebelum mengambil kandidat teratas dari retrieval teks/semantik agar jatah kandidat tidak habis oleh lagu yang akhirnya gugur. Batas numerik eksplisit pada query tetap diiriskan dengan batas suasana; batas yang bertentangan dapat menghasilkan nol lagu dan tidak dilonggarkan otomatis. E1–E5 mempertahankan perilaku eksperimen sebelumnya dan tidak menerima `mood_basis`.

Contoh kasus corpus: Sugar — Maroon 5 memiliki valence `0.884` dan energy `0.788`, sehingga gugur dari pencarian sedih **Makna + musik**. Pencarian judul `Sugar` tetap menemukannya. Respons menyertakan `mood`, batas audio, dan jejak diagnostik yang menjelaskan penyaringan setiap lagu.

```powershell
.\.venv\Scripts\python.exe -m music_ir search "lagu bermakna sedih" --mood-basis both
.\.venv\Scripts\python.exe -m music_ir search "lagu bermakna sedih" --mood-basis lyrics
```

## Elasticsearch untuk eksperimen laporan

Alternatif **tanpa Docker**, unduh distribusi Windows portabel ke `.cache/` (SHA-512 diverifikasi; tidak memasang layanan Windows):

```powershell
.\.venv\Scripts\python.exe scripts/setup_elasticsearch.py
.\run.ps1 elasticsearch
```

Setelah server siap, buka terminal lain dan jalankan `index-elasticsearch` lalu backend dengan `MUSIC_IR_BACKEND=elasticsearch` seperti contoh di bawah. Unduhan pertama cukup besar. Server hanya mendengarkan localhost, dengan heap Java 512 MB. Hentikan server lewat Ctrl+C pada terminalnya.

Jalankan Docker Desktop terlebih dahulu. Compose memakai Elasticsearch 9.5.6 satu node, satu shard, dan port yang hanya terbuka ke localhost. Ini konfigurasi demo lokal; autentikasi dimatikan. Versi dipatok berdasarkan [rilis resmi](https://www.elastic.co/downloads/elasticsearch) saat proyek disiapkan.

```powershell
docker compose up -d
# Tunggu sampai http://localhost:9200 siap, kemudian:
.\.venv\Scripts\python.exe -m music_ir index-elasticsearch
$env:MUSIC_IR_BACKEND = "elasticsearch"
.\run.ps1 api
```

Pembuatan indeks memakai nama berversi lalu mengganti alias `music-ir-v1`; indeks sebelumnya tidak dihapus. Mapping menyimpan identitas corpus dan parameter BM25; pencarian menolak indeks yang berbeda corpus/config. Analyzer: tokenizer `standard` + `lowercase`, tanpa stemming/stopword removal. NFKC dan spasi dinormalisasi sebelum indexing.

E1 memakai field `combined`; E2 menjumlahkan `match` berbobot pada judul–artis–lirik menggunakan `bool.should`, bukan `best_fields`. BM25 k1=1,2 dan b=0,75. Bobot awal field adalah 3:2:1. Bobot akhir harus dipilih pada development set.

CLI Elasticsearch:

```powershell
.\.venv\Scripts\python.exe -m music_ir search "Bruno Mars" --mode E2 --backend elasticsearch
```

## Metode dan batasan

Tabel berikut adalah pembanding eksperimen; default pengguna adalah `AUTO` seperti dijelaskan di atas. Reranking saat ini merupakan penjumlahan fitur berbobot, **belum model cross-encoder terlatih**.

| ID | Perilaku |
|---|---|
| E1 | BM25 satu field gabungan, top-100 |
| E2 | Penjumlahan BM25 judul, artis, lirik berbobot, top-100 |
| E3 | E2 + exact cosine seluruh vektor; RRF c=60; 100 ID unik |
| E4 | Kandidat yang sama dengan E3; reranking teks |
| E5 | Jalur teks + kandidat audio seluruh corpus; filter numerik; RRF; reranking teks–audio |

Reranker teks memakai urutan fitur: BM25 min–max pada kandidat, cosine `(cos+1)/2`, kecocokan judul, kecocokan artis, dan frasa lirik. Kecocokan judul/artis memakai maksimum exact match dan Jaccard token. Fitur frasa aktif jika seluruh query (minimal dua token) muncul berturutan di lirik. Rentang BM25 nol dinormalisasi menjadi nol. Bobot awal teks adalah `[0.25, 0.25, 0.25, 0.25, 0]`; fitur frasa tersedia tetapi bobotnya belum diaktifkan sebelum tuning. Tie-break memakai RRF lalu `track_id`.

Intent audio memakai aturan terbatas yang dapat diperiksa, tanpa LLM. Contoh yang didukung:

- `tempo > 120 BPM`, `tempo di bawah 90 BPM`, `tempo >= 100 dan energi <= 0,5`.
- `tempo tidak di atas 120 BPM` berarti `tempo <= 120`.
- `tempo cepat`, `tempo lambat`, `energi tinggi`, `energi rendah`.
- `lagu Bruno Mars dengan tempo > 120 BPM`, `lagu bertema cinta dengan energi rendah`.
- Fitur numerik: tempo, energy/energi, valence, danceability, acousticness. Selain tempo, nilai menggunakan rentang 0–1.

Preferensi lunak memakai persentil mid-rank corpus, dibalik untuk preferensi rendah; nilai hilang atau fitur konstan netral 0,5. Fitur hilang tidak lolos batas keras. Jika hanya ada batas keras, semua kandidat yang lolos mendapat skor audio satu dan urutan `track_id`. Beberapa batas diterapkan bersamaan. Batas tidak dilonggarkan jika hasil kosong. Negasi yang didukung harus berada sesudah nama fitur seperti contoh; ini bukan parser bahasa alami umum.

Bobot audio awal 0,5 untuk query gabungan, 1 untuk audio murni, 0 tanpa intent audio. E1–E4 tidak memakai filter audio; ini mempertahankan pembanding terhadap E5. E5 tanpa intent audio identik dengan E4. Cuplikan biasa ditandai sebagai pratinjau, bukan bukti relevansi semantik. Alasan hasil berasal dari kecocokan terukur dan nilai CSV.

## Evaluasi dan tuning

`evaluation/queries.example.jsonl` hanya contoh format. `evaluation/queries.draft.jsonl` menyediakan **160 draft untuk ditinjau**, bukan benchmark final yang sudah dinilai. Qrels tidak diisi otomatis. CSV ekspor berisi `query_id,track_id,relevance,annotator`; label 0–3 dengan ambang relevan untuk MRR/Recall >=2. Setiap query JSONL memuat `query_id,query,category,split,group_id`. Query terkait lagu/templat sama berada dalam `group_id` dan split sama. File baru berstatus `draft` ditolak runner sampai definisinya disetujui. File format lama tanpa `review_status` tetap didukung, dengan label yang tetap harus diaudit manusia.

Ikuti target PDF: 160 query (judul, artis, lirik, semantik, audio), masing-masing 8 dev dan 24 test per kategori. Audit pasangan lirik–lagu dan lakukan penilaian manusia sebelum mengukur efektivitas. Pool anotasi perlu mencakup hasil E1–E5, target terverifikasi, dan sampel acak. Penilaian kedua serta penyelesaian konflik dilakukan di luar runner evaluasi.

```powershell
.\.venv\Scripts\python.exe -m music_ir evaluate --queries evaluation/queries.jsonl --qrels evaluation/qrels.csv --modes E1 E2 E3 E4 E5 --backend elasticsearch --split test
```

Runner menyimpan ranking per query, nDCG@10, MRR@10, Recall@100 terhadap relevansi yang diketahui, serta median/p95 latensi per konfigurasi/kategori. Dokumen belum dinilai dihitung 0; query tanpa label >=2 ditolak agar diaudit terlebih dahulu. Model dimuat sebelum timing, embedding query termasuk timing. Warm-up 10 query, lima repetisi, urutan acak seed 42, satu request aktif. Himpunan kandidat E3/E4 diperiksa identik. Waktu API/UI dan transmisi HTTP tidak masuk timing inti mesin; dokumentasikan batas pengukuran ini di laporan.

Runner kini juga mencatat `judged@10` (proporsi hasil top-10 yang memiliki penilaian), ID top-10 yang belum dinilai, jenis query, status pipeline, dan hash implementasi. Nilai efektivitas dengan cakupan penilaian rendah perlu dibaca bersama cakupan tersebut. Development dapat dievaluasi/tuning sebelum test selesai dinilai; validasi kebocoran `group_id` tetap mencakup seluruh file. Run AUTO yang fallback karena semantik gagal dihentikan agar tidak dianggap run penuh.

Tuning otomatis memakai **development set saja**: pilih field weights dari `(1,1,1)`, `(2,1,1)`, `(2,2,1)`, `(3,2,1)` pada query teks tanpa intent audio; selanjutnya 70 kombinasi bobot teks dengan langkah 0,25; terakhir lambda 0,25/0,5/0,75 pada query audio development. Optimasi bertahap memaksimalkan rerata nDCG@10; skor seri memilih percobaan pertama. Embedding dan fitur kandidat digunakan ulang saat mencoba bobot, sehingga encoder tidak dilatih ulang.

```powershell
.\.venv\Scripts\python.exe -m music_ir tune --queries evaluation/queries.jsonl --qrels evaluation/qrels.csv --backend elasticsearch
# Untuk tahap BM25 sebelum embedding tersedia, tambahkan --lexical-only.
```

Tinjau `artifacts/tuning/config.json` dan `trials.json`, lalu salin konfigurasi terpilih ke `config.json` dan muat ulang backend. Konfigurasi utama tidak ditimpa otomatis. `tuned=true` hanya jika tuning penuh mencakup query audio development. Bekukan konfigurasi sebelum evaluasi test. Jangan memilih parameter berdasarkan test. Interval kepercayaan bootstrap, pelaporan tambahan kandidat audio, pemanasan cache terperinci, dan audit manual masih pekerjaan eksperimen lanjutan.

## Jejak keputusan pencarian

Pada hasil pencarian React, buka **Jejak keputusan pencarian** lalu tekan **Lihat jejak**. ID/tautan Spotify lagu target opsional, termasuk lagu yang tidak muncul di hasil. Jejak menunjukkan jenis query terencana/efektif, teks yang dipakai encoder, asal kandidat dan posisi pada setiap jalur, posisi sebelum/sesudah reranking, kontribusi setiap komponen skor, filter audio yang gagal, serta jumlah kandidat per tahap. Kontribusi dijumlahkan ke skor akhir; fitur RRF tetap dijelaskan sebagai pemilih kandidat/tie-break ketika reranking digunakan.

Keputusan target dibedakan menjadi `not_in_corpus`, `not_retrieved`, `audio_filtered`, `candidate_limit`, atau `ranked`. Baris berstatus ranked dapat berada di luar 30 hasil yang ditampilkan UI. Unduh JSON untuk menyimpan snapshot corpus, konfigurasi, revisi model, hash implementasi, dan waktu tiap tahap. Waktu pemuatan/pemanasan encoder ditampilkan terpisah dari latensi pencarian inti. Pemeriksaan jejak menjalankan ulang query secara eksplisit; pencarian biasa tidak mengirim payload diagnostik.

```powershell
.\.venv\Scripts\python.exe -m music_ir search 'lirik "make the stars look like there not shining"' --trace --inspect-track-id 7BqBn9nzAq8spo5e7cZ0dJ
```

API: tambahkan `"trace": true` dan/atau `"inspect_track_id": "<id>"` pada `POST /search`. Data baru berada di `trace.decisions`; field trace lama dipertahankan agar tuner tetap kompatibel. Fitur ini tidak mengubah urutan/skor pencarian.

## Mengumpulkan benchmark manusia

Buka **http://127.0.0.1:8501/?view=benchmark**, atau **Pengaturan pencarian → Benchmark & penilaian**.

1. Masukkan nama/kode penilai dan tekan **Gunakan nama**. Pilih split dan kategori query.
2. Baca definisi query dan catatan intent. Perjelas query ambigu seperti `lagu happy` sebelum menyetujui definisinya. Koreksi draft melalui `evaluation/queries.draft.jsonl` jika diperlukan.
3. Tekan **Siapkan pool kandidat**. Sistem menggabungkan top-k E1–E5 dan AUTO saat semantik tersedia, hint dokumen sumber, serta dua sampel acak. Jika semantik belum siap, pool default hanya memakai E1/E2/AUTO dengan status fallback tercatat. Pool dapat diperbarui setelah model siap.
4. Nilai setiap lagu: **0 tidak relevan, 1 sedikit terkait, 2 relevan, 3 sangat relevan/tepat**. Lirik dan nilai audio tersedia untuk diperiksa. Skor dan asal metode disembunyikan; urutan kandidat diacak deterministik. Hint sumber bukan label. Catatan tersimpan saat memilih nilai.
5. Ekspor query/qrels setelah definisi disetujui dan seluruh pool telah dinilai. Minimal satu lagu dengan label >=2 diperlukan; query tanpa lagu relevan harus diaudit. Perbedaan nilai antarpenilai memblokir ekspor dan harus diselesaikan manusia dengan meninjau/memperbarui penilaian, bukan dirata-ratakan otomatis. Ekspor per query melalui UI atau seluruh split lewat CLI.

Penilaian tersimpan di `artifacts/benchmark/reviews.sqlite3`; pool beserta ranking asal dan konfigurasi berada di `artifacts/benchmark/pool.json`. Menutup/muat ulang halaman tidak menghapus nilai. Ini penyimpanan lokal proyek, bukan sinkronisasi cloud atau sistem akun. Simpan salinan direktori ini jika memindahkan proyek. Perubahan corpus atau definisi file query membuat identitas dataset baru sehingga label/pool versi lama tidak digunakan untuk makna baru; data lama tetap tersimpan.

Draft memiliki 32 query per kategori: judul, artis, lirik, semantik, audio; masing-masing 8 dev dan 24 test. Query judul/artis/lirik dari keluarga artis yang sama berbagi `group_id`, dan parafrasa semantik/audio berbagi grup. Pilihan draft berasal dari corpus dan template penulis; penilaian manusia masih diperlukan untuk cakupan, keseimbangan, ambiguitas, serta kecocokan lirik–rekaman. Jangan menganggap draft sebagai representasi final semua perilaku pengguna.

```powershell
# Hanya jika draft belum ada; perintah tidak menimpa koreksi manusia.
.\.venv\Scripts\python.exe -m music_ir benchmark-draft
# Pilot lima query, kedalaman 5 per metode; tidak membuat nilai relevansi.
.\.venv\Scripts\python.exe -m music_ir benchmark-pool --query-id title-001 artist-001 lyrics-001 semantic-001 audio-001 --depth 5
# Setelah pilot tersebut ditinjau dan selesai dinilai manusia:
.\.venv\Scripts\python.exe -m music_ir benchmark-export --split dev --query-id title-001 artist-001 lyrics-001 semantic-001 audio-001
.\.venv\Scripts\python.exe -m music_ir evaluate --queries artifacts/benchmark/export/queries.jsonl --qrels artifacts/benchmark/export/qrels.csv --modes E1 E2 E3 E4 E5 AUTO --split dev
# Untuk seluruh development set, siapkan pool --split dev dan ekspor tanpa --query-id.
```

Mulai dari pilot yang belum digunakan untuk menyimpulkan efektivitas umum, lalu perluas penilaian ke seluruh draft. Gunakan dev untuk tuning dan bekukan aturan/config sebelum mengukur test. Aplikasi tidak membuat label, memalsukan skor benchmark, atau melatih encoder dari penilaian ini secara otomatis. **Pelatihan ulang belum diperlukan** untuk jejak keputusan, anotasi, evaluasi, atau pencarian bobot. Fine-tuning baru layak diuji jika data berlabel dan analisis kegagalan menunjukkan kebutuhan, menggunakan data yang izinnya mendukung penggunaan ML.

## Posisi Spotify Web API

Ditinjau pada 20 November 2026: [Search for Item](https://developer.spotify.com/documentation/web-api/reference/search) menyediakan pencarian katalog dengan filter seperti judul, artis, album, tahun, dan genre. Respons tidak menyediakan teks lirik atau endpoint yang menjamin pencarian tema/lirik. Ini cocok untuk pencarian katalog tambahan yang ditampilkan dan diatribusikan sebagai hasil Spotify, terpisah dari corpus/benchmark lokal.

[Spotify Developer Policy](https://developer.spotify.com/policy) melarang konten Spotify digunakan untuk melatih **atau dimasukkan ke** model AI/ML. Karena itu, data baru dari API tidak boleh otomatis diteruskan ke BGE-M3, reranker AI, atau pipeline fine-tuning. Rekomendasi arsitektur: hasil metadata Spotify ditampilkan melalui jalur katalog terpisah, dengan tautan Spotify dan credential pada backend; hasil tersebut tidak dimasukkan ke embedding atau pool benchmark kita. Integrasi Web API berautentikasi belum diaktifkan oleh perubahan ini.

[Perubahan Development Mode Februari 2026](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) mewajibkan pemilik app memiliki Premium, membatasi penambahan app/pengguna, dan menurunkan maksimum search menjadi 10 hasil per request. Periksa akses endpoint yang diberikan ke app sebelum mengandalkan audio features/recommendations. Integrasi katalog tidak menggantikan sumber lirik berizin dan evaluasi relevansi manusia.

## Pengujian

```powershell
.\run.ps1 test
.\run.ps1 build
.\run.ps1 test-ui
```

Pengujian frontend memakai Playwright dengan Chrome lokal dan respons API fixture: navigasi genre, pencarian `AUTO`, detail/lirik, persistensi favorit/playlist, penghapusan lagu, kegagalan API, pemilihan eksperimen, embed Spotify, serta layout mobile. Fixture memeriksa perilaku UI; kualitas model tetap diukur melalui qrels.

Dengan backend dan frontend aktif, jalankan `npm --prefix frontend run smoke` untuk pemeriksaan browser terhadap API/model asli. Script menguji query judul, makna, dan batas tempo, lalu menyimpan tangkapan layar desktop/pencarian/mobile ke `artifacts/ui/`. Build menjalankan pemeriksaan TypeScript terlebih dahulu.

Pengujian mencakup Unicode, kolaborasi artis, metadata tanpa lirik, deduplikasi, kesamaan kandidat E3/E4, kesamaan E4/E5 tanpa intent audio, batas numerik termasuk ambang tepat, beberapa filter, nilai hilang, negasi, hasil kosong, metrik ranking, dan validasi API. Fixture semantik pada unit test hanya untuk memeriksa algoritma; kualitas BGE-M3 harus dinilai dengan qrels manusia. Koneksi Elasticsearch harus diuji setelah server tersedia.

Untuk menyertakan lima pengujian integrasi pada indeks Elasticsearch yang sudah disiapkan:

```powershell
$env:MUSIC_IR_TEST_ES = '1'
.\run.ps1 test
```

Checkpoint diuji dengan simulasi interupsi dan resume; potongan yang sudah tersimpan tidak dihitung ulang. Konfigurasi tuning diuji agar hanya memakai development set dan tidak menimpa `config.json` utama.

## Langkah proyek berikutnya

Perbaikan berdasarkan contoh pengguna: `make the stars look like there not shining`, termasuk versi berawalan `lirik`, sekarang menempatkan **Just the Way You Are — Bruno Mars** pada urutan pertama (sebelumnya keenam). Sumber memuat kontraksi yang berbeda dari ingatan query; pencocokan umum jendela token menanganinya tanpa aturan khusus judul/artis. `lights will guide you home` juga menempatkan **Fix You** pertama setelah prioritas frasa diterapkan. Pemeriksaan API dan UI asli serta tes regresi corpus memverifikasi kasus tersebut, termasuk fallback tanpa encoder. `lagu happy` memakai jalur tema; kualitas suasana hati masih memerlukan penilaian manusia dan tidak disimpulkan hanya dari nama lagu. Hasil sebelum/sesudah tersedia di `artifacts/diagnostics/user-query-before.json` dan `user-query-after.json`.

Smoke test lokal pada 16 November 2026 memastikan BGE-M3 dapat dimuat dari cache dan dipakai oleh `AUTO` pada 1.437 lagu. Judul `Die With A Smile` muncul pertama; query `Bruno Mars dengan tempo > 120 BPM` menghasilkan tiga hasil teratas dengan artis tersebut dan tempo yang memenuhi batas. Ini pemeriksaan fungsi, bukan pengukuran efektivitas.

Kasus yang perlu diaudit: query `a song about missing someone after a breakup` menempatkan `A Bar Song (Tipsy)` pertama pada E2 dan E4/AUTO. Dense retrieval murni menempatkan `Maps`, `Be Alright`, dan `For the First Time` di tiga teratas; E3 memberikan urutan berbeda lagi. Pada E4, hasil pertama memperoleh fitur BM25 ternormalisasi 1 dan overlap judul 0,222. Kasus ini menunjukkan bahwa kontribusi kata generik dan bobot reranking perlu diperiksa pada query tematik; belum ada qrels untuk menyimpulkan metode mana yang paling relevan.

1. **Validasi semantic search pada corpus nyata.** Periksa status embedding dan jalankan query Indonesia/Inggris, judul/artis persis, potongan lirik, serta query gabungan audio. Bandingkan hasil dengan lirik; embedding yang selesai dibangun belum membuktikan relevansi.
2. **Tinjau draft dan lakukan penilaian manusia.** Infrastruktur jejak keputusan, 160 draft query, pool pilot, penyimpanan penilaian, dan ekspor qrels sudah tersedia. Tinjau definisi/cakupan, audit pasangan lagu–lirik, dan nilai kandidat di halaman Benchmark. Label manusia tetap menjadi pekerjaan berikutnya sebelum mengklaim efektivitas atau melakukan tuning.
3. **Tune dan ukur pipeline gabungan.** Pilih bobot pada dev, bekukan config, lalu evaluasi E1–E5 dan AUTO pada test dengan backend Elasticsearch. Periksa apakah semantik/reranking meningkatkan nDCG@10, MRR@10, Recall@100, serta berapa biaya latensinya. AUTO memiliki kebijakan lirik/tema tambahan dan perlu dinilai tersendiri; jangan memasukkan fallback sebagai run E5/AUTO penuh yang sukses. Tuner bobot E1–E5 tidak memilih ambang/pola aturan AUTO.
4. **Perbaiki berdasarkan analisis kegagalan.** Jika tema lirik belum tertangkap, uji representasi/potongan lirik dan kandidat terlebih dahulu. Cross-encoder atau sparse BGE-M3 dapat diuji sebagai eksperimen terpisah setelah baseline terukur. Tunda penggantian model besar atau pelatihan ulang sampai ada bukti dari qrels.

## Struktur

`music_ir/` memuat persiapan data, retrieval, parser audio, reranking, CLI, evaluasi, katalog, dan API. `frontend/` memuat React/TypeScript, CSS, aset lokal, konfigurasi Vite, dan pengujian Playwright. `tests/` memuat pengujian backend. `scripts/fetch_artwork.py` menyiapkan cache sampul opsional. `config.json` menyimpan parameter eksperimen. `compose.yaml` menyiapkan Elasticsearch lokal. Dataset hasil pengolahan, environment, model, node_modules, dan hasil build tidak dimasukkan ke version control.
