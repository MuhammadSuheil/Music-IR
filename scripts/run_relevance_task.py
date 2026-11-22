"""Run a relevance CLI task with complete logs; no shell interpolation."""
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

root = Path(__file__).resolve().parent.parent
command, directory = sys.argv[1], Path(sys.argv[2]).resolve()
if command not in {'pool', 'label', 'export', 'report'}:
    raise ValueError('Unsupported task')
args = [sys.executable, '-u', '-m', 'music_ir.relevance', command, '--run', str(directory), *sys.argv[3:]]
started = datetime.now(timezone.utc).isoformat(); timer = time.perf_counter()
with (directory / (command+'.stdout.log')).open('wb') as out, (directory / (command+'.stderr.log')).open('wb') as err:
    result = subprocess.run(args, cwd=root, stdout=out, stderr=err)
record = {'command':args, 'started_utc':started, 'ended_utc':datetime.now(timezone.utc).isoformat(),
          'duration_seconds':time.perf_counter()-timer,'exit_code':result.returncode}
(directory / (command+'_execution.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record),flush=True)
sys.exit(result.returncode)
