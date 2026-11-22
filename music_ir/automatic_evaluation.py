"""Automatic-only evaluation: explicit corpus checks plus blind LLM lyric judgments.

No human approval is synthesized. Retrieval, corpus and original query strings stay frozen.
"""
import argparse
import json
import hashlib
import re
import unicodedata
import math
import bisect
import csv
import statistics
import uuid
from difflib import SequenceMatcher
from collections import defaultdict
from pathlib import Path

from .relevance import RelevanceRun, atomic_json, digest, now
from .relevance_review import clone_for_judge
from .relevance_judge import numeric_checks
from .evaluate import metrics

THEMES = {
 'semantic-happy':'Happiness and joy as the meaning of the lyrics. Celebration/contentment/joy supported in context. Do not infer sound or emotion from audio values. A stray happy word is insufficient.',
 'semantic-breakup':'Missing a former lover after a breakup. Need longing AND past separation; generic current-partner desire is partial at most.',
 'semantic-loss':'Grieving the loss of a loved person. Bereavement/irreversible absence is strong; generic breakup desire alone is weak/partial.',
 'semantic-hope':'Keeping hope through hardship. Need adversity and continued hope/support/perseverance, not merely party optimism.',
 'semantic-self':'Accepting oneself, self-worth or self-acceptance. Boasting/status alone is not self-acceptance.',
 'semantic-nostalgia':'Wishing to return to a past time. Memories alone are partial; a wish to relive/return is stronger.',
 'semantic-friendship':'Friends supporting one another / enduring friendship. Do not automatically treat every romantic partner as friendship.',
 'semantic-love':'Falling in love / beginning romantic love. Established love without beginning/new discovery is related but not strongest.',
 'semantic-distance':'A long-distance romantic relationship / lovers separated geographically. Emotional distance without geography is partial at most.',
 'semantic-betrayal':'Being betrayed by a romantic partner. Infidelity/deception/disloyalty in the relationship needs contextual support.',
 'semantic-lonely':'Feeling lonely among other people / in a crowd. Generic isolation is partial; social surrounding plus loneliness is stronger.',
 'semantic-dream':'Pursuing dreams/aspirations. Night-time dreams or simply wanting a lover are not by themselves aspirations.',
 'semantic-regret':'Regretting one\'s own mistakes. Need self-attributed regret/remorse, not only blaming others or sadness.',
 'semantic-freedom':'Wanting freedom / autonomy. Literal or personal liberation supported in context; a single free word is insufficient.',
 'semantic-family':'Missing home and family. A lover alone is not family/home; hometown, parents or family longing is strong.',
 'semantic-farewell':'Saying goodbye / parting. Need leaving, farewell or accepting an ending; not all sadness is farewell.'
}

RUBRIC = {
 'version':'automatic_only_v1', 'created_utc':None,
 'human_review_required':False,
 'semantic_grades':{'3':'Clear core-theme support with explicit contextual evidence','2':'Core need reasonably supported but less explicit/central','1':'Partial or weak connection; missing a defining facet','0':'No core-theme support in the provided full lyrics','null':'Missing/unintelligible/contradictory evidence; uncertainty is not0'},
 'semantic_scope':THEMES,
 'happy_interpretation':'For the ambiguous happy query, automatically choose lyric meaning, not perceived sound. This interpretation is not human-approved; audio heuristics are not gold truth.',
 'metadata':'Direct metadata task: exact normalized title or credited artist=3; bounded title version variant=2; mismatch=0. These are deterministic corpus checks, not LLM calls.',
 'lyrics':'Normalized contiguous quote=3; independently bounded token-edit match=2; mismatch in available lyrics=0; unavailable lyrics=null. This is a text-matching proxy, not an LLM claim.',
 'audio':'Explicit bounds independently compared with dataset numbers. All mandatory constraints pass=3, any fails=0, missing mandatory value=null. Artist+audio must satisfy both.',
 'soft_audio':'Operational automatic rubric for high/low tempo or energy: favorable corpus percentile >=.75:3, >=.5:2, >=.25:1, else0; average preference percentiles for several preferences. This is a declared proxy aligned with relative dataset preferences, not independent semantic truth.',
 'model_input_exclusions':['retrieval mode','scores','source ranks','result group','system reasons','hint_track_ids'],
 'missing_metric_policy':'Preserve null qrels as unjudged. Report standard known-qrels provisional metrics with explicit unjudged contribution0 convention, incomplete-judgment counts and coverage. Do not store null as grade0 or call metrics human-validated.',
 'mode_selection':'All frozen modes, primary results only, depth100; shorter lists preserved; no tuning or query removal.'
}


