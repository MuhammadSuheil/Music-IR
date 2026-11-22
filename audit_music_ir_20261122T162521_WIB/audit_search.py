import csv, json, math, random, time, urllib.request, urllib.error, statistics, sqlite3, collections, sys
from audit_collect import ROOT,OUT,E,write,sha
from music_ir.data import load_docs

BASE='http://127.0.0.1:8000'
docs=load_docs(); byid={d['track_id']:d for d in docs}
MODES=['E1','E2','E3','E4','E5','AUTO']
def request(payload,timeout=300):
    req=urllib.request.Request(BASE+'/search', data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    start=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=timeout) as f:
            raw=f.read();elapsed=(time.perf_counter()-start)*1000;status=f.status
        return {'status':status,'http_ms':elapsed,'response':json.loads(raw)}
    except urllib.error.HTTPError as exc:
        raw=exc.read()
        return {'status':exc.code,'http_ms':(time.perf_counter()-start)*1000,'response':json.loads(raw)}
    except Exception as exc: return {'status':None,'http_ms':(time.perf_counter()-start)*1000,'error':repr(exc)}
def emit(path,row):
    with path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
def cache_stats():
    p=ROOT/'artifacts/semantic/passages.sqlite3'
    if not p.exists(): return {'entries':0}
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db: n=db.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]
    return {'entries':n,'sha256':sha(p),'bytes':p.stat().st_size}

def plan():
    from scripts.check_search_cases import CASES
    cases=[]
    for i,q in enumerate(CASES,1): cases.append({'case_id':f'REG-{i:02}','query':q,'mode':'AUTO','origin':'development/regression: scripts/check_search_cases.py','expected':'existing verify(number,response) functional assertions','verify_number':i})
    extras=[('TITLE','Die With A Smile','AUTO','Exact catalog title'),('COLLAB','Lady Gaga','AUTO','Catalog artist including collaboration'),
      ('LYRIC','lirik "I just woke up from a dream"','AUTO','Literal contiguous lyric evidence'),
      ('AUDIO','tempo > 120 BPM','AUTO','All displayed tempo >120; indicator 1'),
      ('PREF','energi rendah','AUTO','Low-energy midrank percentile preference'),
      ('MULTI','tempo >= 120 BPM dan energi < 0,5','AUTO','Intersection of explicit bounds'),
      ('BOUND','tempo = '+str(docs[0]['tempo'])+' BPM','AUTO','Exact boundary operator'),
      ('MIXED','Bruno Mars dengan tempo > 120 BPM','AUTO','Artist match AND audio constraint'),
      ('MIXTEXT','leaving memories dengan energi rendah','AUTO','Text and corpus-wide audio candidate union'),
      ('EMPTYRESULT','tempo > 999 BPM','AUTO','No eligible documents'),
      ('CONTRADICT','tempo > 120 BPM dan tempo < 90 BPM','AUTO','No eligible documents'),
      ('UNKNOWN','artis qzxnonexistent','AUTO','Empty catalog artist match'),
      ('UNICODE','Ｄｉｅ With A Smile','AUTO','NFKC title normalization'),
      ('NOLYRICS',next(d['track_name'] for d in docs if not d['lyrics_available']),'AUTO','Track without lyrics remains retrievable by title'),
      ('EMPTY','','AUTO','API validation 422'),('WHITESPACE','   ','AUTO','Parser validation 422'),
      ('BADBOUND','energi > 2','AUTO','Audio input rejected 422'),('MOODAUDIO','lagu sedih','AUTO','Audio mood basis, no text encoder')]
    for cid,q,m,exp in extras: cases.append({'case_id':cid,'query':q,'mode':m,'origin':'audit-authored functional probe; not an independent relevance judgment','expected':exp,**({'mood_basis':'audio'} if cid=='MOODAUDIO' else {})})
    for i,q in enumerate(['Stay','I just woke up from a dream','leaving memories dengan energi rendah','tempo > 120 BPM']):
        for m in MODES: cases.append({'case_id':f'MODE-{i}-{m}','query':q,'mode':m,'origin':'audit comparison/regression probes','expected':'same set E3/E4; E4=E5 without audio; different AUTO policy allowed'})
    with (E/'cases.jsonl').open('w',encoding='utf-8') as f:
        for c in cases: f.write(json.dumps(c,ensure_ascii=False)+'\n')
    subset=[{'query_id':cid,'query':q,'category':cat} for cid,q,cat in [
       ('L-title','Die With A Smile','title'),('L-artist','Bruno Mars','artist'),('L-lyrics','I just woke up from a dream','lyrics'),
       ('L-theme','lagu bermakna cinta','semantic'),('L-audio','tempo > 120 BPM','audio'),('L-mixed','leaving memories dengan energi rendah','mixed')]]
    write(E/'latency_plan.json',{'frozen_before_run':True,'queries':subset,'modes':MODES,'warmups_per_mode':10,'repeats_per_query_mode':5,
        'seed':42,'top_k':30,'trace':True,'active_requests':1,'boundary':'perf_counter immediately before urllib.urlopen until response bytes fully read; excludes JSON decode and file writing',
        'engine_boundary':'response latency_ms excludes explicit semantic warmup/model loading; excludes diagnostics, JSON serialization, network; includes formatting reasons',
        'cache_policy':'existing user caches retained; no response cache in code; passage cache grows normally; no controlled cold cache; warmups excluded from statistics'})
    qs=[json.loads(x) for x in (ROOT/'evaluation/queries.draft.jsonl').read_text(encoding='utf-8').splitlines() if x]
    selected=[]
    for category in ['title','artist','lyrics','semantic','audio']:
        for split in ['dev','test']:
            selected.append(next(q for q in qs if q['category']==category and q['split']==split))
    write(E/'annotation_pool_plan.json',{'query_ids':[q['query_id'] for q in selected],'modes':MODES,'depth':10,'ranking_object':'primary results only; related in separate traces','selection':'first query of each category and split in actual draft file; frozen before run','all_other_queries':'review checklist supplied; candidates not generated for them during audit'})
    print('frozen',len(cases),'cases; 6 latency queries; 10 annotation queries',flush=True)

