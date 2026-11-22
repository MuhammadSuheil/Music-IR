import json,csv,re,sys,sqlite3,hashlib,zipfile,collections,subprocess,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path
from audit_collect import ROOT,OUT,E,sha,write,run

def polish_report():
    p=OUT/'FAKTA_PROYEK_MUSIC_IR.md';text=p.read_text(encoding='utf-8')
    terms={
      'Labelplaylist':'Label playlist','direktorioutput':'direktori output','groundtruth':'ground truth','infrastrukturindeks':'infrastruktur indeks',
      'UIunit':'UI unit','cachehangat':'cache hangat','ataupuncoldcacheterkontrol':'ataupun cold cache terkontrol','renderPNGMermaid':'render PNG Mermaid',
      'RawCSV':'Raw CSV','corpusJSON':'corpus JSON','modelweights':'model weights','virtualenvironment':'virtual environment','lewatSHA':'lewat SHA',
      'snapshotakhir':'snapshot akhir','vectorcachelokal':'vector cache lokal','filecachetidak':'file cache tidak','cachelokal':'cache lokal',
      'IDnaik':'ID naik','IDkandidat':'ID kandidat','setID':'set ID','trackIDjuga':'track ID juga','fieldbaru':'field baru','keybaru':'key baru',
      'batch4':'batch 4','pipeline;source':'pipeline; source','dokumen/candidate-recall':'dokumen/recall kandidat',
      'networks':'networks','sampelcorpus':'sampel corpus','top-depth':'top-depth','RawCSV':'Raw CSV','hotcache':'hot cache',
      'faultinjection':'fault injection','librarymodel':'library model','Katalogexact':'Katalog exact',
      'cachemiss':'cache miss','cachehit':'cache hit','coldcache':'cold cache','miss/hitbagian':'miss/hit bagian',
      'null;tidak':'null; tidak','secaraindependen':'secara independen','berdasarkanlabel':'berdasarkan label',
      'Setiaprequest':'Setiap request','danNone':'dan None','semuaquery':'semua query','webserver':'webserver',
      'datacorpus':'data corpus','namafile':'nama file','Corpusaktif':'Corpus aktif','ranked_cosine':'ranked_cosine',
      'HTTPdan':'HTTP dan','screenshotdan':'screenshot dan','querydan':'query dan','querydengan':'query dengan',
      'candidate-recall':'recall kandidat','sebagaiinput':'sebagai input','matrixshape':'matrix shape',
      'sinkronisasiCUDA':'sinkronisasi CUDA','timingGPUyang':'timing GPU yang','ke13':'ke-13',
      'moodaudio':'mood audio','masing-masinguntuk':'masing-masing untuk','rankID':'rank ID',
    }
    # Apply readable spacing only outside fenced/inline code so IDs, hashes and paths remain exact.
    fence=False;lines=[]
    for line in text.splitlines():
        if line.startswith('```'):fence=not fence;lines.append(line);continue
        if fence:lines.append(line);continue
        parts=re.split(r'(`[^`]*`)',line)
        for n,part in enumerate(parts):
            if n%2:continue
            part=re.sub(r'(?<=\d)(?=[A-Za-z]{2,})',' ',part)
            part=re.sub(r'\b([A-Za-z]{3,})(?=\d)',lambda m:m.group(0) if m.group(0).lower() in {'float','int','uint'} else m.group(0)+' ',part)
            for a,b in terms.items():part=part.replace(a,b)
            parts[n]=part
        lines.append(''.join(parts))
    text='\n'.join(lines)+'\n'
    start=text.index('| Pernyataan calon laporan |');end=text.index('\nIndeks bukti utama:',start)
    finaltable='''| Pernyataan calon laporan | Dasar bukti | Status | Batas kesimpulan | Bagian laporan yang sesuai |
| --- | --- | --- | --- | --- |
| Sistem memakai BM25 lokal, embedding pretrained, dan aturan intent kondisional | CLM-002/004/005; tabel pipeline | EKSEKUSI | Sumber retrieval bergantung query; bukan LLM generatif atau agentic runtime | Bab 3 |
| Corpus 1.686 baris menjadi 1.437 lagu unik; 1.404 memiliki lirik | CLM-003 | EKSEKUSI | Cakupan lirik belum memverifikasi pasangan rekaman | Bab 3/4 |
| Inferensi BGE-M3 memakai CPU float32; matriks 1.437 × 1.024 | CLM-004/021 | EKSEKUSI | Matriks historis diperiksa, tidak dibangun ulang; bukan training | Bab 3/4 |
| AUTO memiliki kebijakan tambahan dibanding E5 | CLM-006/010 | EKSEKUSI/kode | Tidak berarti lebih relevan dari E5 | Bab 3/4 |
| Perhitungan kontribusi skor dapat direproduksi | CLM-007 | EKSEKUSI | Skor bukan probabilitas; bonus dapat membuat skor >1 | Bab 4 |
| Backend: 88 lulus dan 5 skipped; UI: 15 lulus | CLM-008/009 | EKSEKUSI | Jelaskan fixture, mocking, dan layanan yang tidak diuji; bukan metrik retrieval | Bab 4 |
| 51 kasus HTTP dan 4 screenshot menunjukkan perilaku pada snapshot audit | CLM-010/019 | EKSEKUSI | Kasus pengembangan/regresi bukan uji relevansi independen | Bab 4 |
| Latensi diukur pada 6 query, 180 observasi, dan 60 warm-up | CLM-013 | EKSEKUSI | Terbatas pada mesin, subset, dan cache ini | Bab 4 |
| Efektivitas retrieval belum dapat dihitung | CLM-011/012/022 | BELUM TERVERIFIKASI untuk efektivitas | nDCG/MRR/Recall=null; tidak menyimpulkan keunggulan metode | Bab 4/kesimpulan |
| Lembar anotasi manusia telah disiapkan | CLM-016 | EKSEKUSI | 191 pasangan/10 query belum dinilai; 150 query belum dipool | Pekerjaan lanjutan/kesimpulan |
| Evaluator belum mencatat incomplete ketika query gagal | CLM-015 | EKSEKUSI fixture | Perlu perbaikan terpisah; bukan kegagalan run penelitian | Batasan/kesimpulan |
'''
    text=text[:start]+finaltable+text[end:]
    p.write_text(text,encoding='utf-8')

