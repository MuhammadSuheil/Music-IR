import json,csv,sys,math,collections,tempfile,types
from audit_collect import ROOT,OUT,E,write,run
from music_ir.evaluate import metrics,evaluate,read_benchmark
from music_ir.data import load_docs,normalize,tokens

def fixtures():
    ranking=['C','B','A'];labels={'A':3,'B':2,'C':0}
    actual=metrics(ranking,labels)
    expected={'ndcg@10':(3/math.log2(3)+7/2)/(7+3/math.log2(3)),'mrr@10':.5,'recall@100':1.}
    check={'ranking':ranking,'labels':labels,'actual':actual,'manual_expected':expected,
           'tolerance':1e-12,'passed':all(abs(actual[k]-expected[k])<1e-12 for k in expected),
           'scope':'synthetic hand-counted fixture, NOT project retrieval effectiveness'}
    write(E/'evaluator_manual_fixture.json',check)
    with tempfile.TemporaryDirectory(dir=OUT,prefix='fixture_') as d:
        from pathlib import Path
        d=Path(d);qpath=d/'queries.jsonl';lpath=d/'qrels.csv';target=d/'run'
        qs=[{'query_id':'fixture-one','query':'one','split':'test','category':'fixture','group_id':'one','review_status':'approved'},
            {'query_id':'fixture-two','query':'two','split':'test','category':'fixture','group_id':'two','review_status':'approved'}]
        qpath.write_text('\n'.join(json.dumps(q) for q in qs),encoding='utf-8')
        lpath.write_text('query_id,track_id,relevance\nfixture-one,A,3\nfixture-two,A,3\n',encoding='utf-8')
        class FixtureEngine:
            docs=[{'track_id':'A'}];config={};backend='fixture'
            calls=0
            def search(self,query,mode,top_k):
                self.calls+=1
                if self.calls==13: raise RuntimeError('audit fixture: required query failure')
                return {'results':[{'track_id':'A'}],'candidate_ids':['A'],'latency_ms':1.,'pipeline':{}}
        engine=FixtureEngine()
        try:evaluate(engine,qpath,lpath,target,['E1'],repeats=2);error=None
        except Exception as exc:error=repr(exc)
        write(E/'evaluator_failure_reproduction.json',{'procedure':'evaluate() with two approved artificial queries and toy labels; raise on search call13 (after ten warmups, two measurement successes)',
             'calls':engine.calls,'exception':error,'output_directory_exists':target.exists(),'incomplete_manifest_written':(target/'summary.json').exists(),
             'impact':'existing evaluator aborts before persisting completed runs/failure manifest; future research run needs explicit incomplete status and per-query errors',
             'scope':'fixture only; no application code fixed and no human relevance labels fabricated'})