def bank(text):
    lines=[];lookup={};order=[]
    for line in text.splitlines(keepends=True):
        if line not in lookup:lookup[line]=len(lines);lines.append(line)
        order.append(lookup[line])
    assert ''.join(lines[i] for i in order)==text
    return {'unique_lines':lines,'line_order':order,'restored_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'restored_chars':len(text),'representation':'lossless line dictionary; repeated lines referenced by line_order; no lyric words omitted'}


def prepare(parent,directory,workers=3):
    clone_for_judge(parent,directory)
    run=RelevanceRun(directory)
    rubric={**RUBRIC,'created_utc':now()}
    contexts=[{'query_id':q['query_id'],'query':q['query'],'user_need':q['intent_note'],'group_id':q['group_id'],
               'status':'existing draft interpreted automatically; not human-approved'} for q in run.queries if q['category']=='semantic']
    atomic_json(run.directory/'semantic_query_contexts.json',{'query_contexts':contexts,'sha256':digest(contexts)})
    run.manifest['evaluation_policy']={'human_review_required':False,'labeling':'hybrid: independent deterministic objective checks + direct LLM full-lyric thematic judgments',
       'rubric_sha256':digest(rubric),'automatic_only':True,'not_human_ground_truth':True}
    run.manifest['human_review_policy']='Not required for this automatic-only run. Never synthesize human decisions or human final_grade.'
    atomic_json(run.directory/'manifest.json',run.manifest)
    atomic_json(run.directory/'automatic_rubric.json',rubric)
    groups=defaultdict(set)
    for qid,tid in run.pair_ids():
        q=run.by_query[qid]
        if q['category']=='semantic':groups[tid].add(q['group_id'])
    packets=[[] for _ in range(workers)]
    ordered=sorted(groups)
    for index,tid in enumerate(ordered):
        d=run.by_track[tid]
        record={'index':index,'track_id':tid,'title':d['track_name'],'artist':d['track_artist'],
                'active_theme_groups':sorted(groups[tid]),'lyrics':bank(d.get('lyrics',''))}
        record['input_sha256']=digest(record)
        packets[index%workers].append(record)
    target=run.directory/'semantic_packets';target.mkdir()
    out=run.directory/'semantic_judgments';out.mkdir()
    for i,records in enumerate(packets):
        folder=target/f'worker_{i+1}';folder.mkdir()
        for j in range(0,len(records),12):
            packet={'rubric':rubric,'query_contexts':contexts,'query_contexts_sha256':digest(contexts),
                    'worker':i+1,'batch':j//12+1,'records':records[j:j+12]}
            atomic_json(folder/f'batch_{j//12+1:03}.json',packet)
        (out/f'worker_{i+1}').mkdir()
    atomic_json(run.directory/'semantic_packet_manifest.json',{'documents':len(groups),'workers':workers,
        'worker_documents':[len(p) for p in packets],'batch_size':12,'source_identity':run.manifest['corpus_sha256'],
        'rubric_sha256':digest(rubric),'lyric_coverage':'full text, reversible line dictionary; no retrieval-selected snippets'})
    return {'directory':str(run.directory),'semantic_documents':len(groups),'workers':[len(p) for p in packets],'counts':run.counts()}


def normalized(text):
    return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',text).casefold()))


def artist_matches(focus,credit):
    key=normalized(focus);whole=normalized(credit)
    return bool(key) and re.search(r'(?<!\w)'+re.escape(key)+r'(?!\w)',whole) is not None


def title_grade(focus,title):
    if normalized(focus)==normalized(title):return 3
    def base(text):
        text=re.sub(r'\([^)]*\)|\[[^]]*\]',' ',text)
        text=re.split(r'\s[-–—]\s',text,maxsplit=1)[0]
        return normalized(text)
    if base(focus) and base(focus)==base(title) and re.search(r'\b(?:remix|remaster(?:ed)?|version|live|acoustic|feat|featuring|edit|sped|slowed)\b',focus+' '+title,re.I):return 2
    return 0


CONTRACTIONS={"can't":"can not","won't":"will not","don't":"do not","doesn't":"does not","didn't":"did not",
 "i'm":"i am","you're":"you are","we're":"we are","they're":"they are","it's":"it is","that's":"that is",
 "isn't":"is not","aren't":"are not","wasn't":"was not","weren't":"were not","i've":"i have","i'll":"i will"}


def lyric_words(text):
    text=unicodedata.normalize('NFKC',text).casefold().translate(str.maketrans({'’':"'",'‘':"'",'ʼ':"'"}))
    words=[]
    for m in re.finditer(r"[^\W_]+(?:'[^\W_]+)*",text,re.U):
        for word in CONTRACTIONS.get(m.group(),m.group()).split():words.append((word,m.start(),m.end()))
    return words


def edit_cost(a,b,budget):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):
            cost=0 if x==y else .4 if min(len(x),len(y))>=4 and abs(len(x)-len(y))<=2 and SequenceMatcher(None,x,y,autojunk=False).ratio()>=.8 else 1
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+cost))
        if min(current)>budget:return float('inf')
        previous=current
    return previous[-1]


def is_lyric_placeholder(lyrics):
    return lyrics.lstrip().startswith("You don't yet have any static lyrics for this song.")


def quote_grade(query,lyrics):
    if not lyrics.strip():return None,[],['lyrics_unavailable'],'Lirik tidak tersedia; kecocokan kutipan tidak dapat ditetapkan.'
    if is_lyric_placeholder(lyrics):return None,[],['non_lyric_placeholder'],'Field lirik berisi petunjuk editor, bukan lirik; kecocokan tidak dapat ditetapkan.'
    match=re.search(r'["“]([^"”]+)["”]',query)
    focus=match[1] if match else re.sub(r'^(?:lyrics?|lirik)\s*[:\-]?\s*','',query,flags=re.I)
    q=[w[0] for w in lyric_words(focus)];spans=lyric_words(lyrics);d=[w[0] for w in spans]
    if not q:return None,[],['empty_quote'],'Kutipan tidak mengandung token yang dapat diperiksa.'
    for i in range(len(d)-len(q)+1):
        if d[i:i+len(q)]==q:
            evidence=lyrics[spans[i][1]:spans[i+len(q)-1][2]]
            return 3,[{'field':'lyrics','quote':evidence[:500]}],[],'Kutipan berurutan cocok setelah normalisasi Unicode/kontraksi.'
    # Independent exhaustive local alignment; no retrieval matching outputs or ranking are read.
    if 4<=len(q)<=32 and len(set(q)&set(d))>=max(3,math.ceil(.6*len(set(q)))):
        budget=min(2.5,max(1.0,.3*len(q)))
        qset=set(q);best=None
        for start in range(len(d)):
            for length in range(max(3,len(q)-2),len(q)+3):
                window=d[start:start+length]
                if len(window)!=length or len(qset&set(window))<max(3,math.ceil(.6*len(qset))):continue
                distance=edit_cost(q,window,budget)
                if distance<=budget+1e-9 and 1-distance/max(len(q),length)>=.72:
                    if best is None or distance<best[0]:best=(distance,start,length)
        if best:
            _,start,length=best;evidence=lyrics[spans[start][1]:spans[start+length-1][2]]
            return 2,[{'field':'lyrics','quote':evidence[:500]}],[],'Jendela kutipan memenuhi anggaran edit terbatas; ini proksi kecocokan teks, bukan label LLM.'
    return 0,[{'field':'track_name','quote':''}],[],'Pemeriksaan seluruh lirik tidak menemukan kutipan exact atau variasi dalam batas operasional yang dibekukan.'


