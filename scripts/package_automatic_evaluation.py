"""Package a completed automatic evaluation, excluding full lyric inputs and secrets."""
import argparse
import csv
import hashlib
import json
import sys
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from music_ir.relevance import RelevanceRun,atomic_json


def package(run_path):
    run=RelevanceRun(run_path)
    counts=run.counts()
    if not counts['auto_complete'] or counts['ranking_errors'] or counts['auto_errors']:
        raise ValueError('Only a completed, error-free processing run can be packaged as complete')
    ingest=json.loads((run.directory/'semantic_ingest_status.json').read_text(encoding='utf-8'))
    if ingest['errors'] or not ingest['all_documents_imported']:raise ValueError('Semantic import is incomplete')
    for name in ['backend','build','ui']:
        result=json.loads((run.directory/'validation'/(name+'.json')).read_text(encoding='utf-8'))
        if result['exit_code']!=0:raise ValueError(name+' validation failed')
    protected=json.loads((run.directory/'validation/retrieval_unchanged.json').read_text(encoding='utf-8'))
    if not protected['retrieval_preserved']:raise ValueError('Retrieval preservation not verified')
    latest=json.loads((run.directory/'latest_export.json').read_text(encoding='utf-8'))
    if latest['counts']!=counts:raise ValueError('Export is stale; export again before packaging')
    export=run.directory/latest['directory']
    metric_rows=list(csv.DictReader((export/'metrics_auto_per_query.csv').open(encoding='utf-8',newline='')))
    required={(q['query_id'],m) for q in run.queries for m in run.manifest['modes']}
    if len(metric_rows)!=len(required) or {(r['query_id'],r['mode']) for r in metric_rows}!=required:
        raise ValueError('Required query-mode rows omitted or duplicated')
    if any(r['judgment_status'] in {'pending_labels','retrieval_error'} for r in metric_rows):raise ValueError('Pending metric rows')
    with run.connect() as db:
        human_records=db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]
        query_reviews=db.execute('SELECT COUNT(*) FROM query_reviews').fetchone()[0]
        labels=[json.loads(r['label']) for r in db.execute('SELECT label FROM auto_labels')]
    if human_records or query_reviews:raise ValueError('Unexpected human records in automatic-only run')
    if len(labels)!=counts['pairs']:raise ValueError('Pair coverage mismatch')
    qrels=list(csv.DictReader((export/'qrels_auto.tsv').open(encoding='utf-8',newline=''),delimiter='\t'))
    unresolved=list(csv.DictReader((export/'unresolved_pairs.csv').open(encoding='utf-8',newline='')))
    if len(qrels)!=counts['auto_completed'] or len(unresolved)!=counts['auto_needs_review']:
        raise ValueError('Qrels/unknown export count mismatch')
    source_manifest=[]
    for path in sorted((run.directory/'semantic_packets').glob('worker_*/batch_*.json')):
        packet=json.loads(path.read_text(encoding='utf-8'))
        source_manifest.append({'local_file':str(path.relative_to(run.directory)).replace('\\','/'),
            'file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'documents':[{'track_id':d['track_id'],'input_sha256':d['input_sha256'],
                'lyric_sha256':d['lyrics']['restored_sha256'],'characters':d['lyrics']['restored_chars']} for d in packet['records']]})
    atomic_json(run.directory/'semantic_input_hashes.json',source_manifest)
    proof={'verified_utc':datetime.now(timezone.utc).isoformat(),'counts':counts,
        'all_mandatory_metric_rows':len(metric_rows),'metric_statuses':dict(Counter(r['judgment_status'] for r in metric_rows)),
        'qrels_rows':len(qrels),'unresolved_rows':len(unresolved),'human_records':human_records,'query_reviews':query_reviews,
        'label_origins':dict(Counter(r['label_origin'] for r in labels)),
        'uncertainty_flags':dict(Counter(f for r in labels for f in r['uncertainty_flags'])),
        'semantic_documents':ingest['documents_imported'],'semantic_import_errors':ingest['errors'],
        'retrieval_preserved':True,'full_lyric_inputs_included':False}
    atomic_json(run.directory/'validation/package_verification.json',proof)
    stamp=datetime.now(timezone(timedelta(hours=7))).strftime('%Y%m%dT%H%M%S_WIB')
    output=ROOT/('PAKET_EVALUASI_OTOMATIS_MUSIC_IR_'+stamp+'.zip')
    prefix='evaluasi_otomatis_music_ir_'+stamp
    files={}
    for name in ['LAPORAN_EVALUASI_RELEVANSI.md','TEKS_SIAP_LAPORAN.md','manifest.json','latest_export.json','progress.json',
                 'automatic_rubric.json','objective_method.json','judging_agents.json','semantic_query_contexts.json',
                 'semantic_packet_manifest.json','semantic_ingest_status.json','semantic_input_hashes.json',
                 'label_data_errata.json','agent_capacity_events.json','validation_method_note.json','rankings.jsonl','queries.json']:
        path=run.directory/name
        if path.exists():files[name]=path
    for path in export.iterdir():
        if path.is_file():files['exports/'+path.name]=path
    for pattern in ['semantic_judgments/worker_*/*.json','validation/*.json','validation/*.png']:
        for path in run.directory.glob(pattern):files[str(path.relative_to(run.directory)).replace('\\','/')]=path
    source_paths=['README.md','config.json','pyproject.toml','music_ir/automatic_evaluation.py','music_ir/relevance.py',
        'music_ir/relevance_judge.py','music_ir/relevance_review.py','music_ir/api.py','tests/test_automatic_evaluation.py',
        'tests/test_relevance.py','scripts/verify_relevance.py','scripts/package_automatic_evaluation.py',
        'scripts/capture_relevance_review.cjs','frontend/src/RelevancePage.tsx','frontend/src/relevance.css',
        'frontend/tests/relevance.spec.ts']
    for rel in source_paths:files['source/'+rel]=ROOT/rel
    readme='''# Paket evaluasi otomatis Music IR

Buka LAPORAN_EVALUASI_RELEVANSI.md untuk hasil, penyebut, dan keterbatasan. TEKS_SIAP_LAPORAN.md dapat dipakai sebagai paragraf metode. exports/ memuat qrels otomatis, label, semua metrik per query dan agregat. Tidak diperlukan review manusia untuk ekspor ini; hasil tidak diklaim sebagai ground truth manusia.

Pipeline retrieval dan parameter dibekukan. Hasil merupakan evaluasi hibrida: tema dinilai agent LLM dari lirik penuh; katalog/kutipan/audio memakai proksi pemeriksaan corpus yang dinyatakan terpisah. Null tetap tidak diketahui dan bukan label0. Tes fungsional bukan metrik relevansi.

semantic_judgments/ berisi keputusan agent dan kutipan pendek. semantic_input_hashes.json mencatat seluruh input penilaian dan hash sumber. Full corpus.json, semantic_packets/ (lirik lengkap), state.sqlite3, model, cache, environment, credential, node_modules dan virtual environment sengaja tidak disertakan. Berkas input lengkap tetap tersedia dalam folder run lokal yang disebut manifest; verifikasi ulang lirik memerlukan snapshot corpus tersebut. Tidak ada tautan input yang seolah berkas lengkapnya disertakan di ZIP ini.

label_data_errata.json mempertahankan label sebelum/sesudah koreksi field berisi placeholder editor. validation/ menyimpan log eksekusi tes, bukti pipeline tidak berubah, dan tangkapan layar aplikasi asli. Pengujian Elasticsearch dilewati apabila flag pengujian integrasi tidak diaktifkan; backend retrieval run ini adalah local.

source/ adalah snapshot kode evaluasi dan antarmuka untuk pemeriksaan. Menjalankan ulang penilaian LLM dapat menghasilkan perbedaan; model/revision persis, sampling, token dan biaya sesi tidak diekspos. Paket tidak mengarang nilainya. Untuk menghitung ulang label deterministik/metric gunakan kode tersebut dengan snapshot data lokal; jangan mengubah rubrik berdasarkan skor.
'''
    index={'created_wib':stamp,'run_id':run.directory.name,'files':[
        {'path':name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for name,path in sorted(files.items())],'excluded_inputs':['corpus.json','semantic_packets/','state.sqlite3'],
        'exclusion_reason':'Full raw lyrics are kept locally; identities and hashes are included instead.'}
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(prefix+'/README_PAKET.md',readme)
        archive.writestr(prefix+'/PACKAGE_MANIFEST.json',json.dumps(index,ensure_ascii=False,indent=2))
        for name,path in sorted(files.items()):archive.write(path,prefix+'/'+name)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise ValueError('ZIP integrity failed')
    result={'zip':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'file_count':len(files)+2,'counts':counts}
    atomic_json(run.directory/'delivery_package.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(package(args.run),ensure_ascii=False,indent=2))
