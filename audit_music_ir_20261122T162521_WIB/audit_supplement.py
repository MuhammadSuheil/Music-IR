import json,csv,hashlib,collections,re,shutil,subprocess,sys
from datetime import datetime,timedelta
from pathlib import Path
from audit_collect import ROOT,OUT,E,write,sha,run
from music_ir.data import load_docs,tokens,corpus_hash,normalize
from music_ir.benchmark import BenchmarkStore

def supplements():
    docs=load_docs();qs=BenchmarkStore(docs).queries();groups=collections.defaultdict(set);texts=collections.defaultdict(list);exact=collections.defaultdict(list);hints=collections.defaultdict(set)
    for q in qs:
        groups[q['group_id']].add(q['split']);texts[' '.join(tokens(q['query']))].append(q)
        exact[normalize(q['query']).casefold()].append(q)
        for t in q.get('hint_track_ids',[]):hints[t].add(q['split'])
    from scripts.check_search_cases import CASES
    normalized={' '.join(tokens(q)) for q in CASES}
    write(E/'query_independence.json',{'group_count':len(groups),'group_cross_split':{k:sorted(v) for k,v in groups.items() if len(v)>1},
          'exact_normalized_query_duplicates':[{ 'text':k,'query_ids':[q['query_id'] for q in v],'splits':sorted({q['split'] for q in v})} for k,v in exact.items() if len(v)>1],
          'token_only_collisions_not_equivalent_queries':[{ 'text':k,'queries':[{'query_id':q['query_id'],'query':q['query'],'split':q['split']} for q in v]} for k,v in texts.items() if len(v)>1],
          'hint_track_ids_cross_split':{k:sorted(v) for k,v in hints.items() if len(v)>1},
          'exact_normalized_overlap_with_current_regression_cases':[q['query_id'] for q in qs if ' '.join(tokens(q['query'])) in normalized],
          'development_history':'Full authoring/tuning chronology unavailable; structural split checks do not establish independence from rule development'})
    runtime=json.loads((E/'runtime.json').read_text(encoding='utf-8'));installed={k.lower():v for k,v in runtime['packages_installed'].items()}
    locked={}
    for line in (ROOT/'requirements.lock.txt').read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.startswith('#') and '==' in line:
            k,v=line.split('==',1);locked[k.lower()]=v
    front=json.loads(json.loads((E/'frontend_installed.json').read_text(encoding='utf-8'))['stdout'])['dependencies']
    lock=json.loads((ROOT/'frontend/package-lock.json').read_text(encoding='utf-8'))
    pkg=json.loads((ROOT/'frontend/package.json').read_text(encoding='utf-8'))
    frows=[]
    for k,v in {**pkg['dependencies'],**pkg['devDependencies']}.items():
        frows.append({'name':k,'declared':v,'lockfile':lock['packages'].get('node_modules/'+k,{}).get('version'), 'installed':front.get(k,{}).get('version')})
    write(E/'dependency_comparison.json',{'backend_lock_packages':len(locked),'backend_lock_vs_installed':[{ 'name':k,'locked':v,'installed':installed.get(k),'matches':installed.get(k)==v} for k,v in locked.items()],
          'frontend':frows,'declared_backend':'evidence/source/pyproject.toml','installed_inventory':'runtime.json; frontend_installed.json','node':json.loads((E/'node_version.json').read_text())['stdout'].strip(),'npm':json.loads((E/'npm_version.json').read_text())['stdout'].strip()})
    model_dir=ROOT/'.cache/huggingface/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181'
    write(E/'model_cache_manifest.json',{'revision_directory':str(model_dir.relative_to(ROOT)).replace('\\','/'),'small_configuration_files':[
         {'relative_path':str(p.relative_to(model_dir)).replace('\\','/'),'sha256':sha(p),'bytes':p.stat().st_size} for p in model_dir.rglob('*') if p.is_file() and p.suffix=='.json'],
         'weights_included':False,'cache_exists':model_dir.exists(),'revision_selection':'SentenceTransformer receives the pinned revision and local_files_only=True in online warmup'})
    for rel in ['README.md','docs/REVISI_LAPORAN_MUSIC_IR.md','scripts/check_search_cases.py','compose.yaml']:
        dest=E/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dest)
    write(E/'historical_reference.json',{'status':'historical_only','code_reference':'evidence/source/docs/REVISI_LAPORAN_MUSIC_IR.md:449',
          'historical_claims':{'sad_cache_miss_engine_ms':37606.82,'sad_cache_hit_engine_ms':662.48},
          'warning':'Copied only as document comparison; these are NOT audit rerun measurements and no general speedup ratio is inferred',
          'tuning_trial_files_found':[str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'artifacts').rglob('*trials*') if p.is_file()]})
    data=json.loads((E/'data_audit.json').read_text(encoding='utf-8'))
    data['rebuild_audit']['source_snapshot_included']=False
    data['rebuild_audit']['source_snapshot_note']='Temporary audit-only raw copy removed after comparing rebuilt docs; raw corpus/lyrics intentionally excluded from ZIP, original source identified by SHA'
    write(E/'data_audit.json',data)
    cfg=json.loads((OUT/'config_snapshot.json').read_text(encoding='utf-8'));engine=json.loads((E/'runtime_engine.json').read_text(encoding='utf-8'))
    cfg['observed_runtime']=engine['after'];cfg['runtime_config_matches_file']=cfg['effective_for_audit_engine']==engine['after']['effective_config']
    write(OUT/'config_snapshot.json',cfg)
    from music_ir.evaluate import read_benchmark
    try:read_benchmark(ROOT/'evaluation/queries.draft.jsonl',ROOT/'evaluation/qrels.template.csv',docs,required_split='test');error=None
    except Exception as exc:error=repr(exc)
    write(E/'evaluation_eligibility_check.json',{'procedure':'read_benchmark(actual queries.draft.jsonl, actual qrels.template.csv, active docs, required_split=test)','exception':error,
          'relevance_run_executed':False,'reason':'The benchmark validation rejects draft/unjudged real queries; no semantic effectiveness computed'})
    # Repair audit-tool timestamp labels without changing command output.
    migrated=[]
    for p in E.glob('*.json'):
        try:record=json.loads(p.read_text(encoding='utf-8'))
        except Exception:continue
        if not isinstance(record,dict) or not all(k in record for k in ['command','started_at','duration_seconds','stdout','stderr']):continue
        if 'ended_at' not in record:
            record['ended_at']=record['started_at']
            record['started_at']=(datetime.fromisoformat(record['ended_at'])-timedelta(seconds=record['duration_seconds'])).isoformat()
            record['start_time_method']='reconstructed from completion timestamp minus measured perf_counter duration; original collector mislabeled end as start'
            write(p,record);migrated.append(p.name)
        elif 'start_time_method' in record:
            migrated.append(p.name)
    net=json.loads((E/'netstat.json').read_text(encoding='utf-8'))
    lines=[l for l in net['stdout'].splitlines() if re.search(r':(?:8000|8501|9200)\s',l) and 'LISTENING' in l]
    net['stdout']='\n'.join(lines);net['privacy_filter']='Output retained only for local listening ports 8000,8501,9200; unrelated network addresses omitted'
    write(E/'netstat.json',net)
    write(E/'audit_tool_notes.json',{'timestamp_label_normalized_files':migrated,'application_changes':False,
         'initial_build_collector_print_error':'cp1252 stdout could not print a Vite checkmark after successful command exit0; complete build output already persisted in frontend_build.json; audit stdout encoding fixed thereafter',
         'initial_hardware_probe':'CIM access denied; registry and GlobalMemoryStatusEx succeeded; no escalation requested',
         'renderer_probe':{'mermaid_module':(ROOT/'frontend/node_modules/mermaid').exists(),'mermaid_cli_module':(ROOT/'frontend/node_modules/@mermaid-js/mermaid-cli').exists(),'system_mmdc':shutil.which('mmdc'),'system_dot':shutil.which('dot')},
         'audit_asgi_wrapper':'Read-only /_audit/runtime endpoint in separate audit_live_api.py used around original app; does not mutate engine/config/search functions',
         'case_command':[sys.executable,str(OUT/'audit_search.py'),'cases'],'case_duration_source':'per-request HTTP timings; full script duration not measured separately',
         'fixture_command':[sys.executable,str(OUT/'audit_verify.py'),'fixtures']})
    print('supplements captured',flush=True)

if __name__=='__main__': supplements()
