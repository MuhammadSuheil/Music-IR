import json
import tempfile
import unittest
from pathlib import Path

from music_ir.engine import load_config
from music_ir.relevance import RelevanceRun, atomic_json
from music_ir.automatic_evaluation import (bank,prepare,objective_labels,ingest_semantic,
                                          automatic_metrics,export_automatic,title_grade,artist_matches,quote_grade,
                                          repair_placeholder_labels)


class AutomaticEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.docs=[{'track_id':tid,'track_name':title,'track_artist':artist,'lyrics':lyric,'lyrics_available':bool(lyric),
                    'tempo':tempo,'energy':energy,'valence':.5,'danceability':.5,'acousticness':.3,'playlist_genre':['pop']}
                   for tid,title,artist,lyric,tempo,energy in [('A','One','Alice','we celebrate life\nwe celebrate life\n',120,.2),
                                                              ('B','Two','Bob','we miss the past',130,.8),('C','Three','Carol','',None,.5)]]
        self.queries=[{'query_id':qid,'query':text,'intent_note':'Fixture need','category':cat,'group_id':group,'split':'dev','review_status':'draft'}
                      for qid,text,cat,group in [('t','One','title','title-one'),('a','Alice','artist','artist-alice'),
                         ('l','lirik "we celebrate life"','lyrics','quote'),('h','tempo > 120 BPM','audio','tempo'),
                         ('p','energi rendah','audio','energy'),('s','lagu happy','semantic','semantic-happy')]]
        parent=RelevanceRun.create(self.root/'parent',self.docs,self.queries,load_config())
        docs=self.docs
        class Engine:
            config=load_config()
            def __init__(self):self.docs=docs
            def search(self,*args):return {'results':[{'track_id':d['track_id']} for d in docs],'related_results':[], 'pipeline':{'degraded':False}}
        parent.prepare(Engine(),progress=lambda *a,**k:None)
        prepare(parent,self.root/'automatic',workers=1);self.run=RelevanceRun(self.root/'automatic')

    def profiles(self,bad_quote=False):
        packet=json.loads((self.run.directory/'semantic_packets/worker_1/batch_001.json').read_text())
        rows=[]
        for item in packet['records']:
            tid=item['track_id'];grade={'A':3,'B':0,'C':None}[tid]
            quote='invented lyric' if bad_quote and tid=='B' else 'we celebrate life' if tid=='A' else 'we miss the past'
            rows.append({'track_id':tid,'input_sha256':item['input_sha256'],'full_lyric_read':tid!='C','summary':'Fixture only',
                'labels':{'semantic-happy':{'grade':grade,'reason':'Fixture judgment','evidence':[{'field':'lyrics','quote':quote}] if tid!='C' else [],'flags':['lyrics_unavailable'] if tid=='C' else []}}})
        path=self.run.directory/'semantic_judgments/worker_1/batch_001.json'
        atomic_json(path,{'worker':1,'batch':1,'judge':{'provider':'synthetic fixture; not actual LLM'},'records':rows})
        return path

    def test_lossless_lyric_bank_preserves_whole_text_order_and_repetition(self):
        text='chorus\nverse\nchorus\nlast line'
        b=bank(text);self.assertEqual(''.join(b['unique_lines'][i] for i in b['line_order']),text)
        self.assertEqual(b['restored_chars'],len(text));self.assertLess(len(b['unique_lines']),len(b['line_order']))

    def test_catalog_checks_do_not_use_hint_or_ranking(self):
        self.assertEqual(title_grade('One','ONE'),3);self.assertEqual(title_grade('One','One - Remastered'),2)
        self.assertEqual(title_grade('One','One More'),0)
        self.assertTrue(artist_matches('Alice','Bob, Alice'));self.assertFalse(artist_matches('Alice','Alicester'))

    def test_quote_full_scan_bounded_error_and_missing_not_zero(self):
        self.assertEqual(quote_grade('lirik "we celebrate life"','a different verse\nwe celebrate life')[0],3)
        self.assertEqual(quote_grade('lirik "make the stars look like there not shining"',"you make the stars look like they're not shining")[0],2)
        self.assertIsNone(quote_grade('lirik "we celebrate life"','')[0])
        self.assertIsNone(quote_grade('lirik "we celebrate life"',"You don't yet have any static lyrics for this song. To start, replace this text.")[0])

    def test_placeholder_erratum_keeps_prior_label_and_does_not_touch_real_lyrics(self):
        objective_labels(self.run)
        # Simulate discovering non-lyric data after earlier labels were recorded.
        self.run.by_track['B']['lyrics']="You don't yet have any static lyrics for this song."
        before=self.run.counts()['auto_processed']
        result=repair_placeholder_labels(self.run)
        self.assertEqual(result['data_errata_applied'],1)
        self.assertEqual(self.run.counts()['auto_processed'],before)
        audit=json.loads((self.run.directory/'label_data_errata.json').read_text())
        self.assertEqual(audit[0]['changes'][0]['before']['auto_grade'],0)
        self.assertIsNone(audit[0]['changes'][0]['after']['auto_grade'])
        self.assertEqual(repair_placeholder_labels(self.run)['data_errata_applied'],0)

    def test_objective_sources_are_explicit_and_no_human_records_created(self):
        objective_labels(self.run)
        with self.run.connect() as db:
            label=json.loads(db.execute("SELECT label FROM auto_labels WHERE query_id='h' AND track_id='A'").fetchone()[0])
            unknown=json.loads(db.execute("SELECT label FROM auto_labels WHERE query_id='l' AND track_id='C'").fetchone()[0])
            self.assertEqual(label['auto_grade'],0);self.assertIn('Deterministic',label['label_origin']);self.assertIsNone(unknown['auto_grade'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM query_reviews').fetchone()[0],0)

    def test_semantic_quote_validation_never_fabricates_missing_profile(self):
        self.profiles(bad_quote=True);status=ingest_semantic(self.run)
        self.assertTrue(status['errors']);self.assertFalse(status['all_documents_imported'])
        with self.run.connect() as db:self.assertIsNone(db.execute("SELECT label FROM auto_labels WHERE query_id='s' AND track_id='B'").fetchone())

    def test_semantic_profiles_resume_idempotently_with_uncertainty_kept_null(self):
        self.profiles();first=ingest_semantic(self.run);second=ingest_semantic(self.run)
        self.assertEqual(first['new_pairs_imported'],3);self.assertEqual(second['new_pairs_imported'],0)
        self.assertTrue(first['all_documents_imported'])
        with self.run.connect() as db:
            self.assertIsNone(json.loads(db.execute("SELECT label FROM auto_labels WHERE query_id='s' AND track_id='C'").fetchone()[0])['auto_grade'])

    def test_metrics_and_export_need_no_human_approval_and_show_unjudged_coverage(self):
        objective_labels(self.run);self.profiles();ingest_semantic(self.run)
        rows,summary=automatic_metrics(self.run)
        self.assertEqual(len(rows),36);self.assertEqual(summary['status'],'complete_processing');self.assertFalse(summary['human_validated'])
        sem=next(r for r in rows if r['query_id']=='s')
        self.assertEqual(sem['judgment_status'],'provisional_unjudged');self.assertEqual(sem['unjudged_at10'],1)
        self.assertEqual(sem['mrr@10'],1);self.assertEqual(sem['recall@100'],1)
        export=export_automatic(self.run)
        path=self.run.directory/export['directory']
        self.assertTrue((path/'qrels_auto.tsv').exists());self.assertFalse((path/'qrels_final.tsv').exists())
        self.assertEqual(self.run.counts()['human_final_pairs'],0);self.assertFalse(export['human_review_required'])

    def test_pending_query_not_silently_removed_or_filled_with_zero(self):
        objective_labels(self.run);rows,summary=automatic_metrics(self.run)
        sem=[r for r in rows if r['query_id']=='s']
        self.assertEqual(len(sem),6);self.assertTrue(all(r['judgment_status']=='pending_labels' for r in sem))
        self.assertTrue(all(r['ndcg@10'] is None for r in sem));self.assertEqual(summary['queries_dropped'],[])

    def test_modified_lyric_packet_and_rubric_are_rejected(self):
        self.profiles();p=self.run.directory/'semantic_packets/worker_1/batch_001.json'
        packet=json.loads(p.read_text());packet['records'][0]['lyrics']['unique_lines'][0]='changed source\n';atomic_json(p,packet)
        status=ingest_semantic(self.run);self.assertTrue(status['errors']);self.assertEqual(status['new_pairs_imported'],0)
        r=self.run.directory/'automatic_rubric.json';rubric=json.loads(r.read_text());rubric['metadata']='changed';atomic_json(r,rubric)
        with self.assertRaises(ValueError):ingest_semantic(self.run)


if __name__=='__main__':unittest.main()
