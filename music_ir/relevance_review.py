"""Explicit human decisions and stage-separated metrics over immutable run pools."""
import csv
import json
import statistics
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from .relevance import RelevanceRun, RUNS, atomic_json, now
from .relevance_judge import judge_input
from .evaluate import metrics


def reviewer(value):
    from .benchmark import BenchmarkStore
    return BenchmarkStore.annotator(value)


def open_run(run_id):
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', run_id) or '..' in run_id:
        raise ValueError('Run ID tidak valid.')
    path=(RUNS/run_id).resolve()
    if not path.is_relative_to(RUNS.resolve()) or not (path/'manifest.json').exists():raise KeyError('Run tidak ditemukan.')
    return RelevanceRun(path)


def runs_summary():
    rows=[]
    if RUNS.exists():
        for path in sorted(RUNS.iterdir(),reverse=True):
            if path.is_dir() and (path/'manifest.json').exists():
                try:rows.append(RelevanceRun(path).counts())
                except (ValueError,OSError) as exc:rows.append({'run_id':path.name,'error':str(exc)})
    return {'runs':rows}


def run_summary(run):
    with run.connect() as db:
        pairs=dict(db.execute('SELECT query_id,COUNT(*) FROM pairs GROUP BY query_id').fetchall())
        finals=dict(db.execute('SELECT query_id,COUNT(*) FROM reviews WHERE final_grade IS NOT NULL GROUP BY query_id').fetchall())
        qs={r['query_id']:dict(r) for r in db.execute('SELECT * FROM query_reviews')}
    return {**run.counts(),'human_review_required':not run.manifest.get('evaluation_policy',{}).get('automatic_only',False),
            'automatic_label_source':run.manifest.get('evaluation_policy',{}).get('labeling'),
            'queries':[{'query_id':q['query_id'],'query':q['query'],'category':q['category'],'split':q['split'],
             'user_need':q['intent_note'],'definition_approved':bool(qs.get(q['query_id'],{}).get('approved')),
             'pool_count':pairs.get(q['query_id'],0),'final_count':finals.get(q['query_id'],0)} for q in run.queries],
            'note':'Label otomatis tetap provisional. Hanya tindakan manusia eksplisit mengisi final_grade. Query/kriteria berubah memerlukan run baru.'}


def query_candidates(run,qid,reviewer_id='',offset=0,limit=1):
    if qid not in run.by_query:raise KeyError('Query tidak ditemukan.')
    if offset<0 or not 1<=limit<=20:raise ValueError('Offset/limit tidak valid.')
    # Deterministic blind order, independent of grade, source method, and ranking.
    from .relevance import digest
    ids=sorted([t for _,t in run.pair_ids(qid)],key=lambda t:digest([qid,t]))
    with run.connect() as db:
        rows=[]
        for tid in ids[offset:offset+limit]:
            d=run.by_track[tid]
            review=db.execute('SELECT * FROM reviews WHERE query_id=? AND track_id=?',(qid,tid)).fetchone()
            draft=db.execute('SELECT body FROM drafts WHERE query_id=? AND track_id=? AND reviewer_id=?',(qid,tid,reviewer_id)).fetchone()
            auto=db.execute('SELECT status FROM auto_labels WHERE query_id=? AND track_id=?',(qid,tid)).fetchone()
            # All grades, including0/1 and unresolved pairs, remain in this queue.
            rows.append({'track_id':tid,'title':d['track_name'],'artist':d['track_artist'],'album':d.get('track_album_name',''),
                         'genres':d.get('playlist_genre',[]),'lyrics':d.get('lyrics',''),
                         'audio':{k:d.get(k) for k in ['tempo','energy','valence','danceability','acousticness']},
                         'numeric_checks':judge_input(run,qid,tid)['independent_numeric_checks'],
                         'auto_available':auto is not None,'auto_payload_hidden':True,
                         'review':dict(review) if review else None,'draft':json.loads(draft[0]) if draft else None})
    q=run.by_query[qid]
    return {'query':{'query_id':qid,'query':q['query'],'user_need':q['intent_note'],'category':q['category'],'split':q['split']},
            'candidates':rows,'offset':offset,'total':len(ids),'limit':limit}


