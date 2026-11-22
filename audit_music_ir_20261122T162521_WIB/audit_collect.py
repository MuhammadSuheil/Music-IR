"""Separate audit tooling; never changes application configuration or source."""
import collections, csv, ctypes, hashlib, importlib.metadata, json, math, os, platform, re, shutil, sqlite3, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
ROOT = OUT.parent
sys.path.insert(0, str(ROOT))
E = OUT / 'evidence'
E.mkdir(exist_ok=True)
def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(args, name, cwd=ROOT, timeout=600, extra_env=None):
    start = time.perf_counter()
    started_at = datetime.now(timezone(timedelta(hours=7))).isoformat()
    env = {**os.environ, 'PYTHONIOENCODING':'utf-8', **(extra_env or {})}
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, encoding='utf-8', errors='replace', timeout=timeout, env=env)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = None, str(exc.stdout or ''), str(exc.stderr or '') + '\nTIMEOUT'
    except OSError as exc:
        code, stdout, stderr = None, '', repr(exc)
    record = {'command': args, 'cwd':str(cwd), 'started_at':started_at,'ended_at':datetime.now(timezone(timedelta(hours=7))).isoformat(),
              'duration_seconds':time.perf_counter()-start, 'exit_code':code, 'stdout':stdout, 'stderr':stderr}
    write(E / (name+'.json'), record)
    with (E/'verification_log.txt').open('a', encoding='utf-8') as log:
        log.write('\n'+json.dumps({k:v for k,v in record.items() if k not in ('stdout','stderr')}, ensure_ascii=False)+'\nSTDOUT\n'+stdout+'\nSTDERR\n'+stderr+'\n')
    return record

def snapshot():
    from music_ir.data import load_docs, corpus_hash
    from music_ir.engine import load_config
    paths = [*ROOT.glob('music_ir/*.py'), *ROOT.glob('tests/*.py'), *ROOT.glob('frontend/src/*'), *ROOT.glob('frontend/tests/*'),
             *ROOT.glob('evaluation/*'), ROOT/'config.json', ROOT/'run.ps1', ROOT/'pyproject.toml', ROOT/'requirements.lock.txt',
             ROOT/'frontend/package.json',ROOT/'frontend/package-lock.json',ROOT/'frontend/vite.config.ts',ROOT/'frontend/playwright.config.ts',
             *ROOT.glob('data/processed/*'), *ROOT.glob('data/raw/*'), *ROOT.glob('artifacts/semantic/*.json'),
             ROOT/'artifacts/semantic/vectors.npy', *ROOT.glob('artifacts/benchmark/*')]
    hashes = {str(p.relative_to(ROOT)).replace('\\','/'):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths if p.is_file()}
    snap = {'root':str(ROOT), 'audit_start':'2026-11-22T16:25:21+07:00', 'snapshot_at':datetime.now(timezone(timedelta(hours=7))).isoformat(),
            'timezone':'Asia/Jakarta','commit':run(['git','rev-parse','HEAD'],'git_head')['stdout'].strip(),
            'git_status':run(['git','status','--porcelain=v1','--untracked-files=all'],'git_status_before')['stdout'],
            'original_git_status_before_creating_audit_folder':'clean (git status --short at 16:25 WIB)',
            'hashes':hashes,'corpus_identity':corpus_hash(load_docs())}
    write(E/'snapshot_before.json',snap)
    # Source references can be inspected in the ZIP without distributing the full corpus.
    for rel in hashes:
        if rel.startswith(('music_ir/','tests/','frontend/src/','frontend/tests/','evaluation/')) or rel in ('config.json','run.ps1','pyproject.toml','requirements.lock.txt','frontend/package.json','frontend/package-lock.json','frontend/vite.config.ts','frontend/playwright.config.ts'):
            if rel.endswith('artwork.json'): continue
            dest = E/'source'/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/rel,dest)
    shutil.copyfile(r'C:\Users\sumhel\Downloads\Prompt_Audit_Fakta_dan_Evaluasi_Music_IR.md', E/'audit_instructions.md')
    packages = {p.metadata['Name']:p.version for p in importlib.metadata.distributions()}
    runtime = {'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'machine':platform.machine(),
               'logical_cpus':os.cpu_count(),'packages_installed':dict(sorted(packages.items())),
               'process_environment_allowlist':{k:os.environ.get(k) for k in ['MUSIC_IR_BACKEND','MUSIC_IR_API','MUSIC_IR_TEST_ES','OMP_NUM_THREADS','MKL_NUM_THREADS']},
               'cim_probe':'Get-CimInstance Win32_OperatingSystem / Win32_Processor / Win32_VideoController: Access denied in sandbox',
               'physical_cpu_cores':None,'gpu_driver_inventory':None}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
            runtime['cpu_name']=winreg.QueryValueEx(k,'ProcessorNameString')[0].strip()
    except Exception as exc: runtime['cpu_name']=None; runtime['cpu_error']=str(exc)
    try:
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong), *[(k,ctypes.c_ulonglong) for k in ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended')]]
        m=Memory();m.length=ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)): raise OSError('GlobalMemoryStatusEx failed')
        runtime['ram_total_bytes']=m.total_phys;runtime['ram_available_bytes_at_snapshot']=m.avail_phys
    except Exception as exc: runtime['ram_total_bytes']=None;runtime['ram_error']=str(exc)
    try:
        import torch
        runtime['torch']={'version':torch.__version__,'cuda_available':torch.cuda.is_available(),'cuda_build':torch.version.cuda,
                          'threads_before_model':torch.get_num_threads(),'gpu_count':torch.cuda.device_count(),
                          'gpus':[{'name':torch.cuda.get_device_name(i),'vram_bytes':torch.cuda.get_device_properties(i).total_memory} for i in range(torch.cuda.device_count())]}
    except Exception as exc: runtime['torch_error']=repr(exc)
    write(E/'runtime.json',runtime)
    write(OUT/'config_snapshot.json',{'effective_for_audit_engine':load_config(),'backend':os.environ.get('MUSIC_IR_BACKEND','local'),
          'config_source':'config.json, load_config(); engine instance checked again in search run',
          'ui_request':{'endpoint':'/api/search','proxy_default':'http://127.0.0.1:8000/search','mode_default':'AUTO','top_k':30},
          'api_defaults':{'mode':'AUTO','top_k':10},'secrets_included':False})
    for args,name,cwd in [(['node','--version'],'node_version',ROOT),(['npm.cmd','--version'],'npm_version',ROOT),(['npm.cmd','ls','--depth=0','--json'],'frontend_installed',ROOT/'frontend'),(['netstat','-ano'],'netstat',ROOT)]:
        run(args,name,cwd=cwd)
    print('snapshot saved',OUT,flush=True)