def store_auto(run,qid,tid,grade,reason,evidence,flags,origin,raw_file=None,extra=None):
    if grade is not None and (type(grade) is not int or grade not in range(4)):raise ValueError('Invalid grade')
    if grade is None and not flags:raise ValueError('Unknown must carry an explicit reason')
    d=run.by_track[tid]
    for e in evidence:
        field=e['field'];source=d.get(field,'') if not field.startswith('audio.') else str(d.get(field[6:]))
        if not isinstance(source,str):source=json.dumps(source,ensure_ascii=False)
        if not e.get('quote') or e['quote'] not in source:raise ValueError(f'Unverifiable evidence: {qid}/{tid}/{e}')
    record={'query_id':qid,'track_id':tid,'auto_grade':grade,'reason':reason,'evidence':evidence,'uncertainty_flags':flags,
        'mandatory_checks':numeric_checks(run.by_query[qid]['query'],d),'label_origin':origin,
        'provider':'openai-codex-session-subagent' if origin=='LLM full-lyric thematic judgment' else 'deterministic-corpus-evidence-checks',
        'model':None,'model_identity_note':'Exact served model not exposed; deterministic checks are not model inference.',
        'human_reviewed':False,'human_review_required':False,'recorded_utc':now(),
        'rubric_sha256':run.manifest['evaluation_policy']['rubric_sha256'],
        'input_sha256':digest({'query':run.by_query[qid]['query'],'user_need':run.by_query[qid]['intent_note'],'document':d}),
        'raw_response_files':[raw_file] if raw_file else [],**(extra or {})}
    key=digest({'input':record['input_sha256'],'rubric':record['rubric_sha256'],'origin':origin})
    with run.connect() as db:
        old=db.execute('SELECT cache_key,label FROM auto_labels WHERE query_id=? AND track_id=?',(qid,tid)).fetchone()
        if old:
            if old['cache_key']!=key:raise ValueError('Do not mix different labels in frozen run')
            previous=json.loads(old['label'])
            if previous['auto_grade']!=grade or previous['evidence']!=evidence:raise ValueError('Immutable label differs from previous result')
            return False
        db.execute('INSERT INTO auto_labels VALUES (?,?,?,?,?,?)',(qid,tid,key,'ok' if grade is not None else 'needs_review',json.dumps(record,ensure_ascii=False),now()))
    return True


def objective_labels(run):
    from .relevance_judge import FEATURES,OPS
    method={'created_utc':now(),'method':'Independent objective corpus checks; not LLM-generated pair judgments',
        'quote_parameters':{'exhaustive_windows':'query length ±2','weighted_token_edit_budget':'min(2.5,max(1,.3*query_token_count))',
         'similarity_min':.72,'unique_token_support_min':'.6; at least3','near_word_substitution':.4,'near_word_char_ratio_min':.8},
        'rule_definition':run.directory.joinpath('automatic_rubric.json').name,'retrieval_score_used':False,'hint_id_used':False}
    path=run.directory/'objective_method.json'
    if not path.exists():atomic_json(path,method)
    populations={f:sorted(d[f] for d in run.docs if isinstance(d.get(f),(int,float)) and math.isfinite(d[f])) for f in ['tempo','energy']}
    names='|'.join(FEATURES);operators='|'.join(re.escape(k) for k in sorted(OPS,key=len,reverse=True))
    bounds=re.compile(rf'\b({names})\s*(tidak\s+)?({operators})\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:BPM\b)?',re.I)
    preference=re.compile(r'\b(tempo|energy|energi)\s+(tidak\s+)?(cepat|lambat|tinggi|rendah|fast|slow|high|low)\b',re.I)
    count=0
    for qid,tid in run.pair_ids():
        q=run.by_query[qid];d=run.by_track[tid];category=q['category']
        if category=='semantic':continue
        flags=[];evidence=[];extra={};origin='Deterministic corpus '+category+' evidence check'
        if category=='title':
            grade=title_grade(q['query'],d['track_name']);reason='Judul dibandingkan langsung dengan kebutuhan katalog; metadata exact=3, versi terbatas=2, mismatch=0.'
            evidence=[{'field':'track_name','quote':d['track_name']}]
        elif category=='artist':
            grade=3 if artist_matches(q['query'],d['track_artist']) else 0;reason='Kredit artis corpus diperiksa sebagai frasa nama utuh; tidak memakai target ID atau skor pencarian.'
            evidence=[{'field':'track_artist','quote':d['track_artist']}]
        elif category=='lyrics':
            grade,evidence,flags,reason=quote_grade(q['query'],d.get('lyrics',''))
            if grade==0:evidence=[{'field':'track_name','quote':d['track_name']}]
            extra['lyric_coverage']={'full_text_scanned':True,'characters':len(d.get('lyrics','')),'method':'independent exhaustive literal/bounded-edit checker; not an LLM reading claim'}
        elif category=='audio':
            checks=numeric_checks(q['query'],d);extra['mandatory_checks']=checks
            prefs=[]
            for m in preference.finditer(q['query']):
                feature=FEATURES[m[1].lower()];high=m[3].lower() in {'cepat','tinggi','fast','high'}
                if m[2]:high=not high
                v=d.get(feature);pop=populations[feature]
                if v is None or not math.isfinite(v):prefs.append(None);continue
                p=(bisect.bisect_left(pop,v)+bisect.bisect_right(pop,v)-1)/(2*(len(pop)-1)) if len(pop)>1 and pop[0]!=pop[-1] else .5
                prefs.append(p if high else 1-p)
            focus=normalized(re.sub(r'\b(lagu|musik|dengan|dan|yang|BPM)\b',' ',preference.sub(' ',bounds.sub(' ',q['query'])),flags=re.I))
            if any(c['passed'] is False for c in checks):grade=0
            elif any(c['passed'] is None for c in checks) or any(p is None for p in prefs):grade=None;flags=['mandatory_audio_value_unavailable']
            elif focus and not artist_matches(focus,d['track_artist']) and title_grade(focus,d['track_name'])==0:grade=0
            elif prefs:
                p=sum(prefs)/len(prefs);grade=3 if p>=.75 else 2 if p>=.5 else 1 if p>=.25 else 0;extra['evaluation_preference_percentile']=p
            else:grade=3
            reason='Batas eksplisit diperiksa independen pada angka dataset; preferensi relatif memakai rubrik persentil evaluasi yang dinyatakan, bukan kebenaran mood.'
            evidence=[{'field':'audio.'+c['field'],'quote':str(c['observed'])} for c in checks if c['observed'] is not None]
            if focus:evidence.append({'field':'track_artist','quote':d['track_artist']})
            if not evidence:
                evidence=[{'field':'audio.'+FEATURES[m[1].lower()],'quote':str(d.get(FEATURES[m[1].lower()]))} for m in preference.finditer(q['query']) if d.get(FEATURES[m[1].lower()]) is not None]
            extra['evaluated_text_focus']=focus
        else:raise ValueError('Unhandled category '+category)
        count+=int(store_auto(run,qid,tid,grade,reason,evidence,flags,origin,extra=extra))
        if count and count%500==0:print(json.dumps({'phase':'objective','new_labels':count,'counts':run.counts()}),flush=True)
    atomic_json(run.directory/'progress.json',run.counts())
    return {'inserted':count,'counts':run.counts()}