def reveal_auto(run,qid,tid,reviewer_id):
    reviewer_id=reviewer(reviewer_id)
    if (qid,tid) not in set(run.pair_ids(qid)):raise KeyError('Pasangan tidak ada dalam pool.')
    with run.connect() as db:
        record=db.execute('SELECT label,status FROM auto_labels WHERE query_id=? AND track_id=?',(qid,tid)).fetchone()
        if not record:raise KeyError('Label awal belum tersedia untuk pasangan ini.')
        stamp=now();db.execute('INSERT OR IGNORE INTO exposures VALUES (?,?,?,?)',(qid,tid,reviewer_id,stamp))
        db.execute('INSERT INTO review_history(kind,query_id,track_id,reviewer_id,created,payload) VALUES (?,?,?,?,?,?)',
                   ('reveal_auto',qid,tid,reviewer_id,stamp,'{}'))
    return {'status':record['status'],'proposal':json.loads(record['label']),'exposure_recorded':True,
            'review_method_note':'Keputusan sesudah melihat usulan dicatat sebagai post-editing.'}


def approve_query(run,qid,reviewer_id,approved,notes=''):
    reviewer_id=reviewer(reviewer_id)
    if qid not in run.by_query:raise KeyError('Query tidak ditemukan.')
    if type(approved) is not bool:raise ValueError('approved harus boolean.')
    if not approved and not notes.strip():raise ValueError('Alasan diperlukan untuk menandai query bermasalah.')
    with run.connect() as db:
        stamp=now();db.execute('INSERT OR REPLACE INTO query_reviews VALUES (?,?,?,?,?)',(qid,reviewer_id,int(approved),notes,stamp))
        db.execute('INSERT INTO review_history(kind,query_id,track_id,reviewer_id,created,payload) VALUES (?,?,?,?,?,?)',
                   ('query_review',qid,None,reviewer_id,stamp,json.dumps({'approved':approved,'notes':notes})))
    return {'query_id':qid,'definition_approved':approved,'updated':stamp}


def save_draft(run,qid,tid,reviewer_id,grade,reason):
    reviewer_id=reviewer(reviewer_id)
    if (qid,tid) not in set(run.pair_ids(qid)):raise KeyError('Pasangan tidak ada dalam pool.')
    if grade is not None and (type(grade) is not int or grade not in range(4)):raise ValueError('Grade tidak valid.')
    if len(reason)>4000:raise ValueError('Catatan terlalu panjang.')
    body={'grade':grade,'reason':reason}
    with run.connect() as db:db.execute('INSERT OR REPLACE INTO drafts VALUES (?,?,?,?,?)',(qid,tid,reviewer_id,json.dumps(body),now()))
    return {'saved':True,'finalized':False,'draft':body}


def save_review(run,qid,tid,reviewer_id,action,grade=None,reason='',expected_updated=None):
    reviewer_id=reviewer(reviewer_id)
    if (qid,tid) not in set(run.pair_ids(qid)):raise KeyError('Pasangan tidak ada dalam pool.')
    if action not in {'independent','accept','correct','flag'}:raise ValueError('Tindakan tidak dikenal.')
    if len(reason)>4000:raise ValueError('Catatan terlalu panjang.')
    with run.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous=db.execute('SELECT * FROM reviews WHERE query_id=? AND track_id=?',(qid,tid)).fetchone()
        if (previous['updated'] if previous else None)!=expected_updated:raise ValueError('Keputusan berubah sejak halaman dimuat. Muat ulang sebelum menyimpan.')
        query=db.execute('SELECT approved FROM query_reviews WHERE query_id=?',(qid,)).fetchone()
        if action!='flag' and not (query and query[0]):raise ValueError('Setujui definisi kebutuhan query terlebih dahulu.')
        exposed=db.execute('SELECT 1 FROM exposures WHERE query_id=? AND track_id=? AND reviewer_id=?',(qid,tid,reviewer_id)).fetchone() is not None
        auto=db.execute('SELECT label FROM auto_labels WHERE query_id=? AND track_id=?',(qid,tid)).fetchone()
        automatic=json.loads(auto[0]) if auto else None
        if action=='accept':
            if not exposed or not automatic or automatic['auto_grade'] is None:raise ValueError('Buka usulan dengan grade valid sebelum menyetujui.')
            grade=automatic['auto_grade']
        elif action=='correct':
            if not exposed or not automatic:raise ValueError('Koreksi memerlukan usulan yang sudah dibuka; gunakan penilaian mandiri bila belum ada usulan.')
        elif action=='flag':
            grade=None
        if action in {'correct','flag'} and not reason.strip():raise ValueError('Alasan koreksi/masalah wajib diisi.')
        if action!='flag' and (type(grade) is not int or grade not in range(4)):raise ValueError('Pilih grade0–3.')
        status='flagged' if action=='flag' else 'accepted' if action=='accept' else 'corrected' if action=='correct' else 'post_editing' if exposed else 'independent'
        independent=previous['independent_grade'] if previous else None
        if status=='independent' and independent is None:independent=grade
        stamp=now();record={'query_id':qid,'track_id':tid,'reviewer_id':reviewer_id,'human_grade':grade,
          'human_review_status':status,'final_grade':grade,'reason':reason,'viewed_auto':int(exposed),'independent_grade':independent,'updated':stamp}
        db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)',tuple(record.values()))
        db.execute('INSERT INTO review_history(kind,query_id,track_id,reviewer_id,created,payload) VALUES (?,?,?,?,?,?)',
                   ('pair_review',qid,tid,reviewer_id,stamp,json.dumps({'previous':dict(previous) if previous else None,'current':record},ensure_ascii=False)))
    return record