def data_audit():
    from music_ir.data import load_docs, corpus_hash, prepare, NUMERIC, PLAYLIST
    docs=load_docs()
    recorded=json.loads((ROOT/'data/processed/audit.json').read_text(encoding='utf-8'))
    raw=list((ROOT/'data/raw').glob('*.csv'))
    source=next((p for p in raw if sha(p)==recorded['source_sha256']),None)
    if source is None: raise RuntimeError('Source matching processed audit SHA not found')
    with source.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);rows=list(reader);columns=reader.fieldnames
    groups=collections.Counter(r['track_id'] for r in rows)
    numeric={}
    for field in NUMERIC:
        vals=[d.get(field) for d in docs];valid=[v for v in vals if isinstance(v,(float,int)) and math.isfinite(v)]
        numeric[field]={'missing':sum(v is None for v in vals),'types':dict(collections.Counter(type(v).__name__ for v in vals)),
                        'min':min(valid) if valid else None,'max':max(valid) if valid else None,'finite_count':len(valid)}
    # Re-run the original offline merge into an audit-only directory, never data/processed.
    temp=OUT/'scratch'/'rebuild'
    fresh=prepare(source,temp/'processed')
    rebuilt=json.loads((temp/'processed/corpus.json').read_text(encoding='utf-8'))
    result={'active_file':'data/processed/corpus.json','source_file':str(source.relative_to(ROOT)).replace('\\','/'),
            'source_sha256':sha(source),'source_rows':len(rows),'source_columns':len(columns),'column_names':columns,
            'source_unique_ids':len(groups),'missing_id_rows':sum(not r['track_id'].strip() for r in rows),
            'non_spotify_format_id_rows':sum(not re.fullmatch(r'[A-Za-z0-9]{22}',r['track_id']) for r in rows),
            'identical_row_extra_occurrences':len(rows)-len({tuple(r.get(c) for c in columns) for r in rows}),
            'identical_row_groups':sum(n>1 for n in collections.Counter(tuple(r.get(c) for c in columns) for r in rows).values()),
            'repeated_id_extra_occurrences':len(rows)-len(groups),'repeated_id_groups':sum(v>1 for v in groups.values()),
            'active_documents':len(docs),'active_unique_ids':len({d['track_id'] for d in docs}),
            'active_corpus_identity':corpus_hash(docs),'rebuild_matches_active_docs':rebuilt==docs,'rebuild_audit':fresh,
            'lyrics_available':sum(bool(d['lyrics'].strip()) for d in docs),'without_lyrics':sum(not d['lyrics'].strip() for d in docs),
            'short_lyrics_definition':'nonempty lyrics with stripped character length <100',
            'short_lyrics_ids':[d['track_id'] for d in docs if d['lyrics'].strip() and len(d['lyrics'].strip())<100],
            'numeric':numeric,'active_fields':sorted(set().union(*(d.keys() for d in docs))),
            'genre_track_counts':dict(collections.Counter(g for d in docs for g in d.get('playlist_genre',[]))),
            'tracks_multiple_genres':sum(len(d.get('playlist_genre',[]))>1 for d in docs),
            'lyrics_match_status':dict(collections.Counter(d.get('lyrics_match_status') for d in docs)),
            'provenance':'raw SHA matches historical prepare metadata; collection method and recording-to-lyrics correctness not established'}
    write(E/'data_audit.json',result)
    # Purge only audit scratch copies with raw lyrics, after confirming containment.
    if temp.resolve().is_relative_to(OUT.resolve()): shutil.rmtree(temp)
    meta=json.loads((ROOT/'artifacts/semantic/metadata.json').read_text(encoding='utf-8'))
    import numpy as np
    a=np.load(ROOT/'artifacts/semantic/vectors.npy',allow_pickle=False)
    write(E/'embedding_audit.json',{'metadata':meta,'matrix_shape':list(a.shape),'matrix_dtype':str(a.dtype),
           'finite':bool(np.isfinite(a).all()),'norm_min':float(np.linalg.norm(a,axis=1).min()),'norm_max':float(np.linalg.norm(a,axis=1).max()),
           'metadata_corpus_matches_active':meta['corpus_sha256']==corpus_hash(docs),'ids_match_active_order':meta['track_ids']==[d['track_id'] for d in docs],
           'chunked_documents':len(meta['chunked_ids']),'artifact_origin_status':'historical metadata, matrix inspected during audit; corpus embedding NOT rebuilt'})
    print({k:result[k] for k in ['source_rows','source_columns','source_unique_ids','identical_row_extra_occurrences','repeated_id_extra_occurrences','lyrics_available','without_lyrics','rebuild_matches_active_docs']},flush=True)