def repair_placeholder_labels(run):
    """Record a narrow data-validation erratum; never relabel genuine lyrics."""
    changes=[]
    with run.connect() as db:
        for row in db.execute('SELECT * FROM auto_labels').fetchall():
            if run.by_query[row['query_id']]['category']!='lyrics':continue
            if not is_lyric_placeholder(run.by_track[row['track_id']].get('lyrics','')):continue
            before=json.loads(row['label'])
            if before['auto_grade'] is None:continue
            after=dict(before)
            after.update(auto_grade=None,evidence=[],uncertainty_flags=['non_lyric_placeholder'],
                reason='Field lirik berisi petunjuk editor, bukan lirik; kecocokan tidak dapat ditetapkan.',
                data_validation_erratum='label_data_errata.json; prior record preserved there')
            changes.append({'query_id':row['query_id'],'track_id':row['track_id'],'before':before,'after':after})
        if changes:
            path=run.directory/'label_data_errata.json'
            previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            previous.append({'created_utc':now(),'reason':'Discovered literal lyric-editor placeholder; implements frozen insufficient-data=null policy. No metric feedback or rubric change.',
                'retrieval_or_corpus_changed':False,'changes':changes})
            atomic_json(path,previous)
            for change in changes:
                db.execute('UPDATE auto_labels SET label=?,status=?,updated=? WHERE query_id=? AND track_id=?',
                    (json.dumps(change['after'],ensure_ascii=False),'needs_review',now(),change['query_id'],change['track_id']))
    atomic_json(run.directory/'progress.json',run.counts())
    return {'data_errata_applied':len(changes),'counts':run.counts()}