def fork_query(run,qid,reviewer_id,new_query,new_need,reason):
    reviewer_id=reviewer(reviewer_id)
    if qid not in run.by_query:raise KeyError('Query tidak ditemukan.')
    if not new_query.strip() or not new_need.strip() or not reason.strip():raise ValueError('Query, kebutuhan, dan alasan revisi wajib diisi.')
    queries=[{**q,'query':new_query.strip(),'intent_note':new_need.strip(),'review_status':'draft','revision_origin':'human_edit'} if q['query_id']==qid else dict(q) for q in run.queries]
    path=run.directory.parent/('relevance_'+datetime_id()+'_'+uuid.uuid4().hex[:6])
    child=RelevanceRun.create(path,run.docs,queries,run.manifest['config'],run.manifest['backend'])
    child.manifest['parent_run']=run.directory.name
    child.manifest['revision']={'query_id':qid,'reviewer_id':reviewer_id,'reason':reason,'time':now(),'labels_carried_forward':0}
    atomic_json(path/'manifest.json',child.manifest)
    return {'new_run_id':path.name,'parent_run':run.directory.name,'requires_new_pool_and_labels':True}


def datetime_id():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def clone_for_judge(run,directory):
    """Reuse only frozen rankings/pool when changing judge; no labels/reviews carried forward."""
    if not run.counts()['pool_complete']:raise ValueError('Pool asal harus lengkap sebelum digunakan ulang.')
    child=RelevanceRun.create(directory,run.docs,run.queries,run.manifest['config'],run.manifest['backend'])
    if child.manifest['implementation_sha256']!=run.manifest['implementation_sha256']:
        raise ValueError('Implementasi retrieval berubah; ranking lama tidak digunakan ulang.')
    with run.connect() as source,child.connect() as target:
        target.executemany('INSERT INTO rankings VALUES (?,?,?,?,?,?)',[tuple(r) for r in source.execute('SELECT * FROM rankings')])
        target.executemany('INSERT INTO pairs VALUES (?,?)',[tuple(r) for r in source.execute('SELECT * FROM pairs')])
    child.manifest['retrieval_reused_from']=run.directory.name
    child.manifest['reuse_policy']='same frozen corpus/query/config/implementation/rankings; zero labels or human reviews transferred'
    atomic_json(child.directory/'manifest.json',child.manifest);child.export_rankings()
    return child.counts()