def snapshot_after():
    from music_ir.data import load_docs,corpus_hash
    from music_ir.benchmark import BenchmarkStore
    from audit_search import cache_stats
    before=json.loads((E/'snapshot_before.json').read_text(encoding='utf-8'));results={};changed=[];protected=[]
    for rel,rec in before['hashes'].items():
        p=ROOT/rel;new=sha(p) if p.exists() else None
        same=new==rec['sha256'];results[rel]={'before_sha256':rec['sha256'],'after_sha256':new,'unchanged':same}
        if not same:changed.append(rel)
        if rel.startswith(('music_ir/','tests/','frontend/src/','frontend/tests/','evaluation/','data/')) or rel in ['config.json','pyproject.toml','run.ps1','frontend/package.json','frontend/package-lock.json','frontend/vite.config.ts','frontend/playwright.config.ts','requirements.lock.txt']:protected.append(rel)
    status=run(['git','status','--porcelain=v1','--untracked-files=normal'],'git_status_after')
    diff=run(['git','diff','--exit-code'],'git_diff_after')
    staged=run(['git','diff','--cached','--exit-code'],'git_cached_diff_after')
    from music_ir.benchmark import BenchmarkStore
    identity=BenchmarkStore(load_docs()).identity()
    with sqlite3.connect((ROOT/'artifacts/benchmark/reviews.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        judgments=db.execute('SELECT COUNT(*) FROM judgments WHERE dataset=?',(identity,)).fetchone()[0]
        reviews=db.execute('SELECT COUNT(*) FROM reviews WHERE dataset=?',(identity,)).fetchone()[0]
    write(E/'snapshot_after.json',{'at':datetime.now(timezone(timedelta(hours=7))).isoformat(),'commit':before['commit'],'files':results,
         'protected_inputs':protected,'protected_input_changes':[p for p in protected if not results[p]['unchanged']],
         'all_observed_changed_inputs':changed,'git_tracked_diff_exit':diff['exit_code'],'git_staged_diff_exit':staged['exit_code'],'git_status':status['stdout'],
         'active_corpus_identity':corpus_hash(load_docs()),'normal_passage_cache_after_all_runs':cache_stats(),
         'human_judgments_after':judgments,'human_reviews_after':reviews,'notes':'Audit files are new; frontend dist build may change ignored generated output. No source/config/corpus/judgments modified. Passage cache writes, if any, are normal application inference writes.'})
    return not any(not results[p]['unchanged'] for p in protected) and diff['exit_code']==0 and staged['exit_code']==0

def logs():
    records=[]
    for p in E.glob('*.json'):
        try:r=json.loads(p.read_text(encoding='utf-8'))
        except Exception:continue
        if isinstance(r,dict) and all(k in r for k in ['command','stdout','stderr','duration_seconds']):records.append((p.name,r))
    records.sort(key=lambda x:x[1].get('started_at',''))
    with (E/'verification_log.txt').open('w',encoding='utf-8') as f:
        f.write('Audit Music IR: complete captured command outputs. Environment: runtime.json. Some initial command starts reconstructed from end minus duration; see audit_tool_notes.json. Unrelated netstat output removed for privacy.\n')
        for name,r in records:
            f.write('\nRECORD '+name+'\n'+json.dumps({k:v for k,v in r.items() if k not in ['stdout','stderr']},ensure_ascii=False)+'\nSTDOUT\n'+r['stdout']+'\nSTDERR\n'+r['stderr']+'\n')
        f.write('\nADDITIONAL PROCEDURES\n')
        f.write('audit_search.py plan; audit_search.py cases: frozen 51-case plan and all actual HTTP responses/timings in cases.jsonl and search_traces.jsonl. Whole script duration not separately measured.\n')
        f.write('audit_verify.py fixtures: manual metric fixture; injected evaluator failure; additional case assertions and eight independent score calculations. Results in corresponding JSON files.\n')
        f.write('audit_tokenizer.py: local pinned tokenizer across 1437 serialized docs, max content tokens2217, would chunk0. Actual output captured in tokenization_audit.json; no corpus embedding build.\n')
        f.write('audit_supplement.py: actual lock/installed comparison, query independence inspection, read_benchmark eligibility rejection, cache config identity.\n')

def validate():
    errors=[];json_count=0
    for p in OUT.rglob('*.json'):
        if '__pycache__' in p.parts:continue
        try:json.loads(p.read_text(encoding='utf-8'));json_count+=1
        except Exception as exc:errors.append({'file':str(p.relative_to(OUT)),'error':repr(exc)})
    claims=json.loads((E/'claims.json').read_text(encoding='utf-8'))
    for c in claims:
        if not (OUT/c['evidence_file']).is_file():errors.append({'missing_claim_file':c['evidence_file']})
    md=(OUT/'FAKTA_PROYEK_MUSIC_IR.md').read_text(encoding='utf-8')
    for link in re.findall(r'\]\(([^)]+)\)',md):
        if link.startswith(('http:','https:','#')):continue
        if not (OUT/link).is_file() and link!='evidence/package_manifest.json':errors.append({'missing_markdown_target':link})
    with (E/'annotation_needed.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    if any(r['relevance'] or r['annotator_code'] for r in rows):errors.append({'annotation':'grade or annotator not blank'})
    if any('score' in k.lower() or 'mode' in k.lower() for k in fields):errors.append({'annotation':'mode or score exposed'})
    if len(rows)!=191:errors.append({'annotation_count':len(rows)})
    if len(re.findall(r'^## \d+\.',md,re.M))!=12:errors.append({'report':'not 12 sections'})
    if json.loads((E/'snapshot_after.json').read_text(encoding='utf-8'))['protected_input_changes']:errors.append({'protected_inputs':'changed'})
    write(E/'delivery_validation.json',{'json_files_parsed':json_count,'claim_records':len(claims),'markdown_links_checked':True,'annotation_rows':len(rows),'annotation_grades_blank':True,
         'report_required_sections':12,'errors':errors,'passed':not errors,'note':'Mechanical consistency checks; does not certify retrieval effectiveness or complete external-service coverage'})
    if errors:raise RuntimeError(errors)

def package():
    def selected():
        return sorted(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'scratch' not in p.relative_to(OUT).parts)
    files=[{'path':str(p.relative_to(OUT)).replace('\\','/'),'bytes':p.stat().st_size,'sha256':sha(p)} for p in selected() if p!=E/'package_manifest.json']
    write(E/'package_manifest.json',{'created_at':datetime.now(timezone(timedelta(hours=7))).isoformat(),'files':files,
       'self_hash_omitted':True,'excluded':'__pycache__, scratch, original raw/full corpus, model weights, embeddings, caches, node_modules, virtual environments',
       'raw_data_included':False,'full_lyrics_corpus_included':False})
    target=ROOT/('PAKET_FAKTA_MUSIC_IR_'+OUT.name.removeprefix('audit_music_ir_')+'.zip')
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in selected():z.write(p,str(Path(OUT.name)/p.relative_to(OUT)))
    with zipfile.ZipFile(target) as z:
        bad=z.testzip()
        if bad:raise RuntimeError('ZIP CRC failure '+bad)
        names=z.namelist()
    print(json.dumps({'markdown':str(OUT/'FAKTA_PROYEK_MUSIC_IR.md'),'zip':str(target),'zip_bytes':target.stat().st_size,'zip_sha256':sha(target),'zip_files':len(names),'CRC':'passed'},ensure_ascii=False),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='stop-services-safer':
        # IDs verified from our server startup log and listener PID/start time (16:29:14), respectively.
        command="foreach ($taskAuditPid in @(32676,28504)) { $taskAuditProcess = Get-Process -Id $taskAuditPid -ErrorAction SilentlyContinue; if ($taskAuditProcess) { Stop-Process -Id $taskAuditPid -ErrorAction Stop; Write-Output ('Stopped owned audit service ' + $taskAuditPid) } else { Write-Output ('Owned audit service already exited ' + $taskAuditPid) } }"
        result=run(['powershell.exe','-NoProfile','-Command',command],'services_teardown_powershell',timeout=20)
        print(result['exit_code'],result['stdout'],result['stderr'],flush=True)
    elif sys.argv[1]=='stop-services':
        for name in ['api_observed','ui']:
            record=json.loads((E/(name+'_service.json')).read_text(encoding='utf-8'))
            result=run(['taskkill','/PID',str(record['pid']),'/T','/F'],name+'_teardown',timeout=20)
            print(name,result['exit_code'],result['stdout'],result['stderr'],flush=True)
    elif sys.argv[1]=='snapshot':print('protected inputs unchanged:',snapshot_after(),flush=True)
    elif sys.argv[1]=='package':polish_report();logs();validate();package()
