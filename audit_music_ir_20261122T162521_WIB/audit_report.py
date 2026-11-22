"""Compose factual report entirely from collected evidence and inspected source."""
import json,csv,sys,re,collections,platform
from datetime import datetime,timezone,timedelta
from pathlib import Path
from audit_collect import ROOT,OUT,E,write,sha,run

def read(name):return json.loads((E/name).read_text(encoding='utf-8'))
def cell(x):return str(x).replace('|','\\|').replace('\n',' ')
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',*['| '+' | '.join(cell(x) for x in row)+' |' for row in rows]])
def compose():
    s=read('snapshot_before.json');d=read('data_audit.json');emb=read('embedding_audit.json');rt=read('runtime.json');eng=read('runtime_engine.json')['after'];bm=read('benchmark_audit.json')
    cases=read('case_results.json');scores=read('score_verification.json');ind=read('score_independent_examples.json');lat=read('latency_summary.json');anno=read('annotation_manifest.json');dep=read('dependency_comparison.json')
    tok=read('tokenization_audit.json');cold=read('model_load_observation.json');indep=read('query_independence.json');config=json.loads((OUT/'config_snapshot.json').read_text(encoding='utf-8'))
    checks=read('case_additional_assertions.json');fail=[c for c in cases if c['functional_status']!='pass'];ended=datetime.now(timezone(timedelta(hours=7))).isoformat()
    statuses={'executed':'terverifikasi lewat eksekusi saat audit','code_only':'ditemukan dalam kode tetapi belum dijalankan','historical_only':'hanya tercatat pada artefak historis','not_verified':'belum tersedia/tidak dapat diverifikasi'}
    claims=[
      ('CLM-001','Snapshot Git, hash dan lingkungan',s['commit'],'executed','snapshot_before.json','audit_collect.py snapshot','music_ir/engine.py:18'),
      ('CLM-002','UI mengirim AUTO dan top_k 30',{'mode':'AUTO','top_k':30},'executed','ui_live_responses.json','audit_verify.py ui','frontend/src/App.tsx:97'),
      ('CLM-003','Corpus aktif dan audit sumber',{'rows':d['source_rows'],'unique_tracks':d['active_documents'],'lyrics':d['lyrics_available']},'executed','data_audit.json','audit_collect.py data; prepare ke scratch audit','music_ir/data.py:29'),
      ('CLM-004','Model dokumen dan runtime encoder',{'model':'BAAI/bge-m3','shape':emb['matrix_shape'],'device':eng['device'],'dtype':eng['dtype']},'executed','runtime_engine.json','audit_search.py latency; GET /_audit/runtime','music_ir/semantic.py:130'),
      ('CLM-005','Backend yang dipakai adalah LocalBM25',eng['backend_class'],'executed','runtime_engine.json','GET /_audit/runtime','music_ir/engine.py:56'),
      ('CLM-006','E3/E4 identik kandidat pada empat probe',read('mode_comparisons.json'),'executed','mode_comparisons.json','audit_search.py cases','music_ir/engine.py:200'),
      ('CLM-007','Jumlah kontribusi skor sesuai skor akhir',{'checks':len(scores['checks']),'all_passed':scores['all_passed']},'executed','score_verification.json','audit_search.py cases; audit_verify.py fixtures','music_ir/diagnostics.py:20'),
      ('CLM-008','Tes backend tersedia',{'run':93,'passed':88,'failed':0,'skipped':5},'executed','backend_tests.json','python -m unittest discover -s tests -v','tests/test_search.py'),
      ('CLM-009','Build frontend dan tes UI',{'build_exit':read('frontend_build.json')['exit_code'],'ui_passed':15},'executed','frontend_tests.json','npm run build; npm test -- --output=<audit>','frontend/playwright.config.ts'),
      ('CLM-010','Kasus HTTP audit',{'cases':len(cases),'failures':len(fail)},'executed','case_results.json','audit_search.py plan; audit_search.py cases','music_ir/api.py:114'),
      ('CLM-011','Label manusia belum tersedia',{'draft_queries':160,'reviews':0,'judgments':0},'executed','benchmark_audit.json','read-only SQLite active dataset; actual query/qrels inspection','music_ir/benchmark.py:182'),
      ('CLM-012','Efektivitas retrieval belum dapat diukur',None,'not_verified','retrieval_metrics_summary.json','read_benchmark rejects real draft data','music_ir/evaluate.py:26'),
      ('CLM-013','Distribusi latensi subset tetap',{'warmups':60,'measured':180,'errors':0},'executed','latency_summary.json','audit_checks.py latency','music_ir/engine.py:340'),
      ('CLM-014','Durasi pembentukan embedding corpus',emb['metadata']['offline_seconds'],'historical_only','embedding_audit.json','read artifacts/semantic/metadata.json; embedding not rebuilt','music_ir/semantic.py:122'),
      ('CLM-015','Evaluator tidak menyimpan status incomplete saat error',True,'executed','evaluator_failure_reproduction.json','audit_verify.py fixtures; failure on call13','music_ir/evaluate.py:75'),
      ('CLM-016','Pool anonim siap ditinjau manusia',{'queries':10,'pairs':anno['annotation_rows']},'executed','annotation_manifest.json','audit_checks.py annotation','audit_search.py annotation'),
      ('CLM-017','Fallback AUTO pada gangguan semantik',{'fixture_tests':'passed','live_fault_injection':False},'executed','backend_tests.json','test_missing_semantic_* and test_semantic_failures_fallback_only_in_auto','music_ir/engine.py:143'),
      ('CLM-018','Adapter Elasticsearch tersedia, runtime belum diuji',None,'code_only','source/music_ir/lexical.py','read source; service connection refused; five integration tests skipped','music_ir/lexical.py:44'),
      ('CLM-019','Screenshot aplikasi nyata',4,'executed','live_ui.json','node audit_ui.cjs; Chrome headless; no mock routes','frontend/src/DiagnosticsPanel.tsx'),
      ('CLM-020','Riwayat tuning berbasis label',None,'not_verified','historical_reference.json','search *trials* in artifacts; inspect empty qrels','music_ir/tune.py:27'),
      ('CLM-021','Panjang token corpus dan kebutuhan chunking',{'max_content_tokens':tok['content_tokens_max'],'over_8192':tok['would_chunk_count']},'executed','tokenization_audit.json','audit_tokenizer.py; local pinned tokenizer','music_ir/semantic.py:73'),
      ('CLM-022','Struktur split dan paparan regresi',indep,'executed','query_independence.json','audit_supplement.py; compare actual query definitions','music_ir/benchmark.py:29')]
    ledger=[{'claim_id':cid,'claim':claim,'value':value,'verification_status':status,'status_label':statuses[status],'code_reference':ref,
             'evidence_file':'evidence/'+file,'procedure':proc,'snapshot_commit':s['commit'],'reason':'Lihat batas kesimpulan pada laporan' if status!='executed' else None}
            for cid,claim,value,status,file,proc,ref in claims]
    write(E/'claims.json',ledger)
    # Compact supplemental data tables; every item retains source/installed distinction.
    numrows=[]
    for k,v in d['numeric'].items():
        unit='BPM menurut kontrak parser' if k=='tempo' else 'ms menurut nama field' if k=='duration_ms' else 'skala dataset; tidak ditransformasi' if k in ['loudness','key','mode','time_signature','track_popularity'] else 'nilai dataset 0–1'
        usage='filter/preferensi/skor' if k in ['tempo','energy','valence','danceability','acousticness'] else 'tie-break katalog/audio AUTO' if k=='track_popularity' else 'tampilan durasi' if k=='duration_ms' else 'disimpan, tidak masuk ranking aktif'
        numrows.append([k,'float',v['missing'],f"{v['min']} … {v['max']}",unit,usage])
    version_rows=[]
    for name in ['numpy','pandas','pyarrow','fastapi','uvicorn','sentence-transformers','torch','transformers','tokenizers','huggingface-hub','filelock','httpx']:
        actual=next((v for k,v in rt['packages_installed'].items() if k.lower()==name),None)
        locked=next((r['locked'] for r in dep['backend_lock_vs_installed'] if r['name']==name),None)
        declared={'numpy':'>=1.26,<3','pandas':'>=2.2,<4','pyarrow':'>=15','fastapi':'>=0.115,<1','uvicorn':'>=0.30,<1','sentence-transformers':'>=3,<6 (semantic)','filelock':'>=3,<5 (semantic)','httpx':'>=0.27,<1 (test)'}.get(name,'transitif; tidak dideklarasikan langsung')
        version_rows.append([name,actual,locked,declared])
    stage_rows=[
      ['Offline: gabung','prepare','CSV bersnapshot','Group ID; first nonempty; union playlist; numerik float/None','JSON/Parquet + audit','Saat prepare; audit direplikasi ke scratch','data.py:29; CLM-003'],
      ['Offline: embedding','_build_embeddings','Judul, artis, lirik','Encoder pretrained; chunk >8192; mean dan normalisasi','vectors.npy + metadata','Build historis; tokenisasi diperiksa ulang','semantic.py:55; CLM-004/014/021'],
      ['Startup','SearchEngine.__init__','Corpus JSON/config','BM25 3 field+combined; metadata index; cek matriks/cache identity','Engine siap; model lazy','Setiap proses API','engine.py:51; CLM-004/005'],
      ['UI/API','api + SearchRequest','query, mode, top_k, mood_basis','Vite /api → FastAPI; validasi; handler sync','search(query,mode,...)','Semua pencarian','App.tsx:97; api.py:114; CLM-002'],
      ['Rencana query','plan_query/parse/apply_mood','Teks dan metadata corpus','NFKC; lindungi kutipan; parser audio; katalog; tema/mood','Intent, QueryPlan, constraints/preferences','Plan katalog/lirik/tema hanya AUTO; parse audio semua mode','query.py:45; audio.py:23; engine.py:83; trace'],
      ['Semantik','warmup/scores','semantic_text dan vektor dokumen','Load model lokal bila perlu; normalized query; dot seluruh corpus','cosine N elemen','Teks nonkatalog AUTO/E3–E5; gagal AUTO → fallback','semantic.py:149; engine.py:137; CLM-004/017'],
      ['Lexical/lirik','LocalBM25.scores/LyricIndex.match','intent.text','BM25; bukti jendela lirik independen kondisional','BM25 N elemen + match dict','Lexical jika teks nonkatalog; match lirik AUTO kecuali semantic/artist/genre','lexical.py:28; lyrics.py:90; CLM-005/010'],
      ['Mask/skor audio','audio_scores','Seluruh docs, Intent','Irisan batas; sort distribusi per query untuk persentil; metadata mask','mask + audio N elemen','Dihitung setiap search; hanya dipakai AUTO/E5 saat intent aktif','audio.py:66; engine.py:163; trace'],
      ['Kandidat','ranked dan sumber','BM25/cosine/match/audio/metadata','AUTO mask sebelum top; tiap sumber top100 kecuali list lirik; audio seluruh corpus','Daftar sumber berurutan','Tergantung jalur; bukan semua sumber selalu aktif','engine.py:166; CLM-006/010'],
      ['Union/fusion','search loop RRF','Daftar sumber','Set indeks untuk dedup; rank1; 1/(60+r); postfilter audio','Union; lalu <=100 kandidat','E1/E2 mengambil list BM25; lainnya RRF; reservasi lirik AUTO','engine.py:190; CLM-007'],
      ['Bagian tema','passage_scores','24 kandidat, semantic_query','Chunk160 kata overlap40; cache SQLite; max/top3, contrast jika profil','Bukti bagian dan ranking cosine','AUTO semantic + semantik tersedia; clip24 sebelum passage','engine.py:217; passages.py:45; trace REG-03/05/08'],
      ['Skor akhir','reranking','Fitur/metadata/tema/audio/bonus','Rumus sesuai jalur; tie score lalu popularity atau RRF lalu ID','Kandidat terurut','AUTO/E4/E5; E1/E2 BM25; E3 RRF','engine.py:237; CLM-007'],
      ['Tampilan','format hasil/diagnostics','Kandidat dan top_k','Utama/serupa berbagi kuota; alasan; snippet; latency sebelum diagnostics','JSON results, related_results, optional trace','Semua mode; pemisahan khusus lirik/tema AUTO','engine.py:277; diagnostics.py:20; CLM-002/019']]
    mode_rows=[
      ['AUTO','API/UI default; config aktif','Katalog ATAU teks BM25+cosine; lirik/tema kondisional; audio bila aktif','Metadata/audio sebelum top; audio juga sesudah union','RRF kandidat, bukan skor akhir','Fitur, katalog, atau tema+bagian; bonus lirik','Mood, reservasi lirik, populer untuk tie tertentu, fallback','HTTP nyata + UI; CLM-002/010'],
      ['E1','search(mode=E1)','BM25 satu teks combined; audio tidak dipakai','Tidak ada filter audio aktif','Tidak untuk urutan final','Tidak','Query audio tetap diparse/dihapus; pure audio kosong','HTTP nyata'],
      ['E2','search(mode=E2)','Jumlah BM25 field berbobot 3:2:1','Tidak ada filter audio aktif','Tidak untuk urutan final','Tidak','Tie ID; tanpa aturan AUTO','HTTP nyata'],
      ['E3','search(mode=E3)','BM25 field + cosine dokumen','Tidak ada filter audio aktif','RRF dua sumber; top100','Tidak','Tanpa fallback; tie ID','HTTP nyata'],
      ['E4','search(mode=E4)','Sama E3','Tidak ada filter audio aktif','Sama E3','Lima fitur berbobot; tanpa bonus AUTO','Tie RRF lalu ID; tanpa fallback','HTTP nyata'],
      ['E5','search(mode=E5)','Sama E4 + audio corpus penuh jika intent aktif','Sesudah union, sebelum cap akhir','Teks+semantik+audio','Teks/audio weight0.5 jika mixed; audio weight1 jika pure','Tanpa katalog/lirik/tema/mood AUTO; tie RRF lalu ID','HTTP nyata']]
    case_rows=[]
    definitions={json.loads(l)['case_id']:json.loads(l) for l in (E/'cases.jsonl').read_text(encoding='utf-8').splitlines()}
    for c in cases:
        p=definitions[c['case_id']];label='pengembangan/regresi' if c['case_id'].startswith('REG-') or c['case_id'].startswith('MODE-') else 'probe fungsi audit'
        result=f"HTTP {c['status']}; {c['query_type']}; utama {c['primary_count']}, serupa {c['related_count']}"
        if c['case_id'].startswith('MODE-'):result+=f"; kandidat pada trace"
        case_rows.append([c['case_id'],p['query'] if p['query'] else '(string kosong)',label,p['expected'],p['mode']+'/local',result,c['functional_status'],'CLM-010; search_traces.jsonl case_id'])
    latency_rows=[]
    for m,v in lat['summary'].items():
        h=v['http_ms'];g=v['engine_ms'];latency_rows.append([m,h['n'],f"{h['mean']:.2f}",f"{h['median']:.2f}",f"{h['p95']:.2f}",f"{g['mean']:.2f}",f"{g['median']:.2f}",f"{g['p95']:.2f}",v['errors']])
    score_rows=[]
    for c in ind['checks']:
        terms=' + '.join(f"{k}={v:.12g}" for k,v in c['contributions'].items())
        score_rows.append([c['case_id'],c['track_id'],terms,f"{c['expected_score_independent']:.12g}",f"{c['actual_score']:.12g}",f"{c['absolute_error']:.3g}"])
    mermaid=(OUT/'pipeline_actual.mmd').read_text(encoding='utf-8')
    main=f'''# FAKTA PROYEK MUSIC IR

Audit dimulai **22 November 2026, 16:25:21 WIB (Asia/Jakarta)**. Paket disusun pada {ended}. Snapshot Git `{s['commit']}`; root `{ROOT}`. Ini paket fakta untuk diperiksa sebelum penyusunan ulang laporan UAS, bukan Bab 1–5.

Empat status digunakan secara terpisah: **EKSEKUSI** (terverifikasi saat audit), **KODE** (ada tetapi belum dijalankan pada jalur terkait), **HISTORIS** (artefak lama), **BELUM TERVERIFIKASI** (data/akses tidak cukup). Ledger [claims.json](evidence/claims.json) memuat status, prosedur, referensi kode, snapshot, dan file bukti setiap klaim utama. Referensi `music_ir/...:baris` merujuk salinan di `evidence/source/`.

## 1. Ringkasan proyek dalam bahasa sederhana

Music IR melayani pengguna yang ingin menemukan lagu dalam koleksi tetap berdasarkan judul, artis/kolaborasi, potongan lirik, tema/suasana, label genre playlist, atau kondisi angka audio. Input berupa teks dan pilihan mode/mood. Output berupa daftar lagu dengan ID, judul, artis, album, genre playlist, angka audio, skor, cuplikan, dan alasan kecocokan. Jalur lirik/tema tertentu memisahkan hasil utama dari hasil serupa; keduanya berbagi batas hasil. [CLM-002/010/019]

Fitur audio berarti **angka dalam dataset**, misalnya tempo, energy, valence, danceability, dan acousticness. Pipeline pencarian tidak mendengarkan rekaman, menerima unggahan audio, atau mengekstrak ciri sinyal. Spotify embed di UI merupakan pemutaran eksternal; ketersediaan audio di Spotify tidak diuji sebagai bagian retrieval.

BM25 mencari kecocokan kata. Embedding BGE-M3 merepresentasikan teks dan mencari kedekatan makna melalui cosine. Aturan kecil mengenali metadata, kutipan, suasana dan batas numerik; RRF menggabungkan kandidat, kemudian reranking menggunakan fitur/skor sesuai jalur. Tidak ditemukan LLM generatif, cross-encoder, pelatihan ulang encoder, atau model rekomendasi personal di jalur aktif yang ditelusuri. Favorit/playlist menggunakan penyimpanan browser, bukan model personalisasi. Agent coding yang mengembangkan program bukan algoritme runtime aplikasi. [CLM-002/004/005; kode engine.py, semantic.py, frontend/src/lib.ts]

## 2. Snapshot kode, konfigurasi aktif, dan lingkungan runtime

Git awal bersih sebelum folder audit dibuat. Hash SHA-256 berkas awal tersedia di [snapshot_before.json](evidence/snapshot_before.json); pemeriksaan akhir ada di [snapshot_after.json](evidence/snapshot_after.json). Tidak dilakukan perbaikan aplikasi, tuning, penggantian corpus, atau perubahan parameter. Build frontend dan cache normal aplikasi dapat menghasilkan artefak; itu dibedakan dari perubahan kode/data. [CLM-001]

Konfigurasi efektif diamati dari instance engine di proses API dan cocok dengan `load_config()` serta file konfigurasi. Lihat [config_snapshot.json](config_snapshot.json) dan [runtime_engine.json](evidence/runtime_engine.json). Backend runtime **{eng['backend_class']} / {eng['backend']}**, bukan Elasticsearch. Variabel proses `MUSIC_IR_BACKEND`, `MUSIC_IR_API`, dan `MUSIC_IR_TEST_ES` tidak disetel pada snapshot. Probe awal port8000/8501/9200 menolak koneksi; API/UI kemudian dijalankan untuk audit, tanpa mengunduh atau membangun Elasticsearch. [CLM-004/005/018]

Parameter efektif: field_weights=`[3,2,1]`; text_weights=`[0.25,0.25,0.25,0.25,0]`; audio_weight=`0.5`; candidate_limit=`100`; RRF constant=`60`; BM25 k1=`1.2`, b=`0.75`; tema candidate_limit=`24`, document_weight=`0.4`; mood default=`both`, sad valence≤`0.5` dan energy≤`0.65`, happy valence≥`0.5`; tuned=`false`. Trace masing-masing request juga menyertakan config dan identitas corpus/implementasi.

Command launcher repository: `.\\run.ps1 api` menjalankan `.venv\\Scripts\\python.exe -m uvicorn music_ir.api:app --host 127.0.0.1 --port 8000 --reload --reload-dir music_ir`; UI `.\\run.ps1 ui` → `npm --prefix frontend run dev` (Vite127.0.0.1:8501). Build memakai `npm run build` dari frontend; evaluasi CLI tersedia melalui `python -m music_ir evaluate --queries <approved.jsonl> --qrels <human.csv> --output <run> --modes E1 E2 E3 E4 E5 AUTO --backend local --split test --repeats 5`. Command terakhir ini **tidak** dijalankan pada data penelitian karena belum ada qrels layak. Validasi input evaluasi nyata tetap dijalankan dan penolakannya disimpan di [evaluation_eligibility_check.json](evidence/evaluation_eligibility_check.json).

Audit API pertama memakai command uvicorn yang sama tanpa autoreload. Untuk mengamati device/dtype/config dari proses yang benar-benar melayani request, proses kedua membungkus app asli lewat `audit_live_api.py` dengan endpoint baca `/_audit/runtime`; fungsi search dan parameter tetap asli. Command/PID/log ada di `api_service.json`, `api_observed_service.json`, dan file log pasangannya. UI nyata memanggil `/api/search`, diteruskan Vite ke `/search`. Default UI=`AUTO`, top_k UI=`30`; default schema API top_k=`10`. Perbedaan ini dikonfirmasi dari payload browser. [CLM-002]

Engine berjalan sebagai Python native **{rt['platform']}**, executable `{rt['executable']}`, bukan WSL/container. CPU teramati `{rt.get('cpu_name')}`, logical CPU={rt['logical_cpus']}; RAM yang dilaporkan OS={rt['ram_total_bytes']:,} byte ({rt['ram_total_bytes']/1024**3:.2f} GiB). Saat snapshot, RAM tersedia {rt['ram_available_bytes_at_snapshot']:,} byte; beban mesin lain tidak dikontrol. Jumlah core fisik serta inventaris GPU/VRAM hardware **null**: akses CIM ditolak. Torch build `{rt['torch']['version']}` bersifat CPU, CUDA tidak tersedia di runtime ini; ini tidak membuktikan mesin tidak memiliki GPU. Inferensi nyata device=`{eng['device']}`, dtype=`{eng['dtype']}`, threads Torch=`{eng['torch_threads']}`, batas encoder=`{eng['max_seq_length']}`. [CLM-001/004]

Python `{platform.python_version()}`, Node `{dep['node']}`, npm `{dep['npm']}`; paket proyek `music-ir` versi0.2.0, frontend `music-ir-ui`1.0.0. Versi terpasang dibaca dari lingkungan, versi lock dari lockfile, dan rentang deklarasi dari pyproject/package.json:

{table(['Paket backend/model','Terpasang','Lockfile','Deklarasi'],version_rows)}

{table(['Paket frontend','Terpasang','Lockfile','Deklarasi'],[[r['name'],r['installed'],r['lockfile'],r['declared']] for r in dep['frontend']])}

Rincian seluruh paket dan kecocokan lock ada di [runtime.json](evidence/runtime.json), [dependency_comparison.json](evidence/dependency_comparison.json). Lockfile bukan bukti paket terpasang; kedua sumber dibaca terpisah. Berkas `.env`, token, credential, weights, dan dependency trees tidak disertakan.

## 3. Dataset serta hasil audit aktual

Sumber yang cocok dengan SHA audit persiapan adalah `{d['source_file']}`. SHA sumber=`{d['source_sha256']}`; identitas corpus terkanonisasi=`{d['active_corpus_identity']}`. SHA byte file corpus berbeda dari hash logis corpus; keduanya ada pada snapshot. Sumber berisi **{d['source_rows']} baris × {d['source_columns']} kolom**, **{d['source_unique_ids']} ID unik**. ID kosong/tidak sesuai pola22karakter alfanumerik: {d['missing_id_rows']}/{d['non_spotify_format_id_rows']}. Pola valid bukan verifikasi rekaman di layanan eksternal. [CLM-003]

Duplikasi baris identik: **0** kemunculan tambahan, 0 kelompok. Duplikasi ID: **249** kemunculan tambahan dari **213** kelompok ID berulang. Jadi pengurangan baris menjadi lagu unik bukan berarti 249 baris identik. Penggabungan `prepare()` diulangi ke direktori scratch audit dan seluruh objek dokumen cocok dengan corpus aktif. Field nonplaylist memilih nilai pertama yang tidak kosong, konflik dicatat; field playlist (`playlist_id/name/genre/subgenre`) di-union, dinormalisasi dan diurutkan. Konversi numerik tak valid/nonfinite menjadi None. Konflik nonplaylist terhitung **0** pada sumber ini; dokumen akhir **1437**. Corpus asli tidak ditulis ulang.

Ada **1404/1437 lagu unik dengan lirik ({1404/1437*100:.2f}%)**, 33 tanpa lirik, dan 2 lirik nonkosong dengan panjang setelah strip <100 karakter. ID lirik pendek dan audit lengkap tersedia di [data_audit.json](evidence/data_audit.json). Angka historis1.686/1.437/1.404 cocok dengan hitungan ulang; angka tersebut tidak hanya disalin dari README. Semua `lyrics_match_status` pada corpus tetap `unknown`; kualitas pasangan lirik–rekaman belum dinilai.

Field judul/artis/lirik dipakai untuk retrieval teks. Album/release date/duration/ID digunakan dalam keluaran. Label genre berasal dari **playlist_genre**, dapat lebih dari satu per lagu; **{d['tracks_multiple_genres']} lagu** memiliki beberapa label. Jumlah label per genre tersedia di JSON dan tidak boleh dijumlahkan sebagai jumlah lagu unik. Popularitas CSV dipakai untuk tie-break jalur tertentu, bukan popularitas terkini. Field playlist lain dipertahankan pada corpus, bukan otomatis menjadi field BM25.

{table(['Fitur','Tipe aktif','Hilang','Rentang aktual','Satuan/kontrak','Pemakaian'],numrows)}

Rentang angka dihitung ulang; satuan audio selain kontrak parser/nama field tidak memiliki data dictionary asal yang dapat dibuktikan. Tidak ditemukan bukti metode pengambilan metadata/lirik, tanggal pengambilan, verifikasi lisensi sumber lirik, atau validasi pasangan tiap rekaman. Link/URI Spotify dan nama file saja tidak membuktikan asal atau mutu lirik. Audit hanya menetapkan lineage berkas dari SHA ke corpus hasil merge.

## 4. Pipeline offline dan online, diagram, serta tabel tahapan

Alur ringkas: corpus disiapkan dan embedding dokumen tersedia sebelumnya; startup membuat indeks lokal; request UI diparse menjadi intent; mode memilih sumber kandidat yang sesuai; kandidat digabung/difilter; skor dan tie-break ditentukan; UI menampilkan hasil serta alasan. Tahap dalam satu `SearchEngine.search` berjalan **berurutan**, bukan retrieval multijalur konkuren. Model memakai RLock; server dapat menangani request melalui handler sync/threadpool, tetapi itu tidak membuat sumber satu query berjalan paralel.

{table(['Tahap','Fungsi/tugas','Input','Proses/metode aktual','Output','Aktif pada kondisi apa','Lokasi kode dan bukti run'],stage_rows)}

BM25 lokal dibangun saat constructor/startup, tidak dibaca dari indeks Lucene offline. Distribusi fitur audio dihitung/disortir di `audio_scores()` setiap request preferensi, bukan distribusi persisten offline. Pencarian semantik terjadi sebelum BM25 dalam jalur online; kondisi mask diberlakukan saat memilih daftar sumber AUTO, bukan sebelum menghitung seluruh vektor cosine/BM25. Ini membedakan urutan komputasi dari ruang kandidat yang diizinkan.

```mermaid
{mermaid.rstrip()}
```

Sumber diagram: [pipeline_actual.mmd](pipeline_actual.mmd). `pipeline_actual.png` **tidak dihasilkan**: probe tidak menemukan Mermaid module/CLI maupun system mmdc/dot; tidak diunduh renderer baru. Diagram di atas dapat dirender oleh pembaca Markdown yang mendukung Mermaid. Tidak ada screenshot UI yang digambar ulang.

Contoh trace: REG-01 `bruno mars` → artist metadata, tanpa cosine; REG-07 `when i see your face` → bukti lirik, BM25+cosine, bonus exact4, utama/serupa terpisah; REG-03 `lagu bermakna cinta` → query expansion romance, 24 kandidat, bagian lirik dan tema pembanding; AUDIO `tempo >120 BPM` → audio seluruh corpus, skor kelayakan1, popularitas untuk tie. Semua berada di [search_traces.jsonl](evidence/search_traces.jsonl) dengan `case_id`, payload, respons, urutan ID, sumber, filter, dan kontribusi.

## 5. Metode, parameter, rumus skor, dan contoh perhitungan yang diverifikasi

**BM25 lokal.** Token=`re.findall(r"\\w+", NFKC(text).casefold())`; tidak ada stemming/stopword list. Token query diperlakukan sebagai set. Untuk setiap field, `idf(t)=ln(1+(N-df(t)+0.5)/(df(t)+0.5))`; skor token=`idf × tf × (k1+1)/(tf+k1×(1-b+b×dl/avgdl))`. avgdl menjadi1 jika rata-rata panjang nol. E1 memakai satu field gabungan judul+artis+lirik. E2–E5/jalur teks AUTO menjumlahkan `3×BM25judul + 2×BM25artis + 1×BM25lirik`; bukan BM25F dengan satu normalisasi panjang bersama. BM25 retrieval hanya memasukkan skor positif. Adapter Elasticsearch memakai standard tokenizer+lowercase dan Lucene BM25 dengan boost field, tetapi **tidak dijalankan**; kesetaraan kedua analyzer tidak diasumsikan. [CLM-005/018; lexical.py:28]

**Semantik dokumen.** Model ID=`BAAI/bge-m3`, revision=`5617a9f61b028005a4858fdac845db406aefb181`; cache lokal untuk revision ini ditemukan dan loader online meminta revision tersebut dengan local_files_only=True. Serialisasi persis `Judul: <track_name>\\nArtis: <track_artist>\\nLirik: <lyrics>`; tanpa genre/audio. Matriks `{emb['matrix_shape']}` berdimensi1024, float32, finite; norm baris min={emb['norm_min']:.10f}, max={emb['norm_max']:.10f}. Hash corpus dan urutan1437ID cocok. Exact search menggunakan `clip(vectors @ normalized_query,-1,1)` atas seluruh corpus; tidak ada indeks ANN. Encoder pretrained digunakan **tanpa pelatihan ulang**; membuat embedding adalah inferensi. [CLM-004]

Batas dokumen8192token termasuk special tokens. Kode untuk dokumen lebih panjang: potongan512token dengan stride448 (overlap64); encode setiap potongan, rata-rata vektor per pemilik, normalisasi lagi. Metadata historis menyebut0dokumen di-chunk. Audit tokenizer pinned atas seluruh1437dokumen menemukan max{tok['content_tokens_max']}token konten +{tok['special_tokens_to_add']}special tokens, dan0melewati batas; ini memverifikasi kebutuhan chunking corpus sekarang, tanpa membangun ulang embedding. Metadata build historis mencatat batch4, CPU, {emb['metadata']['offline_seconds']}detik; durasi itu **HISTORIS**, bukan pengukuran ulang audit. [CLM-014/021]

**Audio.** Batas eksplisit mendukung >,<,≥,≤,= dan negasi operator (termasuk != hasil negasi); tempo nonnegatif dalam BPM, empat fitur lain0–1. Semua batas diiriskan; nilai tidak ada/nonfinite gagal batas, termasuk !=. Jika hanya batas tanpa preferensi, audio score=1 untuk ranking kandidat lolos; itu indikator, bukan peluang relevansi. Preferensi tinggi/rendah eksplisit tersedia untuk tempo/energy; mood audio menambahkan valence/energy secara internal. Untuk nilai v di distribusi seluruh corpus berukuran n, `p=(left(v)+right(v)-1)/(2(n-1))` dengan posisi searchsorted0-based; nilai seri mendapat midrank. Tinggi=p, rendah=1-p; beberapa preferensi dirata-ratakan. Nilai hilang atau distribusi konstan/n≤1 diberi0.5. Distribusi tidak dibatasi hanya dokumen lolos. Jalur audio membuat kandidat independen dari seluruh corpus, bukan sekadar menyaring teks. [audio.py:66; CLM-010/007]

**Fusion.** RRF=`Σ sumber 1/(60+rank)` dengan rank dimulai1. BM25/cosine/metadata/audio umumnya top100; sumber lirik AUTO tidak dipotong100 sebelum union. Union set indeks menghapus duplikasi. AUTO menyeleksi source text/semantic dengan mask audio/metadata sebelum top; AUTO/E5 juga membuang pelanggar audio sesudah union. Kandidat RRF kemudian dipotong100 dengan tie ID. Bukti lirik AUTO dicadangkan: exact dahulu, similarity turun, RRF turun, ID; sisa anggaran diisi kandidat nonmatch. E1/E2 memakai daftar BM25 langsung; E3 memakai RRF akhir. RRF bukan fitur numerik yang dijumlahkan ke skor rerank E4/E5/AUTO, tetapi masih menjadi tie-break pada jalur umum.

**Reranking teks.** Di kandidat akhir, B=(BM25-min)/(max-min), atau0jika span0; C=(cosine+1)/2; T/A adalah max(exact normalized equality, Jaccard set token query vs judul/artis); P=1jika frasa query ≥2token muncul berurutan dalam lirik. `text=0.25B+0.25C+0.25T+0.25A+0P`. Tanpa audio, final=text. Dengan teks+audio pada AUTO/E5, `final=0.5text+0.5audio`; audio murni memakai weight1. Katalog AUTO mengganti text dengan similarity metadata. Tema AUTO mengganti skor fitur umum dengan skor semantik tema. Jadi bobot fitur umum tidak selalu aktif pada setiap query.

**Katalog dan lirik.** Judul exact menggunakan token key. Artis memakai rentang kredit berurutan yang dipisah koma agar kolaborasi/nama berkoma dapat cocok; tidak ada ID anggota artis, sehingga ambiguitas kredit tetap ada. Fuzzy judul multikata: SequenceMatcher ratio≥0.75, ≥3kata unik bersama, ≤1edit kata; pilih similarity terbaik. Bukti lirik exact dapat mengalahkan tebakan judul approximate pada teks tanpa awalan judul. Genre exact mengikuti label playlist. Lirik punya tokenizer apostrof/kontraksi sendiri, berbeda dari BM25: exact perlu≥3token dan≥2unik. Jika exact ada, fuzzy tidak dicari. Fuzzy hanya4–32token dan≥3unik, dukungan≥max(3,ceil(0.6×unik)), maksimal200lagu diperiksa; anggaran1edit token untuk panjang≤6atau2untuk lebih panjang, similarity≥0.76. Biaya substitusi typo karakter/transposisi yang memenuhi syarat pada kata panjang≥4adalah0.35; selain itu edit1. Window dicari di sekitar longest-match anchor, bukan pencarian global edit-distance semua posisi. [metadata.py:30; lyrics.py:90]

Bonus lirik AUTO sesudah skor dasar: exact+4, approximate+2×similarity. Skor exact dapat melebihi1 (batas teoritis skor dasar+bonus dapat mencapai5); bukan probabilitas. Katalog exact dan audio hard-only dapat bernilai1seragam; urutan AUTO untuk kondisi tersebut mengutamakan popularitas CSV lalu ID. Jalur umum rerank memakai skor turun, RRF turun, IDnaik. E1/E2 memakai BM25 turun lalu ID; E3 RRF turun lalu ID. E5 audio hard-only mempertahankan pemilihan/tie berbasis RRF/ID sehingga urutannya berbeda dari AUTO.

**Tema/mood dan cache.** Query bertema/mood diubah oleh aturan eksplisit, misalnya deskripsi happiness/sadness; cinta dan sulit move on memiliki profil pembanding tetap. Maksimal24kandidat tema dinilai lewat bagian lirik160kata dengan overlap40 (stride120); bagian identik didedup di per-dokumen chunk dan vektor dapat digunakan ulang antar-dokumen. Pooling=`0.7×bagian terbaik+0.3×mean top3`; jika profil contrast, nilai bagian ranking=`(cosine tema-max cosine pembanding)/2`, pooling di urutan nilai ranking. Skor akhir tema=`0.4×(cosine dokumen+1)/2 +0.6×(ranking cosine bagian+1)/2` jika ada bukti, jika tidak memakai cosine dokumen saja. Profil moving_on memerlukan loss cue pada **seluruh lirik** agar masuk utama; lainnya dapat masuk serupa. Nilai valence/energy untuk mood adalah proksi yang dapat dipilih lyrics/audio/both, bukan label emosi yang tervalidasi. [query.py:33; passages.py:45; mood.py:7]

Cache dokumen: `artifacts/semantic/vectors.npy`+metadata, diperiksa corpus hash, model/revision, urutan ID, shape, finite, dan norm. Model dimuat lazy ke memori proses. Cache bagian: `passages.sqlite3`; key SHA256 dari nama/revision model, versi `lyric-passages-v1`, separatorNUL, dan teks bagian. Perubahan teks/model membuat keybaru; vektor lama tidak dihapus. Cache miss mengenkode bagian batch4, cache hit menggunakan vektor; query dan tema pembanding tetap dienkode setiap request. Tidak ditemukan response/query-result cache yang mengembalikan ranking lama tanpa pencarian ulang.

**Fallback.** AUTO tanpa semantik siap/berhasil mengirim warning, menonaktifkan fitur cosine dan bobotnya, lalu menormalisasi ulang bobot teks lain (konfigurasi ini menjadi1/3masing-masing untuk B/T/A; P0). Jika semua bobot tersisa0, fallback BM25 dipakai. Katalog/audio murni tidak memerlukan encoder dan bukan degradasi. E3–E5 gagal saat semantik yang dibutuhkan tidak tersedia; E1/E2 tidak membutuhkannya. Kegagalan bagian lirik mempertahankan cosine dokumen, warning dan degraded; kandidat sudah dibatasi24. Gangguan sengaja diuji lewat fixture unit, bukan merusak cache/model produksi. [CLM-017]

**Status parameter.** Nilai yang berjalan konsisten dengan config `tuned=false`. Tidak ditemukan artefak trials tuning dan tidak ada qrels berlabel; tidak ada dasar menyebut bobot optimal/tuned pada development set manusia. Fungsi `tune()` tersedia (**KODE** untuk data penelitian), tetapi tidak dijalankan audit. Kasus pada skrip regresi jelas diperlakukan sebagai pengembangan/regresi; riwayat lengkap pemilihan aturan/bobot sebelumnya tidak tersedia. [CLM-020/022]

**Perhitungan angka.** Semua2.790kandidat trace yang memiliki final rank diperiksa jumlah kontribusinya dan RRF dari source ranks (toleransi1e-8), lulus; selisih maksimum jumlah kontribusi={max(x['absolute_error'] for x in scores['checks']):.3g}. Delapan contoh berikut juga dihitung ulang secara terpisah dari raw BM25/cosine/definisi fitur/distribusi audio; BM25 satu contoh dihitung langsung dari token corpus. Toleransi independen1e-7, semuanya lulus. Angka lengkap ada di [score_independent_examples.json](evidence/score_independent_examples.json) dan [score_verification.json](evidence/score_verification.json). Ini verifikasi aritmetika, bukan relevansi. [CLM-007]

{table(['Case','Track ID','Seluruh kontribusi','Hitung independen','Skor respons','Selisih'],score_rows)}

## 6. Perbedaan AUTO dan konfigurasi eksperimen

{table(['Mode','Entry/config','Retrieval aktif','Posisi filter','Fusion','Reranking','Kebijakan tambahan','Status eksekusi'],mode_rows)}

Pencarian biasa memakai AUTO. AUTO **bukan** sinonim E5: routing metadata, proteksi kutipan, query expansion/mood, pencocokan/bonus/reservasi lirik, passage reranking, pemisahan utama/serupa, popularitas tie, dan fallback merupakan kebijakan tambahan. Perbandingan nyata pada `Stay`, `I just woke up from a dream`, mixed rendah energy, dan audio>120ada di [mode_comparisons.json](evidence/mode_comparisons.json): E3/E4 memiliki setIDkandidat sama pada4/4probe; urutan akhirnya boleh berubah. E4/E5 identik pada dua probe tanpa audio; berbeda pada dua dengan audio. AUTO/E5 berbeda pada katalog, kutipan, dan hard-audio probe. Ini uji sifat pada probe tersebut dan penelusuran kode, bukan teorema untuk semua query. Tidak ada perbandingan efektivitas yang sah. [CLM-006]

## 7. Hasil validasi fungsional dan studi kasus

Backend: `python -m unittest discover -s tests -v`, **93 tests:88passed,0failed,5skipped**, waktu unittest6.304detik; log lengkap beserta command/durasi proses di [backend_tests.json](evidence/backend_tests.json). Lima skipped adalah integrasi Elasticsearch, karena MUSIC_IR_TEST_ES tidak1dan layanan/indeks belum dijalankan. Banyak tes memakai FakeSemantic/fixture kecil; ini tidak mengukur relevansi model nyata. Fallback dan evaluator diuji lewat fixture. [CLM-008/017/018]

Frontend: build TypeScript+Vite exit0; **15tes Playwright passed,0failed,0skipped**, waktu reporter30.1detik (proses {read('frontend_tests.json')['duration_seconds']:.2f}detik). Tes tersebut memakai route API tiruan, dibedakan dari live smoke browser. Log: [frontend_build.json](evidence/frontend_build.json), [frontend_tests.json](evidence/frontend_tests.json). Smoke browser tambahan tanpa mock berhasil menghasilkan4screenshot dan tidak merekam pageerror. [CLM-009/019]

Daftar51kasus dibekukan di [cases.jsonl](evidence/cases.jsonl) sebelum request. Terdapat48respons HTTP200dan3respons422yang memang diharapkan. Pemeriksaan bersama mencakup keunikan ID, batas top_k, dan kepatuhan audio bila aktif; sembilan regresi menjalankan verifier lama; sembilan kelompok assertion tambahan mengecek title/Unicode/no-lyrics/artist/audio/mood/lirik. Label `pass` berarti assertion yang dicatat terpenuhi, bukan judgment relevansi keseluruhan. Fallback live fault injection tidak dilakukan; fixture unit mencakupnya. [CLM-010]

{table(['Case ID','Query/input','Asal kasus','Harapan dan dasar','Mode/backend','Hasil aktual','Status','Bukti'],case_rows)}

JSON mentah lengkap mempertahankan hasil utama dan serupa secara terpisah; lihat [search_traces.jsonl](evidence/search_traces.jsonl), [case_results.json](evidence/case_results.json), [case_additional_assertions.json](evidence/case_additional_assertions.json). Screenshot asli: [pencarian](evidence/screenshots/search.png), [trace](evidence/screenshots/trace.png), [hasil kosong](evidence/screenshots/empty.png), [status evaluasi](evidence/screenshots/evaluation_status.png). Payload browser dan respons: [ui_live_responses.json](evidence/ui_live_responses.json). Tidak ada narasi hasil sebelum perbaikan yang dibuat; semua kasus dalam paket ini berasal dari snapshot yang sama.

## 8. Status evaluasi efektivitas retrieval

Status: **BELUM DAPAT DIEVALUASI**. Query aktual160: title32, artist32, lyrics32, semantic32, audio32; setiap kategori8dev+24test, total40dev+120test. Sumber96corpus_draft dan64authored_draft. Review approved0, pasangan query–dokumen dinilai0, query dengan judgment0, query dengan grade≥2sebanyak0, penilai0, cross-check/adjudikasi0. Database SQLite diperiksa read-only terhadap identitas dataset aktif `{bm['dataset_identity']}`; qrels.template.csv hanya header (0baris data). Lima pool historis yang ada bukan judgment. [CLM-011]

group_id berjumlah64dan tidak melintasi split; hint trackIDjuga tidak melintasi split. Pemeriksaan string NFKC/casefold yang mempertahankan operator tidak menemukan duplikasi exact lintas split. Ada tabrakan token-only ketika tandaoperator dibuang (`tempo >120` vs `tempo <=120`); itu **bukan query ekuivalen atau bukti kebocoran**. Query `artist-001`, `lyrics-001`, dan `title-016` juga muncul di regresi aktif; `title-016` berada pada test. Riwayat lengkap penggunaan saat menyusun aturan tidak tersedia, jadi independensi benchmark tidak dapat dinyatakan hanya karena group terpisah. [CLM-022]

Label manusia belum tersedia, sehingga nDCG@10, MRR@10, Recall@100 semuanya **null**, bukan0. [retrieval_metrics_summary.json](evidence/retrieval_metrics_summary.json) menyimpan alasan. Tidak dihitung metrik proksi sebagai pengganti relevansi. hint/targetID, keluaran model, filter genre/tempo, hasil pilihan agent, dan urutan sistem tidak dijadikan groundtruth. [CLM-012]

Evaluator tersedia menggunakan gain `2^grade-1`, discount log2(rank+1), normalisasi DCG dengan ideal top10; relevan biner grade≥2. MRR mencari relevan pertama sampai10; Recall menghitung relevan unik sampai100dibagi jumlah relevan diketahui. Unjudged diperlakukan0di fungsi metrik, tetapi tetap harus dibedakan dari label manusia0pada pengumpulan; recall relatif qrels yang diketahui. Empty ranking memberi0jika query memiliki relevan; fungsi metrik juga0untuk query tanpa relevan, tetapi validator menolak query wajib tanpa label≥2. Duplikasi/konflik grade dan split diperiksa sesuai `read_benchmark`. Fixture hitungan manual terpisah pada3dokumen lulus1e-12; [evaluator_manual_fixture.json](evidence/evaluator_manual_fixture.json) **bukan hasil dataset penelitian**.

Objek ranking evaluator sekarang adalah `response.results` (**utama saja**), bukan `candidate_ids`, bukan gabungan tampilan; `related_results` tidak dinilai. Pool aplikasi juga utama top-depth ditambah hint dan2sampel corpus, tanpa label otomatis. Untuk tema AUTO, daftar kandidat/utama+serupa sudah dibatasi24, sehingga metrik bernama Recall@100akan bekerja pada daftar nyata yang mungkin jauh lebih pendek. Jangan membandingkannya dengan recall kandidat100seolah objek sama. Evaluator macro mean per mode/kategori tersedia, tetapi tidak dijalankan untuk penelitian. Penanganan error belum menulis incomplete manifest; lihat bagian10.

Siapan manusia: [annotation_needed.csv](evidence/annotation_needed.csv) berisi **{anno['annotation_rows']}pasangan dari10query aktual**, union hasil utama top10AUTO/E1–E5;60request pooling berhasil. Urutan diacak, mode/skor/hint disembunyikan, label dan penilai kosong. Semua191pasangan **100%unjudged** saat dibuat; angka ini proporsi status anotasi, bukan efektivitas. [query_review_checklist.csv](evidence/query_review_checklist.csv) mencakup160query; **150belum dipool pada audit**. Pedoman dan batas pooling: [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md); rencana/pencatatan: [annotation_manifest.json](evidence/annotation_manifest.json), [annotation_pool_traces.jsonl](evidence/annotation_pool_traces.jsonl). [CLM-016]

Pekerjaan manusia berikutnya: setujui maksud query, verifikasi dokumen/lirik yang relevan, perluas pool terutama untuk recall, beri grade0–3secara independen, periksa silang/adjudikasi konflik, dokumentasikan asal label, lalu bekukan query/qrels/corpus/config untuk perbandingan seluruh mode. Skala/pedoman saja tidak berarti aktivitas penilaian sudah dilakukan. Keunggulan AUTO/E5 belum dapat disimpulkan.

## 9. Hasil pengukuran waktu dan kondisi cache

Rencana dibekukan sebelum run:6query(title,artist,lyrics,tema,audio,mixed), semua6mode,10warm-up per mode(**60total**),5pengulangan per query-mode(**180observasi**,30permode), seed42, satu request aktif, top_k30, trace=true. Mode warm-up diacak `{lat['warmup_mode_order']}`; seluruh job mode/query/repeat diacak lagi dengan PRNG yang sama. Fixture/unit/build/UI-tests telah selesai sebelum benchmark; selama benchmark tidak dijalankan audit lain yang membuat request. Beban OS/proses pengguna tidak dikontrol. [CLM-013]

Timer HTTP memakai perf_counter tepat sebelum urlopen sampai seluruh bytes response terbaca; mencakup network loopback, validasi/queue, engine, diagnostics/serialization server; tidak mencakup decodeJSON atau penulisan log sisi klien. API langsung127.0.0.1:8000, jadi ini bukan waktu render browser dan bukan HTTP lewat proxy Vite. Timer engine `latency_ms` berhenti sebelum diagnostics dan serialisasiJSON; mencakup parsing, query encoding, retrieval/ranking, passage cache miss/hit dan pembuatan alasan/snippet, tetapi mengurangi waktu explicit warmup/model load. Trace juga mengeluarkan timings per tahap; jumlah tahap tidak dipakai sebagai ganti walltime. Tidak ada tahap retrieval satu query yang dijalankan konkuren pada kode ini.

{table(['Mode','n','HTTP mean ms','HTTP median ms','HTTP p95 ms','Engine mean ms','Engine median ms','Engine p95 ms','Error'],latency_rows)}

Agregasi per mode memberi bobot sama pada6query×5pengulangan; p95=`numpy.percentile` linear pada30observasi. Semua180request berhasil,0degraded. Hasil ini khusus subset/mesin/kondisi ini. E1–E4tidak melayani audio murni dan dapat mengembalikan kosong dengan cepat; waktu bukan bukti kemampuan retrieval setara. Jangan menafsirkan perbedaan median sebagai perbandingan relevansi. Raw: [latency_raw.csv](evidence/latency_raw.csv), warm-up [latency_warmups.json](evidence/latency_warmups.json), rencana/summary [latency_summary.json](evidence/latency_summary.json).

Proses API baru diamati sebelum encoder dimuat, kemudian satu request E3: HTTP **{cold['http_ms']:.2f}ms**, engine **{cold['response']['latency_ms']:.2f}ms**, explicit model warmup/load **{cold['response']['trace']['decisions']['timings_ms']['model_loading']:.2f}ms**. Ini satu observasi cold **proses model**, dengan weights dan vectorcachelokal sudah ada; OS filecachetidak dikosongkan. Startup API sampai siap terlihat di log, tetapi durasi startup terisolasi tidak diukur. [model_load_observation.json](evidence/model_load_observation.json)

Cache bagian sudah berisi214vektor sebelum kasus/latensi; hash dan jumlah tetap214selama kedua fase. Dengan demikian distribusi latensi tema ini memakai cache yang sudah tersedia. Tidak ada cache pengguna dihapus/ditulis manual. Pooling anotasi sesudah benchmark dapat menambah vektor melalui mekanisme aplikasi normal; keadaan akhir dicatat di snapshotakhir. Biaya corpus embedding tidak diukur ulang; metadata historis3267.37detik dipisah. Dokumen lama menyebut miss/hitbagian37606.82/662.48ms; itu **HISTORIS** pada [historical_reference.json](evidence/historical_reference.json), bukan distribusi benchmark audit. Audit tidak menyediakan cold passage-cache terkontrol dan tidak menyatakan rasio percepatan umum. Torch CPU tidak memerlukan sinkronisasiCUDA; tidak ada timingGPUyang dilaporkan.

## 10. Temuan ketidaksesuaian/bug beserta dampaknya

| Temuan | Lokasi dan bukti | Status | Dampak dan batas |
| --- | --- | --- | --- |
| Evaluator menghentikan proses tanpa menulis hasil parsial/manifest incomplete ketika request wajib gagal | evaluate.py:75–104; [evaluator_failure_reproduction.json](evidence/evaluator_failure_reproduction.json) | EKSEKUSI fixture | Pada dua query sintetis, exception search ke13terjadi sesudah10warmup+2pengukuran berhasil; direktorioutput tidak terbentuk. Run penelitian mendatang dapat kehilangan diagnostik/hasil parsial. Tidak diperbaiki audit ini. |
| Nama Recall@100dapat digunakan pada daftar utama yang sudah pendek; related tidak ikut | evaluate.py:82; engine.py:217/277 | KODE untuk metrik penelitian; pembatasan tema teramati pada trace | Label @100menyatakan cutoff, bukan jaminan100dokumen/candidate-recall. Tetapkan objek ranking eksplisit saat evaluasi. |
| Query test tidak dapat langsung diklaim independen | query_independence.json; title-016 juga regresi aktif | EKSEKUSI pencocokan string, histori sebab-akibat belum tersedia | Struktur group bersih tidak membuktikan bebas paparan penyusunan aturan. |
| Genre dan mood merupakan proksi terbatas | metadata.py:26; mood.py:7; trace genre/mood | EKSEKUSI/kode | Labelplaylist bukan genre rekaman terverifikasi; valence/energy dan regex tidak menjadi groundtruth emosi. |
| Angka historis dan label “default pipeline equals E5” pada fixture tidak berlaku universal | tests/test_search.py fixture; mode_comparisons.json | EKSEKUSI | AUTO berbeda dari E5pada query nyata tertentu; hasil fixture hanya untuk input fixture. |

Tidak dilakukan perbaikan agar hasil terlihat lebih baik. Masalah keluaran konsol kolektor audit (encoding cp1252setelah build berhasil) dan label waktu awal kolektor dikoreksi hanya pada perkakas audit; catatan transparan tersedia di [audit_tool_notes.json](evidence/audit_tool_notes.json). Output subprocess lengkap dipertahankan. Label timestamp command lama direkonstruksi dari timestamp akhir dikurangi durasi perf_counter; presisi waktu awalnya bersifat rekonstruksi.

## 11. Keterbatasan dan data yang belum tersedia

Belum ada qrels/manusia/review sehingga efektivitas serta keunggulan metode tidak dapat diverifikasi. Tidak ada validasi independen pasangan lirik–rekaman, metode pengambilan sumber, atau riwayat tuning lengkap. Pool anotasi baru mencakup10/160querydan kedalaman10, sehingga belum cukup sebagai benchmark Recall@100lengkap. Uji fault live tidak dilakukan; fallback dibuktikan fixture. Elasticsearch/infrastrukturindeks tidak berjalan; adapter hanya dibaca dan5tesnya skipped. Test UIunit memakai mock, sedangkan4screenshotdan live smoke memakai backend nyata.

Hardware GPU/VRAM dan jumlah core fisik tidak terverifikasi akibat akses CIM; CPU/device/dtype runtime berhasil diperiksa dengan mekanisme lain. Pengukuran latensi memakai subset dan cachehangat, bukan beban produksi ataupuncoldcacheterkontrol. Biaya pembuatan corpus embedding historis, bukan pengukuran ulang. Tidak ada renderPNGMermaid karena renderer tidak tersedia. Screenshot tersedia pada4kategori yang diminta; yang disebut “status evaluasi” menunjukkan belum ada penilaian, bukan layar metrik yang telah dihitung.

RawCSV, corpusJSON/Parquet, vektor/modelweights, node_modules, virtualenvironment, serta seluruh lirik mentah tidak disertakan untuk membatasi paket; identitasnya tersedia lewatSHA. Scratch raw yang sempat dipakai untuk reproduksi merge telah dihapus hanya dari folder scratch audit. Bukti hitungan, trace cuplikan/bagian yang diperlukan, salinan kode/config/lockfile/query, log, dan screenshot tetap disertakan. Path sumber pada snapshot adalah identifikasi input yang sengaja tidak dibundel, bukan tautan bukti eksternal yang harus dicari pembaca.

## 12. Bahan faktual untuk Bab 3, Bab 4, dan kesimpulan

| Pernyataan calon laporan | Dasar bukti | Status | Batas kesimpulan | Bagian laporan yang sesuai |
| --- | --- | --- | --- | --- |
| Sistem mencari katalog musik dengan BM25lokal, embeddingpretraineddan aturan intent kondisional | CLM-002/004/005; tabelpipeline; source | EKSEKUSI | Tidak semua jalur dipakai setiap request; bukan LLMgeneratif/agenticruntime | Bab3 |
| Corpus1686baris menjadi1437lagu unik;1404berlirik | CLM-003 | EKSEKUSI | Kelengkapanlirik bukan verifikasi pasangan rekaman | Bab3/4 |
| Inferensi BGE-M3memakai CPUfloat32, matriks1437×1024 | CLM-004/021 | EKSEKUSI | Embedding tersimpan historis diperiksa, tidakdibangun ulang; bukantraining | Bab3/4 |
| AUTOmemiliki aturan tambahan di atas konfigurasi eksperimen | CLM-006/010; traces | EKSEKUSI/kode | Tidak berarti lebih relevan dariE5 | Bab3/4 |
| Skor numerik dapat ditelusuri dan rumus contoh cocok | CLM-007 | EKSEKUSI | Skor bukanprobabilitas/akurasi; bonus dapat>1 | Bab4 |
| Tesbackend88passed+5skippeddan15tesUIpassed | CLM-008/009 | EKSEKUSI | Fixture/mocking dan dependensiskippedharus disebut; bukan metrikretrieval | Bab4 |
| 51kasusHTTPdan4screenshotmenunjukkan perilaku fungsi pada snapshotini | CLM-010/019 | EKSEKUSI | Kasuspengembangan/regresibukan pengujianrelevansiindependen | Bab4 |
| Latensiterukur pada subset6querydengan180observasi+60warmup | CLM-013 | EKSEKUSI | Mesin/cache/subsettertentu; bukan perbandingankualitas | Bab4 |
| Belum tersedia bukti efektivitas retrieval yang sah | CLM-011/012/022 | BELUM TERVERIFIKASI untuk efektivitas | nDCG/MRR/Recall=null; tidak menyatakanAUTO/E5unggul | Bab4/kesimpulan |
| Lembarpenilaianmanusiasudahdisiapkan | CLM-016 | EKSEKUSI | 191pasangan/10query, belumdinilai;150querybelumdipool | Pekerjaanlanjutan/kesimpulan |
| Evaluatorperlumencatat incomplete saat querygagal | CLM-015 | EKSEKUSI fixture | Perbaikanterpisah; bukan bukti runpenelitiangagal | Batasan/kesimpulan |

Indeks bukti utama: [claims.json](evidence/claims.json), [verification_log.txt](evidence/verification_log.txt), [audit_summary.json](audit_summary.json), dan [package_manifest.json](evidence/package_manifest.json). Penyusunan ulang laporan akademik ditunda sampai paket fakta diperiksa.
'''
    # Natural cache misses occurred after the fixed latency benchmark, during annotation pooling.
    observations=[]
    for phase,name in [('cases','search_traces.jsonl'),('annotation','annotation_pool_traces.jsonl')]:
        for line in (E/name).read_text(encoding='utf-8').splitlines():
            r=json.loads(line);response=r.get('response',{})
            if response.get('mode')!='AUTO' or response.get('query_type')!='semantic':continue
            ps=response.get('trace',{}).get('decisions',{}).get('stages',{}).get('lyric_passages',{})
            if phase=='annotation' or r.get('case_id')=='REG-05':
                observations.append({'phase':phase,'query_or_case_id':r.get('query_id',r.get('case_id')),'query':r['payload']['query'],
                    'http_ms':r['http_ms'],'engine_ms':response['latency_ms'],'passage_ms':response['trace']['decisions']['timings_ms'].get('lyric_passages'),**ps})
    write(E/'cache_observations.json',{'scope':'Natural cache state observations, separate queries and phases, NOT a controlled before/after speedup benchmark','rows':observations})
    note='''Pooling anotasi sesudah benchmark menambah **123 vektor bagian melalui aplikasi**, dari **214 menjadi 337 entri** (snapshot akhir); tidak ada penghapusan cache atau perubahan manual. Dua request anotasi mengalami cache miss alami, sehingga biaya bagian yang benar-benar dienkode juga dapat dipisahkan dari distribusi benchmark cache hangat. Berikut observasi satu request per baris; query berbeda, jadi tidak digunakan untuk menghitung rasio percepatan.

'''+table(['Fase/case','Query','Bagian','Vektor baru','Cache hit unik','Tahap bagian ms','Engine ms','HTTP ms'],[[o['phase']+'/'+o['query_or_case_id'],o['query'],o.get('passages'),o.get('encoded'),o.get('cache_hits'),f"{o['passage_ms']:.2f}",f"{o['engine_ms']:.2f}",f"{o['http_ms']:.2f}"] for o in observations])+'''

Bukti: [cache_observations.json](evidence/cache_observations.json), trace kasus/pooling, dan [snapshot_after.json](evidence/snapshot_after.json).'''
    main=main.replace('Pooling anotasi sesudah benchmark dapat menambah vektor melalui mekanisme aplikasi normal; keadaan akhir dicatat di snapshotakhir.',note+'\n\n')
    # Restore spaces for compact numeric technical prose without changing identifiers or numbers.
    # Explicit phrases are kept simple; no academic narrative is generated.
    (OUT/'FAKTA_PROYEK_MUSIC_IR.md').write_text(main,encoding='utf-8')
    summary={'audit_status':'evidence_package_ready_with_documented_limits','start':'2026-11-22T16:25:21+07:00','report_composed_at':ended,'timezone':'Asia/Jakarta','root':str(ROOT),'commit':s['commit'],
       'config_unchanged':config['runtime_config_matches_file'],'protected_inputs_unchanged':not read('snapshot_after.json')['protected_input_changes'],'runtime':eng,'dataset':{k:d[k] for k in ['source_rows','source_columns','source_unique_ids','lyrics_available','without_lyrics','repeated_id_extra_occurrences','identical_row_extra_occurrences','active_corpus_identity']},
       'tests':{'backend':{'total':93,'passed':88,'failed':0,'skipped':5,'skip_reason':'Elasticsearch opt-in unset; service/index not started'},'frontend_mocked':{'passed':15,'failed':0,'skipped':0},'frontend_build_exit':read('frontend_build.json')['exit_code'],'http_cases':len(cases),'http_case_failures':len(fail),'real_ui_screenshots':4,'independent_score_checks':len(ind['checks'])},
       'retrieval_evaluation':{'status':'not_evaluated','metrics':{'ndcg@10':None,'mrr@10':None,'recall@100':None},'reason':'160 draft queries; 0 human reviews and 0 judgments; no eligible human qrels'},
       'latency':{'measured_requests':180,'warmup_requests':60,'queries':6,'seed':42,'cache':'existing; no deletion; warm passage vectors','summary_file':'evidence/latency_summary.json'},
       'annotation':{'queries_pooled':10,'candidate_pairs':anno['annotation_rows'],'human_labels_generated':0,'remaining_queries_unpooled':150,'file':'evidence/annotation_needed.csv'},
       'known_bug':'Evaluator fixture error aborts before saving incomplete manifest or partial successful measurements',
       'missing_artifacts':{'pipeline_actual.png':'Mermaid renderer not installed','retrieval_metrics_per_query.csv':'No valid human qrels; not produced as empty data','cold_passage_cache_measurement':'Existing user cache retained; controlled cold cache not performed','gpu_vram_inventory':'CIM access denied; CPU-only torch runtime observed'},
       'claim_status_labels':statuses,'claims_file':'evidence/claims.json','protected_inputs_check':'evidence/snapshot_after.json'}
    write(OUT/'audit_summary.json',summary)
    print('report written',len(main),'characters',flush=True)

if __name__=='__main__':compose()