def stage_metrics(run,stage,query_ids=None):
    if stage not in {'auto','final'}:raise ValueError('Stage harus auto/final.')
    with run.connect() as db:
        all_pairs=defaultdict(set)
        for r in db.execute('SELECT * FROM pairs'):all_pairs[r['query_id']].add(r['track_id'])
        rankings={(r['query_id'],r['mode']):dict(r) for r in db.execute('SELECT * FROM rankings')}
        labels=defaultdict(dict)
        if stage=='auto':
            for r in db.execute('SELECT * FROM auto_labels'):
                label=json.loads(r['label'])
                if r['status']=='ok' and type(label.get('auto_grade')) is int:labels[r['query_id']][r['track_id']]=label['auto_grade']
        else:
            for r in db.execute('SELECT * FROM reviews WHERE final_grade IS NOT NULL'):labels[r['query_id']][r['track_id']]=r['final_grade']
        approved={r[0] for r in db.execute('SELECT query_id FROM query_reviews WHERE approved=1')}
    rows=[];eligible=[];unresolved=[];no_relevant=[]
    queries=[q for q in run.queries if query_ids is None or q['query_id'] in query_ids]
    for q in queries:
        qid=q['query_id'];pair_ids=all_pairs[qid]
        ranking_complete=all(rankings.get((qid,m),{}).get('status')=='ok' for m in run.manifest['modes'])
        ready=ranking_complete and bool(pair_ids) and set(labels[qid])==pair_ids and (stage=='auto' or qid in approved)
        known_relevant=sum(g>=2 for g in labels[qid].values())
        if ready and known_relevant:eligible.append(qid)
        elif ready:no_relevant.append(qid)
        else:unresolved.append(qid)
        for mode in run.manifest['modes']:
            record=rankings.get((qid,mode));status='ok' if ready and known_relevant else 'no_known_relevant' if ready else 'unresolved_pool_labels_or_query'
            ids=json.loads(record['response'])['ranking'] if record and record['status']=='ok' else []
            if not record or record['status']!='ok':status='retrieval_error_or_missing'
            values=metrics(ids,labels[qid]) if status in {'ok','no_known_relevant'} else {'ndcg@10':None,'mrr@10':None,'recall@100':None}
            if status=='no_known_relevant':
                values['mrr@10']=None;values['recall@100']=None
                if not any(g>0 for g in labels[qid].values()):values['ndcg@10']=None
            rows.append({'query_id':qid,'category':q['category'],'split':q['split'],'mode':mode,'stage':stage,'status':status,
                         'ranking_length':len(ids),'pool_size':len(pair_ids),'judged_pairs':len(labels[qid]),'known_relevant':known_relevant,
                         'unjudged_in_ranking':sum(t not in labels[qid] for t in ids),
                         'error':record.get('error') if record else 'ranking not yet recorded',**values})
    by_mode={}
    for mode in run.manifest['modes']:
        groups={}
        for kind,group in [('all','all'),*[('category',c) for c in sorted({q['category'] for q in queries})],*[('split',s) for s in sorted({q['split'] for q in queries})]]:
            selected=[r for r in rows if r['mode']==mode and r['status'] in {'ok','no_known_relevant'} and (kind=='all' or r[kind]==group)]
            keys=['ndcg@10','mrr@10','recall@100']
            groups[kind+':'+group]={'eligible_query_count':sum(r['status']=='ok' for r in selected),
                'per_metric_query_count':{k:sum(r[k] is not None for r in selected) for k in keys},
                **{k:statistics.mean(r[k] for r in selected if r[k] is not None) if any(r[k] is not None for r in selected) else None for k in keys}}
        by_mode[mode]=groups
    summary={'label':'Evaluasi berdasarkan label otomatis LLM — provisional' if stage=='auto' else 'Evaluasi berdasarkan label final hasil review manusia',
             'stage':stage,'status':'complete' if not unresolved else 'incomplete','required_query_ids':[q['query_id'] for q in queries],
             'eligible_query_ids':eligible,'unresolved_query_ids':unresolved,'no_known_relevant_query_ids':no_relevant,
             'zero_relevant_policy':'Retain no_known_relevant queries. nDCG is null only when IDCG=0; grade1 still has gain. MRR/Recall are null without known grades>=2. Macro excludes undefined values per metric and reports each denominator. Never raise grades.',
             'ndcg_gain':'2^grade-1; discount log2(rank+1)','binary_relevance':'grade>=2',
             'recall_denominator':'Relevant documents known in this frozen pooled qrels, NOT all relevant corpus documents',
             'unjudged_policy':'Missing/null is unresolved, not human0. Query pool must be fully labeled before metrics; no outside-pool negatives are inferred.',
             'ranking_object':run.manifest['ranking_object'],'pool_depth':100,'query_definitions':'automatic metrics use existing draft needs; final requires explicit human query approval',
             'auto_human_comparison_requires_same_query_ids_and_pool':True,'by_mode':by_mode}
    return rows,summary