def strengthened_cases():
    from music_ir.lyrics import lyric_tokens
    from collections import Counter
    docs=load_docs();byid={d['track_id']:d for d in docs}
    traces=[json.loads(l) for l in (E/'search_traces.jsonl').read_text(encoding='utf-8').splitlines()]
    checks=[]; independent=[]
    for r in traces:
        d=r.get('response',{});cid=r['case_id'];both=d.get('results',[])+d.get('related_results',[]);local={}
        if r['status']!=200:continue
        if cid in ['TITLE','UNICODE']:
            expected={x['track_id'] for x in docs if tokens(x['track_name'])==tokens('Die With A Smile')}
            local['catalog_exact_ids']=set(x['track_id'] for x in both)==expected
        if cid=='COLLAB':local['artist_credit']=bool(both) and all('Lady Gaga' in x['artist'] for x in both)
        if cid=='LYRIC':local['literal_lyric_evidence']=bool(d['results']) and all(x['lyric_match'] and x['lyric_match']['kind']=='exact' for x in d['results'])
        if cid=='NOLYRICS':local['without_lyrics_retrieved']=any(not x['lyrics_available'] for x in both)
        if cid=='MOODAUDIO':local['mood_audio_only']=not d['pipeline']['semantic'] and not d['pipeline']['lexical'] and d['mood']['basis']=='audio'
        if cid=='MIXED':local['artist_and_audio']=bool(both) and all('Bruno Mars' in x['artist'] and x['audio']['tempo']>120 for x in both)
        if cid=='AUDIO':local['indicator_1']=bool(both) and all(x['score']==1 for x in both)
        if cid=='REG-09':local['bounded_memory_error']=bool(d['results']) and d['results'][0]['lyric_match']['kind']=='approximate'
        # Independently reconstruct score from raw source scores and feature definitions for each selected branch.
        chosen=d.get('trace',{}).get('decisions',{});rows=[x for x in chosen.get('candidates',[]) if x['final_rank'] is not None]
        if cid in ['MODE-0-E2','MODE-0-E3','MODE-0-E4','AUDIO','PREF','REG-07','REG-03','MIXTEXT'] and rows:
            row=rows[0];raw=row['raw_scores'];doc=byid[row['track_id']];audio_weight=chosen['audio_weight']
            bm_values=[x['raw_scores']['bm25'] for x in rows];span=max(bm_values)-min(bm_values)
            normbm=(raw['bm25']-min(bm_values))/span if span>0 else 0.
            def overlap(query,text):
                a,b=set(tokens(query)),set(tokens(text))
                return max(float(normalize(query).casefold()==normalize(text).casefold()),len(a&b)/max(1,len(a|b))) if a else 0.
            text=d['text_query'];lyric=tokens(doc['lyrics']);qt=tokens(text)
            feats=[normbm,(raw['cosine']+1)/2 if raw['cosine'] is not None else 0.,overlap(text,doc['track_name']),overlap(text,doc['track_artist']),float(len(qt)>=2 and any(lyric[i:i+len(qt)]==qt for i in range(len(lyric)-len(qt)+1)))]
            if cid=='MODE-0-E2':
                n=len(docs);expected_bm=0.
                for field,weight in zip(['track_name','track_artist','lyrics'],[3,2,1]):
                    allwords=[tokens(x[field]) for x in docs];avg=sum(len(x) for x in allwords)/n or 1;docwords=tokens(doc[field]);ct=Counter(docwords)
                    for token in set(tokens(text)):
                        df=sum(token in words for words in allwords);tf=ct[token]
                        expected_bm+=weight*math.log(1+(n-df+.5)/(df+.5))*tf*2.2/(tf+1.2*(.25+.75*len(docwords)/avg))
                expected=expected_bm
            elif cid=='MODE-0-E3':expected=sum(1/(60+rank) for rank in row['sources'].values())
            elif cid in ['AUDIO','PREF']:
                if cid=='AUDIO':expected=1.
                else:
                    vals=sorted(x['energy'] for x in docs if x['energy'] is not None);v=doc['energy'];left=sum(x<v for x in vals);right=sum(x<=v for x in vals)
                    expected=1-(left+right-1)/(2*(len(vals)-1))
            elif cid=='REG-03':
                ev=row['theme_evidence'];expected=.4*(raw['cosine']+1)/2+.6*(ev['ranking_cosine']+1)/2
            else:
                weights=list(chosen['text_weights'].values());expected_text=sum(w*f for w,f in zip(weights,feats))
                expected=(1-audio_weight)*expected_text+audio_weight*raw['audio']
                if row['lyric_match']:expected+=4 if row['lyric_match']['kind']=='exact' else 2*row['lyric_match']['similarity']
            error=abs(expected-row['score'])
            independent.append({'case_id':cid,'track_id':row['track_id'],'mode':d['mode'],'query_type':d['query_type'],'features_recomputed':feats,'contributions':row['contributions'],
                'raw_scores':raw,'audio_weight':audio_weight,'text_weights':chosen['text_weights'],'expected_score_independent':expected,'actual_score':row['score'],
                'absolute_error':error,'tolerance':1e-7,'passed':error<=1e-7})
        if local:checks.append({'case_id':cid,'assertions':local,'passed':all(local.values())})
    write(E/'case_additional_assertions.json',checks)
    write(E/'score_independent_examples.json',{'checks':independent,'all_passed':all(x['passed'] for x in independent)})
    print('additional checks:',len(checks),'failed:',sum(not c['passed'] for c in checks),'independent scores:',len(independent),'failed:',sum(not c['passed'] for c in independent),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='fixtures': fixtures();strengthened_cases()
    elif sys.argv[1]=='ui':
        r=run(['node',str(OUT/'audit_ui.cjs')],'live_ui',cwd=ROOT,timeout=600)
        print(r['stdout'],r['stderr'],flush=True)