def cases():
    from scripts.check_search_cases import verify
    before=cache_stats(); results=[]; formula=[]
    for line in (E/'cases.jsonl').read_text(encoding='utf-8').splitlines():
        case=json.loads(line);payload={'query':case['query'],'mode':case['mode'],'top_k':30,'trace':True}
        if case.get('mood_basis'):payload['mood_basis']=case['mood_basis']
        row={'case_id':case['case_id'],'payload':payload,**request(payload)}
        data=row.get('response',{}); checks=[]
        if row['status']==200:
            both=data['results']+data.get('related_results',[])
            checks += [('unique_display_ids',len({x['track_id'] for x in both})==len(both)),('top_k_bound',len(both)<=30)]
            if data['pipeline']['audio']:
                for field,op,bound in data['constraints']:
                    def passed(d):
                        v=d.get(field)
                        return v is not None and {'>':lambda:v>bound,'<':lambda:v<bound,'>=':lambda:v>=bound,'<=':lambda:v<=bound,'=':lambda:v==bound,'!=':lambda:v!=bound}[op]()
                    checks.append(('audio_constraint_'+field+op+str(bound),all(passed(byid[x['track_id']]) for x in both)))
            if case.get('verify_number'):
                try:verify(case['verify_number'],data);checks.append(('existing_regression_assertions',True))
                except Exception as exc:checks.append(('existing_regression_assertions',False));row['assertion_error']=repr(exc)
            for c in data['trace']['decisions']['candidates']:
                if c['final_rank'] is None:continue
                computed=sum(c['contributions'].values()); err=abs(computed-c['score'])
                rrf=sum(1/(60+r) for r in c['sources'].values())
                formula.append({'case_id':case['case_id'],'mode':case['mode'],'track_id':c['track_id'],'query_type':data['query_type'],
                                'contributions':c['contributions'],'features':c['features'],'raw_scores':c['raw_scores'],'sources':c['sources'],
                                'final_score':c['score'],'sum_contributions':computed,'absolute_error':err,'rrf_recomputed':rrf,
                                'rrf_error':abs(rrf-c['raw_scores']['rrf']),'tolerance':1e-8,'passed':err<=1e-8 and abs(rrf-c['raw_scores']['rrf'])<=1e-8})
            if case['case_id'] in ['EMPTYRESULT','CONTRADICT','UNKNOWN']:checks.append(('empty_expected',not both))
            row['checks']=dict(checks);row['functional_status']='pass' if all(v for _,v in checks) else 'fail'
        else:
            row['functional_status']='pass' if case['case_id'] in ['EMPTY','WHITESPACE','BADBOUND'] and row['status']==422 else 'error'
        emit(E/'search_traces.jsonl',row)
        summary={k:v for k,v in row.items() if k not in ['response']}
        summary.update(query_type=data.get('query_type'),primary_ids=[x['track_id'] for x in data.get('results',[])],related_ids=[x['track_id'] for x in data.get('related_results',[])],
                       primary_count=len(data.get('results',[])),related_count=len(data.get('related_results',[])),pipeline=data.get('pipeline'),warnings=data.get('warnings'))
        results.append(summary);print(case['case_id'],row['status'],row['functional_status'],round(row['http_ms'],1),data.get('query_type'),flush=True)
    write(E/'case_results.json',results);write(E/'score_verification.json',{'tolerance':1e-8,'checks':formula,'all_passed':all(x['passed'] for x in formula)})
    comparisons=[]
    traces=[json.loads(l) for l in (E/'search_traces.jsonl').read_text(encoding='utf-8').splitlines()]
    for i in range(4):
        rows={r['payload']['mode']:r for r in traces if r['case_id'].startswith(f'MODE-{i}-')}
        valid=all(r['status']==200 for r in rows.values())
        comparisons.append({'query':rows['E3']['payload']['query'],'all_modes_executed':valid,
            'e3_e4_same_candidate_set':set(rows['E3'].get('response',{}).get('candidate_ids',[]))==set(rows['E4'].get('response',{}).get('candidate_ids',[])) if valid else None,
            'e4_e5_same_results':rows['E4'].get('response',{}).get('results')==rows['E5'].get('response',{}).get('results') if valid else None,
            'auto_e5_same_results':rows['AUTO'].get('response',{}).get('results')==rows['E5'].get('response',{}).get('results') if valid else None})
    write(E/'mode_comparisons.json',comparisons)
    write(E/'cache_cases.json',{'before':before,'after':cache_stats(),'policy':'no deletion or manual modification; normal application writes only'})