def export_run(run):
    directory=run.directory/'exports'/(datetime_id()+'_'+uuid.uuid4().hex[:8]);directory.mkdir(parents=True)
    with run.connect() as db:
        auto=[json.loads(r['label']) for r in db.execute('SELECT * FROM auto_labels ORDER BY query_id,track_id')]
        reviews=[dict(r) for r in db.execute('SELECT * FROM reviews ORDER BY query_id,track_id')]
        history=[dict(r) for r in db.execute('SELECT * FROM review_history ORDER BY id')]
    for name,rows in [('auto_labels.jsonl',auto),('human_reviews.jsonl',reviews),('human_review_history.jsonl',history)]:
        (directory/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    automatic_by_pair={(a['query_id'],a['track_id']):a for a in auto}
    human_by_pair={(r['query_id'],r['track_id']):r for r in reviews}
    with (directory/'pair_status.jsonl').open('w',encoding='utf-8') as f:
        for key in run.pair_ids():
            a=automatic_by_pair.get(key);h=human_by_pair.get(key)
            row={'query_id':key[0],'track_id':key[1],'auto_grade':a.get('auto_grade') if a else None,
                 'auto_status':'not_processed' if a is None else 'needs_review' if a.get('auto_grade') is None else 'labeled',
                 'human_grade':h['human_grade'] if h else None,'human_review_status':h['human_review_status'] if h else 'pending',
                 'final_grade':h['final_grade'] if h else None,'reviewer_id':h['reviewer_id'] if h else None,
                 'human_reason':h['reason'] if h else None,'human_reviewed_utc':h['updated'] if h else None}
            f.write(json.dumps(row,ensure_ascii=False)+'\n')
    summaries={}
    for stage in ['auto','final']:
        rows,summary=stage_metrics(run,stage);summaries[stage]=summary
        with (directory/('metrics_'+stage+'_per_query.csv')).open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        atomic_json(directory/('metrics_'+stage+'_summary.json'),summary)
    def tsv(name,rows):
        with (directory/name).open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f,delimiter='\t');w.writerow(['query_id','track_id','relevance']);w.writerows(rows)
    tsv('qrels_auto.tsv',[(a['query_id'],a['track_id'],a['auto_grade']) for a in auto if a.get('auto_grade') is not None])
    final_ids=set(summaries['final']['eligible_query_ids']+summaries['final']['no_known_relevant_query_ids'])
    if final_ids:tsv('qrels_final.tsv',[(r['query_id'],r['track_id'],r['final_grade']) for r in reviews if r['query_id'] in final_ids and r['final_grade'] is not None])
    comparable=sorted(set(summaries['auto']['eligible_query_ids'])&set(summaries['final']['eligible_query_ids']))
    _,auto_same=stage_metrics(run,'auto',comparable);_,final_same=stage_metrics(run,'final',comparable)
    autos={(a['query_id'],a['track_id']):a for a in auto};changes=Counter();cross=0
    for r in reviews:
        a=autos.get((r['query_id'],r['track_id']),{}).get('auto_grade');b=r['final_grade']
        if a is not None and b is not None:
            changes[str(a)+'->'+str(b)]+=1;cross+=int((a>=2)!=(b>=2))
    def ordering(summary):
        values={m:v['all:all']['ndcg@10'] for m,v in summary['by_mode'].items()}
        return sorted(values,key=lambda m:(-values[m],m)) if all(v is not None for v in values.values()) else None
    comparison={'same_query_ids':comparable,'same_pool':True,'auto_same_queries':auto_same,'final_same_queries':final_same,
       'fully_reviewed_query_ids':sorted(final_ids),'excluded_from_comparison':sorted(final_ids-set(comparable)),
       'accepted_pairs':sum(r['human_review_status']=='accepted' for r in reviews),
       'corrected_pairs':sum(r['human_review_status']=='corrected' for r in reviews),
       'independent_pairs':sum(r['human_review_status']=='independent' for r in reviews),
       'post_editing_pairs':sum(bool(r['viewed_auto']) for r in reviews),'flagged_pairs':sum(r['human_review_status']=='flagged' for r in reviews),
       'grade_transitions':dict(changes),'binary_threshold_crossings':cross,'mode_order_ndcg_auto':ordering(auto_same),'mode_order_ndcg_final':ordering(final_same),
       'mode_order_ties':'Equal metrics sorted alphabetically only for presentation, not a claim of superiority',
       'review_method':'Decisions after any proposal reveal are post-editing. Independent initial grades are retained separately.'}
    comparison['metric_deltas']={m:{k:(final_same['by_mode'][m]['all:all'][k]-auto_same['by_mode'][m]['all:all'][k])
        if final_same['by_mode'][m]['all:all'][k] is not None and auto_same['by_mode'][m]['all:all'][k] is not None else None
        for k in ['ndcg@10','mrr@10','recall@100']} for m in run.manifest['modes']}
    usages=[]
    with run.connect() as db:
        for row in db.execute("SELECT detail FROM attempts WHERE status='ok'"):
            detail=json.loads(row[0]);usages.append(detail)
    atomic_json(directory/'usage_summary.json',{'calls_with_response':len(usages),'usage_as_reported':[u for u in usages],
         'total_cost_as_reported':sum(u['cost_as_reported'] for u in usages if type(u.get('cost_as_reported')) in (int,float))
             if any(type(u.get('cost_as_reported')) in (int,float) for u in usages) else None,
         'currency':'provider-defined if supplied; not inferred','estimated_cost':False,
         'session_token_usage':None,'session_cost':None,'note':'Session/backend values not exposed remain null; no cost or token estimates fabricated.'})
    atomic_json(directory/'comparison.json',comparison)
    info={'created_utc':now(),'directory':str(directory.relative_to(run.directory)).replace('\\','/'),'counts':run.counts(),
          'qrels_final_available':bool(final_ids),'final_query_ids':sorted(final_ids),'auto_status':summaries['auto']['status'],'final_status':summaries['final']['status']}
    atomic_json(directory/'export_manifest.json',info);atomic_json(run.directory/'latest_export.json',info)
    return info


