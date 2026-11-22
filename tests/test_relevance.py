import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_ir.engine import load_config
from music_ir.relevance import RelevanceRun, digest
from music_ir.relevance_judge import (Backend, PROMPT_HASH, batch_label, judge_input, label_pair,
                                     numeric_checks, partition, persist_label, session_packet, import_session, validate_label)
from music_ir.relevance_review import (approve_query, export_run, fork_query, query_candidates,
                                      reveal_auto, save_draft, save_review, stage_metrics, clone_for_judge)


class RelevanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.docs=[{'track_id':i,'track_name':title,'track_artist':artist,'lyrics':lyrics,'lyrics_available':bool(lyrics),
                    'tempo':tempo,'energy':.5,'valence':.5,'danceability':.5,'acousticness':.2,'playlist_genre':['pop']}
                   for i,title,artist,lyrics,tempo in [('A','One','Alice','we celebrate life',120),('B','Two','Bob','we miss the past',130),('C','Three','Carol','',None)]]
        self.queries=[{'query_id':'q1','query':'One','intent_note':'Find title One','category':'title','split':'dev','group_id':'g1','review_status':'draft','hint_track_ids':['C']},
                      {'query_id':'q2','query':'tempo > 120 BPM','intent_note':'Strictly more than120 BPM','category':'audio','split':'test','group_id':'g2','review_status':'draft'}]
        self.run=RelevanceRun.create(self.root/'run',self.docs,self.queries,load_config())
        self.engine=self.fake_engine()
        self.run.prepare(self.engine,progress=lambda *a,**kw:None)
        self.identity={'provider':'fixture-instruction-model','model':'fixture','parameters':{'temperature':0},'prompt_sha256':PROMPT_HASH}

    def fake_engine(self,fail=None,degraded=False):
        test=self
        class Engine:
            docs=test.docs;config=load_config();calls=0
            def search(self,query,mode,top_k):
                self.calls+=1
                if fail and (query,mode)==fail:raise RuntimeError('fixture interruption')
                ids=['C','B','A'] if query=='One' else ['B']
                return {'results':[{'track_id':i} for i in ids],'related_results':[{'track_id':'unused-related'}],
                        'pipeline':{'degraded':degraded},'query_type':'fixture','latency_ms':1}
        return Engine()

    def put(self,qid,tid,grade,status=None):
        d=judge_input(self.run,qid,tid)
        label={'query_id':qid,'track_id':tid,'auto_grade':grade,'reason':'fixture label','evidence':[{'field':'track_name','quote':d['track_name']}],
               'uncertainty_flags':['fixture uncertainty'] if grade is None else []}
        validated=validate_label(label,d)
        persist_label(self.run,d,self.identity,validated,status or ('needs_review' if grade is None else 'ok'),[])

    def test_pool_depth_union_and_resume_keep_all_modes_and_primary_only(self):
        self.assertEqual(self.engine.calls,12);self.assertEqual(self.run.counts()['pairs'],4)
        self.assertNotIn(('q1','unused-related'),self.run.pair_ids())
        fresh=self.fake_engine();self.run.prepare(fresh,progress=lambda *a,**kw:None);self.assertEqual(fresh.calls,0)

    def test_failed_required_query_is_persisted_and_resume_retries_only_failure(self):
        with self.run.connect() as db:db.execute("DELETE FROM rankings WHERE query_id='q2' AND mode='E4'")
        self.run.prepare(self.fake_engine(('tempo > 120 BPM','E4')),progress=lambda *a,**kw:None)
        self.assertFalse(self.run.counts()['pool_complete']);self.assertEqual(self.run.counts()['ranking_errors'],1)
        rows,summary=stage_metrics(self.run,'auto');self.assertEqual(len(rows),12)
        self.assertEqual(next(r for r in rows if r['query_id']=='q2' and r['mode']=='E4')['status'],'retrieval_error_or_missing')
        engine=self.fake_engine();self.run.prepare(engine,progress=lambda *a,**kw:None);self.assertEqual(engine.calls,1)

    def test_changed_frozen_input_rejected(self):
        path=self.run.directory/'queries.json';qs=json.loads(path.read_text());qs[0]['query']='changed';path.write_text(json.dumps(qs))
        with self.assertRaises(ValueError):RelevanceRun(self.run.directory)

    def test_numeric_check_is_independent_and_preserves_strict_boundary_missing(self):
        self.assertFalse(numeric_checks('tempo > 120',self.docs[0])[0]['passed'])
        self.assertTrue(numeric_checks('tempo >= 120',self.docs[0])[0]['passed'])
        self.assertIsNone(numeric_checks('tempo tidak = 120',self.docs[2])[0]['passed'])
        self.assertEqual(numeric_checks('lirik "tempo > 120"',self.docs[0]),[])
        self.assertEqual(numeric_checks('lagu sedih',self.docs[0]),[])

    def test_judge_input_has_no_retrieval_leaks(self):
        d=judge_input(self.run,'q1','A')
        for k in ['mode','score','rank','group','hint_track_ids','reasons','popularity']:self.assertNotIn(k,d)
        self.assertEqual(d['lyrics'],self.docs[0]['lyrics'])

    def test_grade_bool_bad_quote_ids_and_unsupported_positive_rejected(self):
        d=judge_input(self.run,'q1','A')
        valid={'query_id':'q1','track_id':'A','auto_grade':3,'reason':'yes','evidence':[{'field':'lyrics','quote':'celebrate'}],'uncertainty_flags':[]}
        self.assertEqual(validate_label(valid,d)['auto_grade'],3)
        for change in [{'auto_grade':True},{'track_id':'B'},{'evidence':[{'field':'lyrics','quote':'fabricated'}]},{'evidence':[]},{'uncertainty_flags':['ambiguous']}]:
            with self.subTest(change=change),self.assertRaises(ValueError):validate_label({**valid,**change},d)
        d2=judge_input(self.run,'q2','A')
        with self.assertRaises(ValueError):validate_label({**valid,'query_id':'q2'},d2)

    def test_deterministic_partition_covers_entire_text_without_truncation(self):
        d=judge_input(self.run,'q1','A');d['lyrics']='abcde '*3000
        parts=partition(d,4000)
        self.assertGreater(len(parts),1);self.assertEqual(''.join(p['lyrics'] for p in parts),d['lyrics'])
        self.assertEqual(parts[0]['coverage']['start'],0);self.assertEqual(parts[-1]['coverage']['end'],len(d['lyrics']))

    def test_no_backend_does_not_fabricate_labels(self):
        with patch.dict('os.environ',{},clear=True):result=batch_label(self.run)
        self.assertEqual(result['status'],'blocked_backend');self.assertEqual(self.run.counts()['auto_processed'],0)

    def test_label_retries_invalid_output_and_keeps_raw_errors(self):
        backend=Backend('openai-compatible','fixture','http://localhost:1/v1',retries=1)
        good={'query_id':'q1','track_id':'A','auto_grade':3,'reason':'title','evidence':[{'field':'track_name','quote':'One'}],'uncertainty_flags':[]}
        with patch.object(backend,'call',side_effect=[{'content':'not-json','raw_response':'invalid'}, {'content':json.dumps(good),'raw_response':json.dumps(good)}]),patch('time.sleep'):
            self.assertEqual(label_pair(self.run,'q1','A',backend),'ok')
        self.assertEqual(len(list((self.run.directory/'raw_responses').glob('*.json'))),2)
        with self.run.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2)

    def test_resume_skips_cached_label_and_model_change_requires_new_run(self):
        backend=Backend('openai-compatible','fixture','http://localhost:1/v1')
        d=judge_input(self.run,'q1','A');v={'query_id':'q1','track_id':'A','auto_grade':3,'reason':'title','evidence':[{'field':'track_name','quote':'One'}],'uncertainty_flags':[]}
        persist_label(self.run,d,backend.identity(),validate_label(v,d),'ok',[])
        with patch('music_ir.relevance_judge.Backend.from_env',return_value=backend),patch('music_ir.relevance_judge.label_pair',return_value='ok') as call:
            batch_label(self.run);self.assertEqual(call.call_count,3)
        from music_ir.relevance_judge import freeze_judge
        with self.assertRaises(ValueError):freeze_judge(self.run,{**backend.identity(),'model':'another'})

    def test_human_draft_is_not_final_and_query_approval_is_required(self):
        save_draft(self.run,'q1','A','human',3,'draft')
        self.assertEqual(self.run.counts()['human_final_pairs'],0)
        with self.assertRaises(ValueError):save_review(self.run,'q1','A','human','independent',3)
        approve_query(self.run,'q1','human',True)
        review=save_review(self.run,'q1','A','human','independent',3)
        self.assertEqual(review['final_grade'],3);self.assertEqual(review['viewed_auto'],0)

    def test_blind_payload_excludes_proposal_until_reveal_and_logs_post_editing(self):
        self.put('q1','A',3);approve_query(self.run,'q1','human',True)
        result=query_candidates(self.run,'q1','human',0,20)
        self.assertNotIn('auto_grade',json.dumps(result));self.assertNotIn('mode',json.dumps(result))
        reveal_auto(self.run,'q1','A','human')
        saved=save_review(self.run,'q1','A','human','independent',2)
        self.assertEqual(saved['human_review_status'],'post_editing');self.assertEqual(saved['viewed_auto'],1)

    def test_accept_null_or_without_reveal_rejected_correction_needs_reason(self):
        self.put('q1','A',3);self.put('q1','B',None);approve_query(self.run,'q1','human',True)
        with self.assertRaises(ValueError):save_review(self.run,'q1','A','human','accept')
        with self.assertRaises(ValueError):save_review(self.run,'q1','A','human','correct',2,'without reveal')
        reveal_auto(self.run,'q1','B','human')
        with self.assertRaises(ValueError):save_review(self.run,'q1','B','human','accept')
        with self.assertRaises(ValueError):save_review(self.run,'q1','B','human','correct',0)

    def test_stale_review_rejected_and_original_independent_grade_retained(self):
        self.put('q1','A',3);approve_query(self.run,'q1','human',True)
        first=save_review(self.run,'q1','A','human','independent',1)
        with self.assertRaises(ValueError):save_review(self.run,'q1','A','human','independent',2)
        reveal_auto(self.run,'q1','A','human')
        second=save_review(self.run,'q1','A','human','correct',2,'reviewed',first['updated'])
        self.assertEqual(second['independent_grade'],1)

    def test_manual_metric_fixture_and_incomplete_query_never_silently_dropped(self):
        self.put('q1','A',3);self.put('q1','B',2);self.put('q1','C',0)
        rows,summary=stage_metrics(self.run,'auto')
        r=next(r for r in rows if r['query_id']=='q1')
        self.assertAlmostEqual(r['ndcg@10'],(3/math.log2(3)+7/2)/(7+3/math.log2(3)))
        self.assertEqual(r['mrr@10'],.5);self.assertEqual(r['recall@100'],1)
        self.assertEqual(summary['unresolved_query_ids'],['q2']);self.assertEqual(len(rows),12)

    def test_zero_known_relevant_remains_null_and_reported(self):
        for t in ['A','B','C']:self.put('q1',t,0)
        rows,summary=stage_metrics(self.run,'auto')
        self.assertEqual(summary['no_known_relevant_query_ids'],['q1'])
        self.assertIsNone(rows[0]['ndcg@10']);self.assertEqual(rows[0]['status'],'no_known_relevant')

    def test_grade_one_still_has_ndcg_gain_when_binary_recall_is_undefined(self):
        for t in ['A','B','C']:self.put('q1',t,1)
        rows,summary=stage_metrics(self.run,'auto')
        self.assertEqual(rows[0]['ndcg@10'],1);self.assertIsNone(rows[0]['recall@100']);self.assertIsNone(rows[0]['mrr@10'])
        self.assertEqual(summary['by_mode']['E1']['all:all']['per_metric_query_count']['ndcg@10'],1)

    def test_final_qrels_waits_for_all_pairs_and_export_stage_separation(self):
        self.put('q1','A',3);self.put('q1','B',2);self.put('q1','C',0);approve_query(self.run,'q1','human',True)
        save_review(self.run,'q1','A','human','independent',2)
        out=export_run(self.run);self.assertFalse(out['qrels_final_available'])
        self.assertFalse((self.run.directory/out['directory']/'qrels_final.tsv').exists())
        save_review(self.run,'q1','B','human','independent',0);save_review(self.run,'q1','C','human','independent',0)
        out=export_run(self.run);self.assertEqual(out['final_query_ids'],['q1'])
        text=(self.run.directory/out['directory']/'qrels_final.tsv').read_text();self.assertIn('q1\tA\t2',text);self.assertNotIn('q2',text)
        comp=json.loads((self.run.directory/out['directory']/'comparison.json').read_text());self.assertEqual(comp['same_query_ids'],['q1']);self.assertEqual(comp['binary_threshold_crossings'],1)

    def test_all_grades_remain_in_review_queue_and_flag_is_not_grade_zero(self):
        for t,g in [('A',0),('B',1),('C',None)]:self.put('q1',t,g)
        self.assertEqual(query_candidates(self.run,'q1',limit=20)['total'],3)
        r=save_review(self.run,'q1','A','human','flag',reason='bad data');self.assertIsNone(r['final_grade'])

    def test_query_revision_new_version_has_no_copied_labels_or_human_reviews(self):
        self.put('q1','A',3)
        child=fork_query(self.run,'q1','human','Another','New need','clarify')
        new=RelevanceRun(self.root/child['new_run_id'])
        self.assertEqual(new.by_query['q1']['query'],'Another');self.assertEqual(new.counts()['auto_processed'],0)
        self.assertEqual(self.run.by_query['q1']['query'],'One')

    def test_session_import_requires_exact_packet_input_and_is_idempotent(self):
        packet=self.run.directory/'packet.json';session_packet(self.run,packet,1,'q1');p=json.loads(packet.read_text());r=p['records'][0];d=r['input']
        identity={'provider':'openai-codex-session','model':None,'parameters':None,'prompt_sha256':PROMPT_HASH}
        label={'query_id':d['query_id'],'track_id':d['track_id'],'auto_grade':3,'reason':'fixture','evidence':[{'field':'track_name','quote':d['track_name']}],
               'uncertainty_flags':[],'input_sha256':r['input_sha256']}
        bundle={'judge_identity':identity,'session_provenance':'fixture only','packet_file':'packet.json','packet_sha256':p['packet_sha256'],'labels':[label]}
        path=self.run.directory/'labels.json';path.write_text(json.dumps(bundle))
        import_session(self.run,path);import_session(self.run,path);self.assertEqual(self.run.counts()['auto_processed'],1)
        bundle['labels'][0]['input_sha256']='bad';path.write_text(json.dumps(bundle))
        with self.assertRaises(ValueError):import_session(self.run,path)

    def test_api_blind_payload_and_strict_grade_and_path_validation(self):
        from fastapi.testclient import TestClient
        from music_ir.api import app
        self.put('q1','A',3)
        with patch('music_ir.api.SearchEngine',return_value=self.engine),patch('music_ir.relevance_review.RUNS',self.root),TestClient(app) as client:
            base='/relevance/runs/run'
            self.assertEqual(client.get(base).status_code,200)
            data=client.get(base+'/queries/q1?reviewer_id=human&limit=20').json()
            self.assertNotIn('auto_grade',json.dumps(data))
            self.assertEqual(client.put(base+'/queries/q1/tracks/A/draft',json={'reviewer_id':'human','grade':True}).status_code,422)
            self.assertEqual(client.get(base+'/export?name=../corpus.json').status_code,422)

    def test_api_review_reveal_persists_only_explicit_final_decision(self):
        from fastapi.testclient import TestClient
        from music_ir.api import app
        self.put('q1','A',3)
        with patch('music_ir.api.SearchEngine',return_value=self.engine),patch('music_ir.relevance_review.RUNS',self.root),TestClient(app) as client:
            base='/relevance/runs/run/queries/q1'
            client.put(base+'/definition',json={'reviewer_id':'human','approved':True}).raise_for_status()
            client.put(base+'/tracks/A/draft',json={'reviewer_id':'human','grade':1,'reason':'draft'}).raise_for_status()
            self.assertEqual(self.run.counts()['human_final_pairs'],0)
            self.assertEqual(client.post(base+'/tracks/A/proposal',json={'reviewer_id':'human'}).json()['proposal']['auto_grade'],3)
            result=client.put(base+'/tracks/A/review',json={'reviewer_id':'human','action':'correct','grade':2,'reason':'partial fit'}).json()
            self.assertEqual(result['final_grade'],2);self.assertEqual(result['human_review_status'],'corrected');self.assertEqual(result['viewed_auto'],1)

    def test_cross_run_labels_and_legacy_judgments_are_not_implicitly_reused(self):
        self.put('q1','A',3)
        other=RelevanceRun.create(self.root/'another',self.docs,self.queries,load_config())
        self.assertEqual(other.counts()['auto_processed'],0);self.assertEqual(other.counts()['human_final_pairs'],0)

    def test_new_judge_reuses_identical_rankings_without_copying_labels(self):
        self.put('q1','A',3)
        result=clone_for_judge(self.run,self.root/'new-judge')
        self.assertTrue(result['pool_complete']);self.assertEqual(result['pairs'],4);self.assertEqual(result['auto_processed'],0)

    def test_http_provider_protocols_keep_credentials_out_of_identity(self):
        from unittest.mock import MagicMock
        for provider,response in [('ollama',{'model':'served-fixture','message':{'content':'{}'},'prompt_eval_count':12,'eval_count':4}),
                                  ('openai-compatible',{'model':'served-fixture','choices':[{'message':{'content':'{}'}}],'usage':{'prompt_tokens':12,'completion_tokens':4}})]:
            with self.subTest(provider=provider):
                backend=Backend(provider,'requested-fixture','http://127.0.0.1:1/v1' if provider=='openai-compatible' else 'http://127.0.0.1:1',api_key='fixture-secret')
                stream=MagicMock();stream.__enter__.return_value.read.return_value=json.dumps(response).encode()
                with patch('urllib.request.urlopen',return_value=stream) as call:result=backend.call(judge_input(self.run,'q1','A'))
                request=call.call_args.args[0];body=json.loads(request.data)
                self.assertEqual(body['model'],'requested-fixture');self.assertEqual(body['messages'][0]['role'],'system')
                self.assertEqual(result['reported_model'],'served-fixture');self.assertEqual(result['content'],'{}')
                self.assertNotIn('fixture-secret',json.dumps(backend.identity()))
                self.assertTrue(request.full_url.endswith('/api/chat' if provider=='ollama' else '/chat/completions'))

    def test_invalid_provider_envelope_retains_raw_response(self):
        from unittest.mock import MagicMock
        backend=Backend('openai-compatible','fixture','http://127.0.0.1:1/v1')
        stream=MagicMock();stream.__enter__.return_value.read.return_value=b'invalid envelope'
        with patch('urllib.request.urlopen',return_value=stream):result=backend.call(judge_input(self.run,'q1','A'))
        self.assertEqual(result['raw_response'],'invalid envelope');self.assertEqual(result['content'],'')

    def test_failed_context_budget_is_error_null_and_does_not_abort_other_pairs(self):
        backend=Backend('openai-compatible','fixture','http://127.0.0.1:1/v1',context_chars=1)
        with patch.object(backend,'call') as call:status=label_pair(self.run,'q1','A',backend)
        self.assertEqual(status,'error');call.assert_not_called()
        with self.run.connect() as db:label=json.loads(db.execute("SELECT label FROM auto_labels WHERE query_id='q1' AND track_id='A'").fetchone()[0])
        self.assertIsNone(label['auto_grade']);self.assertFalse(label['lyric_coverage']['full_text_supplied'])


if __name__=='__main__':unittest.main()
