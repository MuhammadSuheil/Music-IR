"""Capture actual run proof, stage counts, and reproducible command history."""
import ast
import csv
import hashlib
import json
import platform
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from music_ir.relevance import RelevanceRun,atomic_json,digest
from music_ir.relevance_review import write_report
from music_ir.evaluate import metrics
import math
run=RelevanceRun(Path(sys.argv[1]))
directory=run.directory/'validation';directory.mkdir(exist_ok=True)
initial=root/'audit_music_ir_20261122T162521_WIB/evidence/annotation_needed.csv'
with initial.open(encoding='utf-8-sig',newline='') as f:prior=list(csv.DictReader(f))
qrels=root/'evaluation/qrels.template.csv'
with qrels.open(encoding='utf-8-sig',newline='') as f:original_qrels=list(csv.DictReader(f))
with sqlite3.connect((root/'artifacts/benchmark/reviews.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    legacy={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ['judgments','reviews']}
with run.connect() as db:
    ranked=[dict(r) for r in db.execute('SELECT * FROM rankings')]
    thematic=[{'query_id':r['query_id'],'mode':r['mode'],**json.loads(r['response'])} for r in ranked if r['status']=='ok' and r['mode']=='AUTO' and json.loads(r['response']).get('query_type')=='semantic']
    labels=[json.loads(r['label']) for r in db.execute('SELECT * FROM auto_labels')]
proof={'query_total':len(run.queries),'query_splits':dict(Counter(q['split'] for q in run.queries)),
       'query_categories':dict(Counter(q['category'] for q in run.queries)), 'query_review_status_in_frozen_source':dict(Counter(q.get('review_status') for q in run.queries)),
       'prior_audit_annotation_rows':len(prior),'prior_audit_annotation_queries':len({r['query_id'] for r in prior}),
       'original_qrels_template_rows':len(original_qrels),'legacy_benchmark_records_untouched':legacy,
       'frozen_corpus_documents':len(run.docs),'frozen_unique_track_ids':len(run.by_track),
       'ranking_jobs':len(ranked),'ranking_errors':[r for r in ranked if r['status']!='ok'],
       'theme_auto_primary_lengths':[{k:r[k] for k in ['query_id','length','related_count_excluded']} for r in thematic],
       'theme_auto_primary_max':max((r['length'] for r in thematic),default=None),
       'ranking_object':'response.results / primary only; response.related_results excluded',
       'auto_grades':dict(Counter(str(a['auto_grade']) for a in labels)),'actual_http_instruction_model_calls':0,
       'actual_session_judgments':len(labels),'web_used_for_actual_labels':False,
       'session_timestamp_note':'judged_utc on imported session labels is import/recording time, not an exposed server inference timestamp; exact session model/parameters/tokens/cost remain null',
       'python':platform.python_version(),'scope':'Facts read from actual snapshot, SQLite, original annotation CSV, and stored responses; no human labeling performed'}
atomic_json(directory/'project_verification.json',proof)
source_files=[*root.glob('music_ir/relevance*.py'),root/'music_ir/api.py',root/'frontend/src/RelevancePage.tsx',root/'frontend/src/relevance.css',
              root/'tests/test_relevance.py',root/'frontend/tests/relevance.spec.ts']
atomic_json(directory/'implementation_hashes.json',{str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files})
notes={'collector_stdout_issue':'First verification runner completed backend/build successfully and saved their JSON logs, then failed while printing a Unicode Vite checkmark to cp1252 stdout. Collector stdout changed to UTF-8; UI validation run separately. This was not an application build failure.',
       'earlier_session_import_during_pool':'OS work lock correctly rejected concurrent session import during pool preparation. Import succeeded after pooling; idempotent second import added0 and reused10 cached labels.',
       'source_prompt_hash_method':'SHA256 of canonical JSON serialization of the prompt string (same digest function used in packet/import); judge_prompt.txt preserves exact prompt text.',
       'scope':'No human actions taken on the actual run; all synthetic human review tests used temporary fixture directories.'}
atomic_json(directory/'execution_notes.json',notes)
result=write_report(run)
atomic_json(run.directory/'progress.json',run.counts())
report=run.directory/'LAPORAN_EVALUASI_RELEVANSI.md'
text=report.read_text(encoding='utf-8')
backend=json.loads((directory/'backend.json').read_text(encoding='utf-8'))
ui=json.loads((directory/'ui.json').read_text(encoding='utf-8'))
build=json.loads((directory/'build.json').read_text(encoding='utf-8'))
summary={'backend_exit':backend['exit_code'],'backend_reporter_summary':backend['stderr'].split('----------------------------------------------------------------------')[-1].strip(),
         'frontend_build_exit':build['exit_code'],'frontend_test_exit':ui['exit_code'],
         'frontend_reporter_summary':re.findall(r'\d+ passed[^\n]*',ui['stdout']),
         'retrieval_preserved':json.loads((directory/'retrieval_unchanged.json').read_text())['retrieval_preserved']}
atomic_json(directory/'validation_summary.json',summary)
fixture_labels={'A':3,'B':2,'C':0};fixture_ranking=['C','B','A']
actual=metrics(fixture_ranking,fixture_labels)
expected={'ndcg@10':(3/math.log2(3)+7/2)/(7+3/math.log2(3)),'mrr@10':.5,'recall@100':1.}
atomic_json(directory/'manual_metric_fixture.json',{'scope':'synthetic arithmetic fixture, NOT research effectiveness','ranking':fixture_ranking,'labels':fixture_labels,
           'manual_expected':expected,'actual':actual,'tolerance':1e-12,'passed':all(abs(actual[k]-expected[k])<1e-12 for k in expected)})
text+='''
## Validasi yang benar-benar dijalankan

```json
'''+json.dumps(summary,ensure_ascii=False,indent=2)+'''
```

Log lengkap: validation/backend.json, validation/build.json, validation/ui.json. Tes manusia, adapter HTTP dengan mock transport, resume, grade/quote validation, kegagalan wajib, ekspor parsial, versi baru, dan fixture metrik memakai data sintetis di temporary directory; tidak mengisi label manusia pada run penelitian. Fixture hitungan manual beserta angka expected/actual disimpan di validation/manual_metric_fixture.json; bukan metrik dataset. Backend model instruksi nyata belum diuji. Periksa validation/retrieval_unchanged.json untuk hash 11 modul core, config, corpus, query, dan AST API pencarian semula yang tetap sama. Penambahan route/page evaluasi tidak mengubah ranking.

Pemeriksaan kondisi proyek: validation/project_verification.json. Source penilai dan review baru: validation/implementation_hashes.json. Screenshot dan smoke browser nyata: validation/review_live_*.png dan validation/review_live_browser.json; tidak ada POST/PUT penilaian manusia. validation/execution_notes.json membedakan error perkakas dari hasil aplikasi.

## Status eksekusi yang belum selesai

Pembentukan pool penuh selesai: 960/960 pencarian, 160 query, 24.367 pasangan. Penilaian sesi langsung baru 10 pasangan: 8 grade 0 dan 2 null untuk ambiguity, belum menyelesaikan satu pool query. Sebanyak 24.357 pasangan belum dinilai. Karena itu tidak ada nilai nDCG/MRR/Recall penelitian yang sah untuk dilaporkan; JSON metrik tetap null/incomplete. Ini tidak dinyatakan sebagai tahap otomatis selesai. pair_status.jsonl pada ekspor mencatat status seluruh pasangan, termasuk auto_grade/human_grade/final_grade null untuk pasangan yang belum diproses; pending tidak diubah menjadi nilai 0.

Sesi assistant yang digunakan menilai sepuluh input tidak menyediakan endpoint batch yang dapat dipanggil kode proyek. Tidak ditemukan model instruksi lokal atau API terkonfigurasi (backend_discovery.json); eksekusi command label berhenti dengan status blocked_backend dan exit2. Tidak dicoba mengakses credential internal sesi/subscription atau mengganti LLM dengan BGE-M3/aturan. Kelanjutan bisa melalui paket sesi yang benar-benar dinilai, atau backend instruksi yang dikonfigurasi. Untuk provider/model berbeda, clone-for-judge menggunakan ranking/pool yang sama ke runbaru tanpa menimpa label sesi lama.

Model persis dan parameter generasi sesi tidak diekspos dan tetap null. Kolom judged_utc pada label sesi merupakan waktu impor/pencatatan, bukan timestamp inferensi server. Tidak ada sumber web yang dipakai untuk10label aktual karena bukti corpus memadai atau query memang ambigu. Review manusia, persetujuan query, dan qrels_final masih belum tersedia dan tidak dibuat atas nama pengguna.
'''
report.write_text(text,encoding='utf-8')
atomic_json(run.directory/'run_summary.json',{'counts':run.counts(),'validation':summary,'latest_export':result,
           'automatic_stage_complete':False,'reason':'No callable instruction-model backend; direct session labels cover10pairs only','review_url':'http://127.0.0.1:8501/?view=relevance'})
export_dir=run.directory/result['directory']
with (export_dir/'pair_status.jsonl').open(encoding='utf-8') as f:pair_rows=[json.loads(line) for line in f if line.strip()]
with (export_dir/'qrels_auto.tsv').open(encoding='utf-8',newline='') as f:qrels_rows=list(csv.DictReader(f,delimiter='\t'))
delivery={'pool_pairs':len(run.pair_ids()),'pair_status_rows':len(pair_rows),
          'unique_pairs':len({(r['query_id'],r['track_id']) for r in pair_rows}),
          'auto_qrels_nonnull_rows':len(qrels_rows),'pending_auto_rows':sum(r['auto_status']=='not_processed' for r in pair_rows),
          'human_final_pairs':sum(r['final_grade'] is not None for r in pair_rows),
          'raw_response_references_exist':all((run.directory/p).is_file() for a in labels for p in a['raw_response_files']),
          'qrels_final_available':(export_dir/'qrels_final.tsv').exists(),
          'query_mode_rows':{}}
for stage in ['auto','final']:
    with (export_dir/('metrics_'+stage+'_per_query.csv')).open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    delivery['query_mode_rows'][stage]={'rows':len(rows),'status_counts':dict(Counter(r['status'] for r in rows))}
delivery['passed']=delivery['pool_pairs']==delivery['pair_status_rows']==delivery['unique_pairs'] and delivery['raw_response_references_exist'] and all(v['rows']==len(run.queries)*6 for v in delivery['query_mode_rows'].values())
atomic_json(directory/'delivery_check.json',delivery)
if not delivery['passed']:raise RuntimeError('Run artifacts are inconsistent')
print(json.dumps({'report':str(report),'counts':run.counts(),'validation':summary},ensure_ascii=False,indent=2))