def benchmark_audit():
    from music_ir.data import load_docs
    from music_ir.benchmark import BenchmarkStore
    docs=load_docs();store=BenchmarkStore(docs)
    qs=store.queries(); identity=store.identity()
    dbpath=ROOT/'artifacts/benchmark/reviews.sqlite3'
    db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    tables={r[0]:[dict(x) for x in db.execute('SELECT * FROM '+r[0])] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('judgments','reviews')")}
    db.close()
    # Do not publish annotator identities/notes; preserve anonymous counts.
    js=[x for x in tables.get('judgments',[]) if x['dataset']==identity]
    rs=[x for x in tables.get('reviews',[]) if x['dataset']==identity]
    pools=json.loads((ROOT/'artifacts/benchmark/pool.json').read_text(encoding='utf-8'))
    pairs=collections.defaultdict(set)
    for j in js: pairs[j['query_id'],j['track_id']].add(j['grade'])
    groups=collections.defaultdict(set)
    for q in qs: groups[q['group_id']].add(q['split'])
    result={'dataset_identity':identity,'queries_total':len(qs),'raw_review_status':dict(collections.Counter(q.get('review_status') for q in qs)),
            'approved_query_ids_from_db':sorted({r['query_id'] for r in rs}),'query_category':dict(collections.Counter(q['category'] for q in qs)),
            'split_counts':dict(collections.Counter(q['split'] for q in qs)), 'category_split':dict(collections.Counter(q['category']+'/'+q['split'] for q in qs)),
            'sources':dict(collections.Counter(q.get('source') for q in qs)), 'group_ids_crossing_splits':{k:sorted(v) for k,v in groups.items() if len(v)>1},
            'judgment_records_active':len(js),'judged_pairs_active':len(pairs),'queries_with_judgment':len({k[0] for k in pairs}),
            'queries_with_grade_ge2':len({k[0] for k,v in pairs.items() if any(g>=2 for g in v)}),
            'annotator_count_active':len({x['annotator'] for x in js}),'pairs_multiple_annotators':sum(sum(j['query_id']==k[0] and j['track_id']==k[1] for j in js)>1 for k in pairs),
            'conflicting_pairs':sum(len(v)>1 for v in pairs.values()),
            'records_all_dataset_identities':{k:len(v) for k,v in tables.items()},'pool_identity_matches':pools.get('dataset')==identity,
            'historical_pool_queries':len(pools.get('queries',{})),
            'historical_pool_metadata':[{k:v for k,v in p.items() if k not in ('track_ids',)} for p in pools.get('queries',{}).values()],
            'qrels_template_data_rows':len(list(csv.DictReader((ROOT/'evaluation/qrels.template.csv').open(encoding='utf-8-sig')))),
            'evaluation_ready':False if not pairs else None,'effectiveness':{'ndcg@10':None,'mrr@10':None,'recall@100':None},
            'reason':'Human qrels must be reviewed and eligible; no labels are inferred from hints or retrieval.'}
    write(E/'benchmark_audit.json',result)
    write(E/'retrieval_metrics_summary.json',{'status':'not_evaluated','metrics':result['effectiveness'],'reason':result['reason'],'human_judgment_records':len(js)})
    print({k:result[k] for k in ['queries_total','split_counts','judgment_records_active','queries_with_judgment','annotator_count_active','approved_query_ids_from_db']},flush=True)

if __name__=='__main__':
    {'snapshot':snapshot,'data':data_audit,'benchmark':benchmark_audit}[sys.argv[1]]()
