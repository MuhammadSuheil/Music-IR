import sys,json,collections
from audit_collect import ROOT,OUT,E,write
from music_ir.data import load_docs
from music_ir.engine import load_config
from transformers import AutoTokenizer
c=load_config();docs=load_docs()
t=AutoTokenizer.from_pretrained(c['model_name'],revision=c['model_revision'],cache_dir=str(ROOT/'.cache/huggingface'),local_files_only=True)
lengths=[];would_chunk=[]
special=t.num_special_tokens_to_add()
for d in docs:
    text=f"Judul: {d['track_name']}\nArtis: {d['track_artist']}\nLirik: {d.get('lyrics','')}"
    n=len(t.encode(text,add_special_tokens=False));lengths.append(n)
    if n+special>8192:would_chunk.append(d['track_id'])
write(E/'tokenization_audit.json',{'procedure':'Tokenize active full serialized documents with local tokenizer for pinned revision; no embedding recomputed',
   'model_name':c['model_name'],'revision':c['model_revision'],'documents':len(docs),'special_tokens_to_add':special,
   'content_tokens_min':min(lengths),'content_tokens_max':max(lengths),'would_chunk_over_8192_ids':would_chunk,'would_chunk_count':len(would_chunk),
   'historical_metadata_chunked_ids':json.loads((ROOT/'artifacts/semantic/metadata.json').read_text(encoding='utf-8'))['chunked_ids'],
   'inference_training':False})
print('tokenized',len(docs),'max tokens',max(lengths),'chunk count',len(would_chunk),flush=True)
