import sys, json, urllib.request, urllib.error, time
from audit_collect import ROOT, OUT, E, run, write

if sys.argv[1]=='tests':
    r=run([sys.executable,'-m','unittest','discover','-s','tests','-v'],'backend_tests',timeout=900)
    print(r['stderr'][-2400:],flush=True)
elif sys.argv[1]=='build':
    r=run(['npm.cmd','run','build'],'frontend_build',cwd=ROOT/'frontend')
    print(r['stdout'][-1800:],r['stderr'][-1000:],flush=True)
elif sys.argv[1]=='ui-tests':
    r=run(['npm.cmd','test','--','--output='+str(E/'playwright_results')],'frontend_tests',cwd=ROOT/'frontend',timeout=600)
    print(r['stdout'][-4000:],r['stderr'][-2000:],flush=True)
elif sys.argv[1] in ['latency','annotation']:
    name=sys.argv[1]
    r=run([sys.executable,str(OUT/'audit_search.py'),name],name+'_execution',timeout=1800)
    print(r['stdout'][-5000:],r['stderr'][-2000:],flush=True)
elif sys.argv[1]=='data':
    from audit_collect import data_audit, benchmark_audit
    data_audit();benchmark_audit()
elif sys.argv[1]=='probe':
    results=[]
    for url in ['http://127.0.0.1:8000/health','http://127.0.0.1:8501/','http://127.0.0.1:9200/']:
        start=time.perf_counter()
        try:
            with urllib.request.urlopen(url,timeout=4) as f:
                body=f.read().decode('utf-8',errors='replace')
                results.append({'url':url,'status':f.status,'body':json.loads(body) if f.headers.get_content_type()=='application/json' else body[:4000],'seconds':time.perf_counter()-start})
        except Exception as exc: results.append({'url':url,'error':repr(exc),'seconds':time.perf_counter()-start})
    write(E/'service_probe.json',results);print(json.dumps(results,ensure_ascii=True),flush=True)
