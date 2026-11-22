"""Capture complete validation logs and confirm retrieval was not modified."""
import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

root=Path(__file__).resolve().parent.parent
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,str(root))
parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
parser.add_argument('--checks',default='backend,build,ui');args=parser.parse_args()
directory=args.run.resolve()/'validation';directory.mkdir(exist_ok=True)
jobs={'backend':([sys.executable,'-m','unittest','discover','-s','tests','-v'],root),
      'build':(['npm.cmd','run','build'],root/'frontend'),
      'ui':(['npm.cmd','test','--','--output='+str(directory/'playwright')],root/'frontend')}
records=[]
for name in args.checks.split(','):
    command,cwd=jobs[name];started=datetime.now(timezone.utc).isoformat();timer=time.perf_counter()
    result=subprocess.run(command,cwd=cwd,capture_output=True,encoding='utf-8',errors='replace',timeout=600)
    record={'command':command,'cwd':str(cwd),'started_utc':started,'duration_seconds':time.perf_counter()-timer,'exit_code':result.returncode,
            'stdout':result.stdout,'stderr':result.stderr}
    (directory/(name+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');records.append(record)
    print(name,result.returncode,result.stdout[-1000:],result.stderr[-1000:],flush=True)
baseline=root/'audit_music_ir_20261122T162521_WIB/evidence/snapshot_before.json'
if baseline.exists():
    hashes=json.loads(baseline.read_text(encoding='utf-8'))['hashes']
    core=['music_ir/'+name+'.py' for name in ['engine','data','audio','query','lexical','semantic','lyrics','metadata','mood','passages','evaluate']]
    core+=['config.json','data/processed/corpus.json','evaluation/queries.draft.jsonl']
    comparison=[{'path':rel,'unchanged':hashlib.sha256((root/rel).read_bytes()).hexdigest()==hashes[rel]['sha256']} for rel in core]
    def function(path,name):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        return ast.dump(next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)) and n.name==name))
    old=root/'audit_music_ir_20261122T162521_WIB/evidence/source/music_ir/api.py'
    api_check={name:function(old,name)==function(root/'music_ir/api.py',name) for name in ['SearchRequest','search','lifespan']}
    proof={'baseline':str(baseline),'core_files':comparison,'original_search_api_ast_unchanged':api_check,
           'retrieval_preserved':all(r['unchanged'] for r in comparison) and all(api_check.values())}
    (directory/'retrieval_unchanged.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    if not proof['retrieval_preserved']:raise RuntimeError('Protected retrieval changed')
if any(r['exit_code']!=0 for r in records):raise SystemExit(1)
