"""Unpack the exact candidate and verify imports/tests without source checkout."""
import hashlib,json,re,subprocess,sys,tempfile,zipfile,os
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
package=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'submission/xiaoman-source-candidate.zip'
destination=Path(tempfile.mkdtemp(prefix='rehearsal-',dir=str(ROOT/'submission/build')))
with zipfile.ZipFile(package) as z:
    for name in z.namelist():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
    z.extractall(destination)
env=os.environ.copy()
for k in ('GUARDIAN_LLM_BASE_URL','GUARDIAN_LLM_MODEL','GUARDIAN_LLM_API_KEY'): env.pop(k,None)
test=subprocess.run([sys.executable,'-m','pytest','-q','tests'],cwd=str(destination),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
summary=next((line for line in reversed(test.stdout.splitlines()) if re.search(r'\d+ passed',line)),None)
code="from fastapi.testclient import TestClient; from guardian.app import create_app; c=TestClient(create_app('data/rehearsal.sqlite3')); assert c.get('/').status_code==200; c.post('/api/session'); assert c.get('/api/state').status_code==200; assert c.get('/data/model.local.json').status_code==404; print('Standalone app and static bundle OK')"
app=subprocess.run([sys.executable,'-c',code],cwd=str(destination),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
report=dict(source_zip_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),extraction_dir=str(destination),
    independent_checkout=True,fresh_dependency_install=False,shared_python_environment=sys.executable,
    tests_exit_code=test.returncode,tests_summary=summary,app_exit_code=app.returncode,passed=test.returncode==0 and app.returncode==0,
    limitations=['Existing verified Python dependencies reused','No clean-machine dependency installation or production deploy'])
out=ROOT/'test-results/completion-round/package-rehearsal.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if not report['passed']:
    (ROOT/'test-results/completion-round/package-rehearsal-failure.txt').write_text(test.stdout+'\n'+app.stdout,encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
if not report['passed']: raise SystemExit(1)
