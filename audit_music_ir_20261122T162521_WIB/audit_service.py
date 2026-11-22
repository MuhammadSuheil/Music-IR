import subprocess, sys, time, os
from audit_collect import ROOT,E,write
kind=sys.argv[1]
args=([sys.executable,'-m','uvicorn','music_ir.api:app','--host','127.0.0.1','--port','8000'] if kind=='api' else [sys.executable,str(ROOT/'audit_music_ir_20261122T162521_WIB/audit_live_api.py')] if kind=='api_observed' else ['npm.cmd','run','dev'])
cwd=ROOT if kind.startswith('api') else ROOT/'frontend'
with (E/(kind+'.stdout.log')).open('w',encoding='utf-8') as out, (E/(kind+'.stderr.log')).open('w',encoding='utf-8') as err:
    child=subprocess.Popen(args,cwd=cwd,stdout=out,stderr=err,env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=subprocess.CREATE_NO_WINDOW)
    write(E/(kind+'_service.json'),{'command':args,'cwd':str(cwd),'pid':child.pid,'started_epoch':time.time(),'backend_env':os.environ.get('MUSIC_IR_BACKEND'),'reload':False})
    print(kind,child.pid,flush=True)
    try: child.wait()
    except KeyboardInterrupt: child.terminate(); child.wait(timeout=20)