def ingest_semantic(run):
    rubric=json.loads((run.directory/'automatic_rubric.json').read_text(encoding='utf-8'))
    if digest(rubric)!=run.manifest['evaluation_policy']['rubric_sha256']:raise ValueError('Frozen rubric was modified')
    packet_by_tid={};file_by_tid={}
    for p in sorted((run.directory/'semantic_packets').glob('worker_*/batch_*.json')):
        for r in json.loads(p.read_text(encoding='utf-8'))['records']:packet_by_tid[r['track_id']]=r
    inserted=0;documents=0;errors=[];seen=set()
    semantic_pairs=defaultdict(list)
    for qid,tid in run.pair_ids():
        if run.by_query[qid]['category']=='semantic':semantic_pairs[tid].append(qid)
    contexts=json.loads((run.directory/'semantic_query_contexts.json').read_text(encoding='utf-8'))
    if digest(contexts['query_contexts'])!=contexts['sha256']:raise ValueError('Original query catalog hash mismatch')
    for path in sorted((run.directory/'semantic_judgments').glob('worker_*/batch_*.json')):
        try:
            result=json.loads(path.read_text(encoding='utf-8'))
            expected_packet=run.directory/'semantic_packets'/path.parent.name/path.name
            expected=json.loads(expected_packet.read_text(encoding='utf-8'))
            if digest(expected['rubric'])!=digest(rubric):raise ValueError('Packet rubric differs from frozen run')
            if result.get('batch')!=expected['batch'] or result.get('worker')!=expected['worker']:raise ValueError('Batch identity mismatch')
            rows=result['records']
            if len(rows)!=len(expected['records']) or {r['track_id'] for r in rows}!={r['track_id'] for r in expected['records']}:raise ValueError('Batch incomplete or unexpected documents')
            for row in rows:
                tid=row['track_id'];packet=packet_by_tid[tid];d=run.by_track[tid]
                if tid in seen:raise ValueError('Duplicate document profile')
                if row['input_sha256']!=packet['input_sha256']:raise ValueError('Input hash mismatch')
                if digest({k:v for k,v in packet.items() if k!='input_sha256'})!=packet['input_sha256']:raise ValueError('Packet document content was modified')
                restored=''.join(packet['lyrics']['unique_lines'][i] for i in packet['lyrics']['line_order'])
                if restored!=d.get('lyrics','') or hashlib.sha256(restored.encode()).hexdigest()!=packet['lyrics']['restored_sha256']:
                    raise ValueError('Lossless lyric source does not match frozen corpus')
                if set(row['labels'])!=set(packet['active_theme_groups']):raise ValueError('Active theme omitted or extra')
                if d.get('lyrics','').strip() and not is_lyric_placeholder(d.get('lyrics','')) and row.get('full_lyric_read') is not True:raise ValueError('Full lyric reading not confirmed')
                # Validate every field first; never turn an invalid/missing judgment into a grade0.
                for group,v in row['labels'].items():
                    grade=v['grade'];flags=v.get('flags',[])
                    if grade is not None and (type(grade) is not int or grade not in range(4)):raise ValueError('Invalid semantic grade')
                    if grade is None and not flags:raise ValueError('Null requires uncertainty flags')
                    if grade is not None and flags:raise ValueError('Unresolved semantic uncertainty has a numeric grade')
                    if grade is not None and not d.get('lyrics','').strip():raise ValueError('Missing lyric requires null')
                    if grade is not None and is_lyric_placeholder(d.get('lyrics','')):raise ValueError('Lyric-editor placeholder requires null')
                    if not v.get('reason'):raise ValueError('Missing semantic rationale')
                    if grade is not None and not v.get('evidence'):raise ValueError('Numeric theme grade requires actual lyric evidence')
                    for e in v.get('evidence',[]):
                        if e.get('field')!='lyrics' or not e.get('quote') or e['quote'] not in d.get('lyrics',''):raise ValueError('Theme quote not in original full lyric')
                for qid in semantic_pairs[tid]:
                    v=row['labels'][run.by_query[qid]['group_id']]
                    extra={'document_summary':row.get('summary'),'semantic_profile_input_sha256':row['input_sha256'],
                        'provider':result.get('judge',{}).get('provider','openai-codex-session-subagent'),
                        'original_query_catalog_sha256':contexts['sha256'],
                        'original_query_context_ack':str((path.parent/('root_query_context_ack.json' if result.get('judge',{}).get('provider')=='openai-codex-session-root' else 'query_context_ack.json')).relative_to(run.directory)).replace('\\','/'),
                        'judge_identity':result.get('judge',{}),'lyric_coverage':{'full_lyric_read':row['full_lyric_read'],'representation':'lossless line dictionary',
                        'characters':len(d.get('lyrics','')),'original_lyric_sha256':packet['lyrics']['restored_sha256']}}
                    inserted+=int(store_auto(run,qid,tid,v['grade'],v['reason'],v.get('evidence',[]),v.get('flags',[]),'LLM full-lyric thematic judgment',
                        str(path.relative_to(run.directory)).replace('\\','/'),extra))
                seen.add(tid);documents+=1
        except Exception as exc:errors.append({'file':str(path.relative_to(run.directory)).replace('\\','/'),'error':str(exc)})
    info={'documents_expected':len(packet_by_tid),'documents_imported':documents,'new_pairs_imported':inserted,'errors':errors,
          'all_documents_imported':documents==len(packet_by_tid),'counts':run.counts()}
    atomic_json(run.directory/'semantic_ingest_status.json',info);atomic_json(run.directory/'progress.json',run.counts())
    return info


def automatic_metrics(run):
    """Known-qrels estimates; missing judgments remain missing and coverage is explicit."""
    with run.connect() as db:
        auto={}
        for r in db.execute('SELECT * FROM auto_labels'):
            auto[r['query_id'],r['track_id']]=json.loads(r['label'])
        rank={(r['query_id'],r['mode']):dict(r) for r in db.execute('SELECT * FROM rankings')}
    pools=defaultdict(set)
    for q,t in run.pair_ids():pools[q].add(t)
    rows=[];undefined_queries=[]
    for q in run.queries:
        qid=q['query_id'];pool=pools[qid]
        known={t:auto[qid,t]['auto_grade'] for t in pool if (qid,t) in auto and auto[qid,t]['auto_grade'] is not None}
        missing=[t for t in pool if (qid,t) not in auto]
        unresolved=[t for t in pool if (qid,t) in auto and auto[qid,t]['auto_grade'] is None]
        relevant=sum(g>=2 for g in known.values());gain=any(g>0 for g in known.values())
        if not gain or not relevant:
            undefined_queries.append({'query_id':qid,'query':q['query'],'category':q['category'],
                'known_labels':len(known),'unresolved_pairs':len(unresolved),'unprocessed_pairs':len(missing),
                'known_positive_gain':gain,'known_binary_relevant':relevant})
        for mode in run.manifest['modes']:
            r=rank.get((qid,mode));ids=json.loads(r['response'])['ranking'] if r and r['status']=='ok' else []
            state='complete_judgments' if not missing and not unresolved else 'provisional_unjudged' if not missing else 'pending_labels'
            if r is None or r['status']!='ok':state='retrieval_error'
            # No estimates before all pairs were attempted; no hidden omission of failed queries.
            values=metrics(ids,known) if state in {'complete_judgments','provisional_unjudged'} else {'ndcg@10':None,'mrr@10':None,'recall@100':None}
            if not gain:values['ndcg@10']=None
            if not relevant:values['mrr@10']=None;values['recall@100']=None
            rows.append({'query_id':qid,'query':q['query'],'category':q['category'],'split':q['split'],'mode':mode,
                'judgment_status':state,'pool_pairs':len(pool),'processed_pairs':len(pool)-len(missing),'known_labels':len(known),
                'unresolved_pairs':len(unresolved),'unprocessed_pairs':len(missing),'known_relevant':relevant,'ranking_length':len(ids),
                'judged_at10':sum(t in known for t in ids[:10]),'unjudged_at10':sum(t not in known for t in ids[:10]),
                'judged_fraction_at10':sum(t in known for t in ids[:10])/len(ids[:10]) if ids[:10] else None,
                'human_validated':False,**values})
    aggregates={}
    for mode in run.manifest['modes']:
        groups={}
        for kind,value in [('all','all'),*[('category',x) for x in sorted({q['category'] for q in run.queries})],*[('split',x) for x in ['dev','test']]]:
            selected=[r for r in rows if r['mode']==mode and (kind=='all' or r[kind]==value)]
            keys=['ndcg@10','mrr@10','recall@100']
            groups[kind+':'+value]={'required_queries':len(selected),'per_metric_query_count':{k:sum(r[k] is not None for r in selected) for k in keys},
                **{k:statistics.mean(r[k] for r in selected if r[k] is not None) if any(r[k] is not None for r in selected) else None for k in keys},
                'judged_fraction_at10_macro':statistics.mean(r['judged_fraction_at10'] for r in selected if r['judged_fraction_at10'] is not None)
                    if any(r['judged_fraction_at10'] is not None for r in selected) else None,
                'queries_with_unresolved_labels':sum(r['unresolved_pairs']>0 for r in selected)}
        aggregates[mode]=groups
    counts=run.counts()
    summary={'label':'Evaluasi otomatis hibrida — label tema oleh LLM; katalog/lirik/audio melalui pemeriksaan corpus; tanpa validasi manusia',
        'human_review_required':False,'human_validated':False,'status':'complete_processing' if counts['auto_complete'] else 'incomplete_processing',
        'all_judgments_resolved':counts['auto_labels_resolved'],'counts':counts,'required_query_ids':[q['query_id'] for q in run.queries],
        'ranking_object':'primary results only','pool_depth':100,'queries_dropped':[],
        'queries_with_undefined_metrics':undefined_queries,
        'undefined_metric_policy':'nDCG null if known IDCG=0; MRR and Recall null if no known grade>=2. All mandatory query rows retained; each macro denominator is exported.',
        'unjudged_policy':'Nulls are NOT stored as grade0. Known-qrels estimates use standard no-known-gain contribution for unjudged returned IDs; this is not a judgment of irrelevance. Coverage and provisional_unjudged status are explicit.',
        'recall_scope':'Recall@100 relative only to known relevant documents in frozen pooled qrels, not all relevant corpus documents.',
        'gain':'2^grade-1; discount log2(rank+1)','binary_threshold':2,
        'important_limits':['Automatic judgments are not independent human ground truth.','Objective category metrics are corpus-check proxies; preference percentile rubric is aligned with the feature used by retrieval.',
            'Thematic LLM judgments remain subjective and may be wrong.','Unresolved lyrics/language/data are retained; estimates may be biased by unjudged results.',
            'Current draft/test queries have regression exposure; no claim of independent held-out generalization.'],
        'by_mode':aggregates}
    return rows,summary