def latency():
    import numpy as np
    p=json.loads((E/'latency_plan.json').read_text(encoding='utf-8'));before=cache_stats()
    with urllib.request.urlopen(BASE+'/_audit/runtime') as f: runtime_before=json.load(f)
    cold=request({'query':p['queries'][2]['query'],'mode':'E3','top_k':30,'trace':True})
    with urllib.request.urlopen(BASE+'/_audit/runtime') as f: runtime_after=json.load(f)
    write(E/'runtime_engine.json',{'before':runtime_before,'after':runtime_after,'observation':'Read-only audit route around original app; no search functions/config changed'})
    write(E/'model_load_observation.json',{'status':'observed','cold_process_model_only':not runtime_before['encoder_loaded'],
          'os_file_cache_controlled':False,'note':'One request in fresh API process, local pretrained weights and existing document/passage caches; not a cold filesystem benchmark',**cold})
    # Fixed seed shuffles mode order for warmup and all mode/query/repeat measurement jobs.
    modes=p['modes'].copy();rng=random.Random(p['seed']);rng.shuffle(modes)
    warmups=[]
    for mode in modes:
        for i in range(p['warmups_per_mode']):
            q=p['queries'][i%len(p['queries'])];r=request({'query':q['query'],'mode':mode,'top_k':30,'trace':True})
            d=r.get('response',{});dec=d.get('trace',{}).get('decisions',{})
            warmups.append({'mode':mode,'query_id':q['query_id'],'index':i,'status':r['status'],'http_ms':r['http_ms'],'engine_ms':d.get('latency_ms'),
                'model_loading_ms':dec.get('timings_ms',{}).get('model_loading'),'passages':dec.get('stages',{}).get('lyric_passages'), 'error':r.get('error')})
        print('warmup',mode,flush=True)
    write(E/'latency_warmups.json',warmups)
    jobs=[(q,m,r) for q in p['queries'] for m in p['modes'] for r in range(p['repeats_per_query_mode'])];rng.shuffle(jobs)
    rows=[]
    fields=['sequence','query_id','category','mode','repeat','status','http_ms','engine_ms','model_loading_ms','passage_encoded','passage_cache_hits','degraded','error']
    with (E/'latency_raw.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for n,(q,mode,repeat) in enumerate(jobs):
            r=request({'query':q['query'],'mode':mode,'top_k':30,'trace':True});d=r.get('response',{});decision=d.get('trace',{}).get('decisions',{})
            ps=decision.get('stages',{}).get('lyric_passages',{})
            row={'sequence':n,'query_id':q['query_id'],'category':q['category'],'mode':mode,'repeat':repeat,'status':r['status'],
                 'http_ms':r['http_ms'],'engine_ms':d.get('latency_ms'),'model_loading_ms':decision.get('timings_ms',{}).get('model_loading'),
                 'passage_encoded':ps.get('encoded'),'passage_cache_hits':ps.get('cache_hits'),'degraded':d.get('pipeline',{}).get('degraded'),'error':r.get('error')}
            writer.writerow(row);f.flush();rows.append(row)
            if n%18==0:print('latency',n+1,'/',len(jobs),flush=True)
    summary={}
    for mode in p['modes']:
        selected=[r for r in rows if r['mode']==mode]; good=[r for r in selected if r['status']==200]
        summary[mode]={'requests':len(selected),'errors':len(selected)-len(good),'degraded':sum(bool(r['degraded']) for r in good)}
        for key in ['http_ms','engine_ms']:
            values=[r[key] for r in good if r[key] is not None]
            summary[mode][key]={'n':len(values),'mean':statistics.mean(values) if values else None,'median':statistics.median(values) if values else None,'p95':float(np.percentile(values,95)) if values else None}
    write(E/'latency_summary.json',{'status':'complete' if all(r['status']==200 for r in rows+warmups) else 'incomplete',
         'plan':p,'warmup_mode_order':modes,'total_warmup_requests':len(warmups),'total_measured_requests':len(rows),
         'aggregation':'each mode equally weights 6 queries x5 repetitions; p95 numpy linear percentile over 30 observations; successful requests only with error counts retained',
         'summary':summary,'cache_before':before,'cache_after':cache_stats()})

def annotation():
    qs=[json.loads(x) for x in (ROOT/'evaluation/queries.draft.jsonl').read_text(encoding='utf-8').splitlines() if x]
    p=json.loads((E/'annotation_pool_plan.json').read_text(encoding='utf-8')); plan=set(p['query_ids'])
    traces=[];annotations=[];coverage=[]
    for q in qs:
        pool=set();errors=[]
        if q['query_id'] in plan:
            for m in p['modes']:
                r={'query_id':q['query_id'],'payload':{'query':q['query'],'mode':m,'top_k':10,'trace':True}}
                r.update(request(r['payload']));emit(E/'annotation_pool_traces.jsonl',r)
                if r['status']==200:pool.update(x['track_id'] for x in r['response']['results'])
                else:errors.append({'mode':m,'status':r['status'],'error':r.get('error')})
            ordered=list(sorted(pool));random.Random('music-ir-42-'+q['query_id']).shuffle(ordered)
            for trackid in ordered:
                d=byid[trackid]
                annotations.append({'query_id':q['query_id'],'query':q['query'],'intent_note':q['intent_note'],'query_review_status':'needs_review',
                  'candidate_id':trackid,'title':d['track_name'],'artist':d['track_artist'], 'album':d.get('track_album_name',''),
                  'lyrics_available':d['lyrics_available'],'lyric_excerpt':d.get('lyrics','')[:250],
                  'track_url':'https://open.spotify.com/track/'+trackid,
                  'local_evidence_endpoint':BASE+'/tracks/'+trackid,'relevance':'','annotator_code':'','notes':''})
            print('annotation',q['query_id'],len(pool),'errors',len(errors),flush=True)
        coverage.append({'query_id':q['query_id'],'query':q['query'],'category':q['category'],'split':q['split'],'group_id':q['group_id'],
                         'query_review_status':'needs_review','pool_status':'incomplete' if errors else 'pooled' if q['query_id'] in plan else 'not_pooled_in_audit',
                         'pool_count':len(pool),'human_judgments':0,'errors':json.dumps(errors) if errors else ''})
    for name,rows in [('annotation_needed.csv',annotations),('query_review_checklist.csv',coverage)]:
        with (E/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    write(E/'annotation_manifest.json',{'queries_pooled':len(plan),'annotation_rows':len(annotations),'query_checklist_rows':len(coverage),'grade_fields_blank':True,
          'candidate_order':'deterministic per query shuffled, seed music-ir-42-query_id','mode_and_score_hidden':True,'depth':10,'modes':p['modes'],
          'ranking_object':'union of primary results; related results are separate and not included','human_labels_created':0,'status':'incomplete' if any(c['errors'] for c in coverage) else 'ready_for_human_review',
          'queries_without_candidates':sum(c['pool_count']==0 for c in coverage),'pool_coverage':coverage})

if __name__=='__main__': {'plan':plan,'cases':cases,'latency':latency,'annotation':annotation}[sys.argv[1]]()