def write_report(run):
    if run.manifest.get('evaluation_policy',{}).get('automatic_only'):
        from .automatic_evaluation import export_automatic
        return export_automatic(run)
    summary=run.counts();latest=export_run(run);path=run.directory/latest['directory']
    auto=json.loads((path/'metrics_auto_summary.json').read_text(encoding='utf-8'))
    final=json.loads((path/'metrics_final_summary.json').read_text(encoding='utf-8'))
    judge_path=run.directory/'judge_config.json';judge=json.loads(judge_path.read_text(encoding='utf-8')) if judge_path.exists() else None
    text=f'''# Laporan evaluasi relevansi Music IR

Run `{run.directory.name}`, corpus `{run.manifest['corpus_sha256']}`, queries `{run.manifest['queries_sha256']}`.
Konfigurasi dan implementasi retrieval dibekukan. Tidak ada tuning. Objek ranking hasil utama; seluruh enam mode sampai kedalaman100, termasuk daftar yang memang lebih pendek (misalnya tema AUTO maksimum24).

Progres saat laporan dibuat:

```json
{json.dumps(summary,ensure_ascii=False,indent=2)}
```

Penilai awal yang benar-benar tercatat:

```json
{json.dumps(judge,ensure_ascii=False,indent=2)}
```

Label otomatis adalah provisional, bukan qrels manusia. Jika provider sesi Codex, hanya label pada respons sesi yang diimpor telah dinilai; session/subscription tidak dianggap API batch terkonfigurasi. Model persis/parameter/token/biaya yang tidak diekspos tetap null. Label belum diproses tidak diisi aturan, angka acak, atau grade0. Lihat backend_discovery.json dan batch_status.json jika tersedia.

Pool lengkap: {summary['pool_complete']}; pasangan {summary['pairs']}; otomatis diproses {summary['auto_processed']}; belum diproses {summary['auto_unprocessed']}; gagal {summary['auto_errors']}; needs_review {summary['auto_needs_review']}.
Tahap otomatis seluruh pool diproses: {summary['auto_complete']}; seluruh label terselesaikan: {summary['auto_labels_resolved']}. Review manusia selesai: {summary['human_complete']}.

Metrik otomatis berstatus **{auto['status']}**, query layak {len(auto['eligible_query_ids'])}/{len(run.queries)}; final berstatus **{final['status']}**, query layak {len(final['eligible_query_ids'])}/{len(run.queries)}. Macro yang tersedia hanya pada query yang seluruh poolnya terselesaikan; daftar query wajib, belum selesai, retrieval error, dan tanpa relevan disimpan eksplisit. Tidak ada klaim keunggulan mode dari hasil incomplete.

Definisi: gain nDCG=2^grade−1, relevan biner grade≥2. Recall@100 relatif pada dokumen relevan yang diketahui dalam pool, bukan seluruh corpus. Dokumen di luar pool tidak diasumsikan0. Query tanpa grade≥2 tetap dicatat; MRR/Recall null, nDCG tetap dihitung jika IDCG>0 (grade1 masih punya gain), dan nDCG null jika seluruh gain0. Penyebut macro per metrik dilaporkan. Perbandingan otomatis/final menggunakan query dan pool yang sama dengan metrik terdefinisi di kedua tahap; query yang tidak dapat dibandingkan dicatat. Lihat comparison.json.

Ekspor terbaru: `{latest['directory']}`. Di dalamnya tersedia auto_labels.jsonl, qrels_auto.tsv, human_reviews.jsonl, human_review_history.jsonl, metrics_auto/final_per_query.csv, metrics_auto/final_summary.json, comparison.json dan export_manifest.json. qrels_final.tsv hanya dibuat bila setidaknya satu query disetujui dan seluruh poolnya selesai direview; tidak dibuat sebagai file seolah telah dinilai ketika belum tersedia.

Buka halaman `http://127.0.0.1:8501/?view=relevance`. Pilih run/query, isi reviewer_id, setujui kebutuhan, baca seluruh bukti, simpan grade mandiri atau buka usulan dan setujui/koreksi/tandai masalah. Draft autosave tidak memfinalisasi grade. Semua pasangan, termasuk grade0/1 dan unresolved, ada pada antrean. Sesudah melihat usulan, keputusan dicatat sebagai post-editing. Tidak ada persetujuan massal otomatis.

Perintah dari root repository:

```powershell
.\\.venv\\Scripts\\python.exe -m music_ir.relevance pool --run "{run.directory}"
.\\.venv\\Scripts\\python.exe -m music_ir.relevance label --run "{run.directory}" --smoke
.\\.venv\\Scripts\\python.exe -m music_ir.relevance label --run "{run.directory}" --retry-errors
.\\.venv\\Scripts\\python.exe -m music_ir.relevance report --run "{run.directory}"
.\\run.ps1 api
.\\run.ps1 ui
```

Batch HTTP memerlukan MUSIC_IR_JUDGE_PROVIDER, MUSIC_IR_JUDGE_MODEL, MUSIC_IR_JUDGE_BASE_URL dan MUSIC_IR_JUDGE_API_KEY bila provider memerlukan key. Jangan tempel key pada report. Ollama memakai base URL server; OpenAI-compatible memakai base URL berakhiran/v1. Model/prompt/parameter berubah mengharuskan run baru. Packet sesi dan import-session mendukung penilaian langsung oleh assistant dengan hash input/prompt, tanpa menyatakannya sebagai API batch.

Query/kriteria yang diubah lewat halaman review membuat run baru, tidak mengedit snapshot atau label lama. Draft query asal belum disetujui manusia; query test yang pernah muncul pada regresi tidak otomatis independen. Metode pengambilan lirik dan kesesuaian pasangan rekaman tetap perlu diperiksa manusia. Penggunaan web, jika ada, harus dicatat sebagai pelengkap dan tidak menggantikan bukti corpus yang dibekukan.
'''
    (run.directory/'LAPORAN_EVALUASI_RELEVANSI.md').write_text(text,encoding='utf-8')
    return {'report':str(run.directory/'LAPORAN_EVALUASI_RELEVANSI.md'),**latest}