def export_automatic(run):
    from .relevance_review import datetime_id
    directory=run.directory/'exports'/(datetime_id()+'_'+uuid.uuid4().hex[:8]);directory.mkdir(parents=True)
    with run.connect() as db:
        records=[json.loads(r['label']) for r in db.execute('SELECT * FROM auto_labels ORDER BY query_id,track_id')]
        human_count=db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]
    rows,summary=automatic_metrics(run)
    with (directory/'auto_labels.jsonl').open('w',encoding='utf-8') as f:
        for record in records:f.write(json.dumps(record,ensure_ascii=False)+'\n')
    with (directory/'qrels_auto.tsv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['query_id','track_id','relevance','label_origin'])
        w.writerows((r['query_id'],r['track_id'],r['auto_grade'],r['label_origin']) for r in records if r['auto_grade'] is not None)
    with (directory/'unresolved_pairs.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['query_id','track_id','reason','flags'])
        w.writerows((r['query_id'],r['track_id'],r['reason'],'; '.join(r['uncertainty_flags'])) for r in records if r['auto_grade'] is None)
    with (directory/'metrics_auto_per_query.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    atomic_json(directory/'metrics_auto_summary.json',summary)
    atomic_json(directory/'export_manifest.json',{'created_utc':now(),'counts':run.counts(),'human_review_required':False,'human_review_records':human_count,
        'qrels_final_not_generated':'No human-reviewed labels are fabricated; this export uses automatic qrels only.',
        'corpus_sha256':run.manifest['corpus_sha256'],'queries_sha256':run.manifest['queries_sha256'],'rubric_sha256':run.manifest['evaluation_policy']['rubric_sha256']})
    mode_rows=[]
    for m in run.manifest['modes']:
        v=summary['by_mode'][m]['all:all'];mode_rows.append([m,*[f"{v[k]:.4f}" if v[k] is not None else 'null' for k in ['ndcg@10','mrr@10','recall@100']],
          '/'.join(str(v['per_metric_query_count'][k]) for k in ['ndcg@10','mrr@10','recall@100'])])
    def table(headers,values):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',*['| '+' | '.join(map(str,r))+' |' for r in values]])
    category_rows=[]
    for c in ['title','artist','lyrics','semantic','audio']:
        for m in run.manifest['modes']:
            v=summary['by_mode'][m]['category:'+c]
            category_rows.append([c,m,*[f"{v[k]:.4f}" if v[k] is not None else 'null' for k in ['ndcg@10','mrr@10','recall@100']],
                '/'.join(str(v['per_metric_query_count'][k]) for k in ['ndcg@10','mrr@10','recall@100']),
                f"{v['judged_fraction_at10_macro']:.4f}" if v['judged_fraction_at10_macro'] is not None else 'null'])
    split_rows=[]
    for split in ['dev','test']:
        for m in run.manifest['modes']:
            v=summary['by_mode'][m]['split:'+split]
            split_rows.append([split,m,*[f"{v[k]:.4f}" if v[k] is not None else 'null' for k in ['ndcg@10','mrr@10','recall@100']],
                '/'.join(str(v['per_metric_query_count'][k]) for k in ['ndcg@10','mrr@10','recall@100'])])
    counts=run.counts();origins=defaultdict(int);grades=defaultdict(int)
    for r in records:origins[r['label_origin']]+=1;grades['null' if r['auto_grade'] is None else str(r['auto_grade'])]+=1
    agents_path=run.directory/'judging_agents.json';agents=json.loads(agents_path.read_text(encoding='utf-8')) if agents_path.exists() else None
    undefined_rows=[[q['query_id'],q['query'],q['known_labels'],q['unresolved_pairs'],q['known_binary_relevant']]
        for q in summary['queries_with_undefined_metrics']]
    undefined_text=table(['Query ID','Query asli','Label diketahui','Unresolved','Relevan biner diketahui'],undefined_rows) if undefined_rows else 'Seluruh query mempunyai gain dan relevan biner yang diketahui.'
    text=f'''# Laporan evaluasi otomatis Music IR

Run `{run.directory.name}`. **Review manusia tidak diwajibkan untuk ekspor ini.** Hasil merupakan evaluasi otomatis hibrida: penilaian makna lirik oleh agent LLM dan pemeriksaan objektif metadata, kutipan, serta angka corpus. Label bukan hasil penilaian manusia dan tidak boleh dinyatakan sebagai akurasi berbasis ground truth manusia.

## Snapshot dan cakupan

Corpus: `{run.manifest['corpus_sha256']}`; query: `{run.manifest['queries_sha256']}`; pipeline: `{run.manifest['implementation_sha256']}`. Seluruh query asli, split, corpus, config, metode, bobot, top-k dan batas kandidat dipertahankan. Ranking/pool digunakan ulang dari `{run.manifest.get('retrieval_reused_from')}`. Tidak ada tuning atau pemilihan query berdasarkan skor evaluasi.

Terdapat {len(run.queries)} query dan {counts['ranking_jobs_completed']} ranking dari E1–E5/AUTO. Pool utama berkedalaman100 berisi {counts['pairs']} pasangan unik. Tema AUTO tetap maksimum24; hasil serupa tidak dimasukkan. Query gagal atau tidak mempunyai relevan diketahui tetap ada pada CSV, tidak dihapus diam-diam.

Otomatis diproses: **{counts['auto_processed']}/{counts['pairs']}**; berlabel numerik: **{counts['auto_completed']}**; belum terselesaikan: **{counts['auto_needs_review']}**; belum diproses: **{counts['auto_unprocessed']}**. Status eksekusi: **{summary['status']}**. Semua judgment terselesaikan: **{summary['all_judgments_resolved']}**. Istilah needs_review pada penyimpanan lama berarti bukti otomatis belum cukup; tidak menjadi kewajiban review manusia untuk ekspor ini. Nilainya tetap null.

## Asal label dan pedoman

Distribusi asal label: `{json.dumps(dict(origins),ensure_ascii=False)}`. Distribusi grade: `{json.dumps(dict(grades))}`.

Skala:3 kebutuhan inti jelas terpenuhi,2 cukup terpenuhi,1 terkait sebagian/lemah,0 tidak memenuhi kebutuhan inti. Ketidakpastian/data hilang=null. Penilaian tema mengacu pada makna penuh lirik dan facet query (misalnya jarak geografis, bukan sekadar jarak emosional). Lirik diberikan lengkap dengan kamus baris yang dapat direkonstruksi tanpa kehilangan teks; urutan serta pengulangan tetap tersedia. Bukti, reason, hash input dan respons agent mentah disimpan. Nama mode, skor, posisi asal, hint ID, dan alasan retrieval tidak diberikan kepada agent.

Katalog dan angka objektif diperiksa dengan kode independen dari output retrieval; ini diberi asal **deterministic checks**, bukan diklaim inferensi LLM. Kutipan lirik menggunakan pencarian literal dan edit terbatas atas seluruh lirik, sehingga hasil kategori ini adalah proksi kecocokan teks. Soft audio high/low memakai rubrik persentil yang ditetapkan sebelum melihat metrik; ini selaras dengan preferensi fitur retrieval sehingga bukan validasi independen metode audio. Genre playlist dan angka audio tidak diperlakukan sebagai kebenaran tema/emosi.

Query happy yang ambigu dioperasionalkan sebagai makna lirik bahagia, bukan persepsi bunyi; interpretasi otomatis ini dicatat pada automatic_rubric.json, bukan persetujuan manusia. Pedoman dibekukan sebelum penilaian/metrik; tidak diubah agar AUTO/E5 memperoleh skor lebih tinggi.

Penilai paralel yang benar-benar digunakan:

```json
{json.dumps(agents,ensure_ascii=False,indent=2)}
```

Provider penilaian tema adalah sesi agent OpenAI Codex; model/revision tepat, parameter sampling, token dan biaya tidak diekspos sehingga tidak dikarang. Label pemeriksaan objektif tidak memakai model. Human review records={human_count}; human_grade/final_grade tidak diisi atas nama pengguna.

Dokumen tema dibagi antartiga agent, dengan tambahan pembacaan langsung oleh assistant induk untuk batch017–018 worker3. Satu dokumen memakai satu profil penilaian yang disimpan; tidak dilakukan pelabelan silang independen, pengukuran kesepakatan antarpenilai, atau adjudikasi manusia. Profil per tema dipakai kembali untuk pasangan query Indonesia/Inggris yang berada dalam group_id kebutuhan yang sama. Pasangan tersebut bukan penilaian independen yang terpisah.

## Definisi metrik dan ketidakpastian

nDCG@10: gain=2^grade−1, discount=log2(rank+1). MRR@10 dan Recall@100: relevan biner grade≥2. Recall dihitung terhadap dokumen relevan yang **diketahui dalam qrels pool**, bukan semua dokumen relevan corpus. Ranking selalu hasil utama; daftar yang lebih pendek tidak dipanjang-panjangkan.

Qrels tidak mengubah null menjadi grade0. Untuk estimasi known-qrels, dokumen unjudged pada ranking tidak menyumbang gain/relevan, sesuai konvensi evaluasi yang dinyatakan; ini bukan keputusan bahwa dokumen tersebut tidak relevan. Query dengan label belum terselesaikan ditandai provisional_unjudged dan cakupan judged@10 diekspor. Bias akibat judgment hilang tetap mungkin. Jika IDCG diketahui nol, nDCG=null; bila tidak ada grade≥2 diketahui, MRR/Recall=null. Macro hanya merata-ratakan nilai terdefinisi, dengan penyebut per metrik terlihat pada tabel/JSON. Angka bukan hasil validasi manusia atau jaminan generalisasi.

Query dengan metrik yang tidak terdefinisi tetap disimpan pada seluruh enam baris mode:

{undefined_text}

## Hasil agregat otomatis

{table(['Mode','nDCG@10','MRR@10','Recall@100 known pool','n query nDCG/MRR/Recall'],mode_rows)}

## Hasil per kategori

{table(['Kategori','Mode','nDCG@10','MRR@10','Recall@100 known pool','n query nDCG/MRR/Recall','Cakupan judged@10'],category_rows)}

Kategori semantic merupakan penilaian makna lirik oleh LLM. Kategori title, artist, lyrics dan audio merupakan proksi pemeriksaan corpus; angka agregat gabungan mewarisi perbedaan sumber tersebut. Bandingkan setiap kategori bersama pedomannya, bukan menyebut keseluruhan tabel sebagai akurasi semantik.

## Hasil per split yang dibekukan

{table(['Split','Mode','nDCG@10','MRR@10','Recall@100 known pool','n query nDCG/MRR/Recall'],split_rows)}

Label test adalah nama split draft yang dipertahankan. Query memiliki paparan regresi/pengembangan sehingga angka test ini tidak membuktikan generalisasi pada test independen.

## Berkas bukti dan ekspor

Ekspor versi ini: `{str(directory.relative_to(run.directory)).replace(chr(92),'/')}`. auto_labels.jsonl memuat grade, asal, alasan, bukti, flags, dan identitas input. qrels_auto.tsv berisi grade numerik saja; unresolved_pairs.csv menyimpan nilai yang tetap tidak diketahui. metrics_auto_per_query.csv menyimpan seluruh {len(rows)} baris query-mode dan cakupan; metrics_auto_summary.json memuat semua penyebut dan kebijakan. semantic_packets/ dan semantic_judgments/ menyimpan input lengkap dan keputusan LLM yang dapat diperiksa. objective_method.json dan automatic_rubric.json menyatakan prosedur pemeriksaan otomatis.

Koreksi validasi data, bila ada, dicatat pada label_data_errata.json beserta label sebelum/sesudah. Satu field corpus berisi petunjuk editor lirik, bukan lirik lagu; label kutipan yang terdampak dikoreksi menjadi null sesuai aturan data tidak cukup. Corpus, ranking, dan rubrik tetap dipertahankan.

Tidak dibuat qrels_final.tsv seolah-olah berlabel manusia. Semua ekspor dapat dipakai langsung sebagai **hasil evaluasi otomatis**, dengan keterangan sumber dan keterbatasan ini tetap dicantumkan. Jangan mengganti istilahnya menjadi ground truth manusia, benchmark independen, atau akurasi pencarian yang telah divalidasi manusia.

## Teks singkat siap dimasukkan ke laporan

Evaluasi dilakukan otomatis pada {len(run.queries)} query dengan pool {counts['pairs']} pasangan query–lagu, yang dibentuk dari hasil utama hingga peringkat100 pada enam konfigurasi retrieval. Pipeline dan parameternya dibekukan. Penilaian tema didasarkan pada pembacaan lirik oleh agent LLM; tugas metadata, kutipan literal, dan batas audio memakai pemeriksaan corpus yang dinyatakan sebagai proksi otomatis. Nilai relevansi menggunakan skala0–3 dan ambang relevan biner≥2. Metrik yang dilaporkan adalah nDCG@10, MRR@10, serta Recall@100 terhadap relevan yang diketahui pada pool. Tidak ada penilaian manusia; karena itu hasil menunjukkan kesesuaian terhadap prosedur penilaian otomatis ini dan tidak membuktikan efektivitas berbasis ground truth manusia. Label yang tidak dapat ditetapkan tetap null dan cakupan judgment dilaporkan.
'''
    report=run.directory/'LAPORAN_EVALUASI_RELEVANSI.md';report.write_text(text,encoding='utf-8')
    (directory/report.name).write_text(text,encoding='utf-8')
    ready_text=text.split('## Teks singkat siap dimasukkan ke laporan\n\n',1)[1]
    (run.directory/'TEKS_SIAP_LAPORAN.md').write_text(ready_text,encoding='utf-8')
    (directory/'TEKS_SIAP_LAPORAN.md').write_text(ready_text,encoding='utf-8')
    info={'created_utc':now(),'directory':str(directory.relative_to(run.directory)).replace('\\','/'),'counts':counts,
        'human_review_required':False,'qrels_final_available':False,'final_query_ids':[],'automatic_report_available':True,
        'automatic_status':summary['status'],'report':str(report),'label_source':'hybrid automatic; not human validated'}
    atomic_json(run.directory/'latest_export.json',info);atomic_json(run.directory/'run_summary.json',info)
    atomic_json(run.directory/'progress.json',counts)
    return info


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    init=s.add_parser('prepare');init.add_argument('--parent',type=Path,required=True);init.add_argument('--run',type=Path,required=True)
    for name in ['objective','ingest','export','repair-data']:
        command=s.add_parser(name);command.add_argument('--run',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':result=prepare(RelevanceRun(a.parent),a.run)
    elif a.command=='objective':result=objective_labels(RelevanceRun(a.run))
    elif a.command=='ingest':result=ingest_semantic(RelevanceRun(a.run))
    elif a.command=='repair-data':result=repair_placeholder_labels(RelevanceRun(a.run))
    elif a.command=='export':result=export_automatic(RelevanceRun(a.run))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
