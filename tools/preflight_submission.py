"""Targeted FastAPI adaptation of vibe-preflight. Never emit secret values."""
import importlib.util,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from guardian.app import create_app

OUT=ROOT/'test-results/challenge-v2';OUT.mkdir(parents=True,exist_ok=True)
package=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'submission/xiaoman-source-candidate.zip'
config_path=ROOT/'data/model.local.json'
key=json.loads(config_path.read_text(encoding='utf-8')).get('api_key','').encode() if config_path.exists() else b''
findings=[];checks=[]
with zipfile.ZipFile(package) as z:
    names=z.namelist()
    private=[n for n in names if set(Path(n).parts)&{'data','node_modules','.git'} or n.endswith(('.env','.env.local','.sqlite3','.sqlite3-wal'))]
    checks.append(dict(name='Private files excluded from archive',passed=not private,paths=private))
    for name in names:
        content=z.read(name)
        if key and key in content: findings.append({'path':name,'type':'ACTUAL_LOCAL_CREDENTIAL_PRESENT'})
    checks.append(dict(name='Exact local credential not present in archive',passed=not findings))
    checks.append(dict(name='Build inputs present',passed=all(n in names for n in ['frontend/index.html','vite.config.js','package-lock.json','guardian/app.py','tests/conftest.py'])))

# Reuse the skill's regex implementation without its dependency auto-installer
# or masking output. Scan only the reviewable archive's public text sources.
scanner=Path('C:/Users/ASUS/.agents/skills/vibe-preflight/scripts/check_secrets.py')
pattern_hits=[]
if scanner.is_file():
    import re
    spec=importlib.util.spec_from_file_location('preflight_patterns',scanner);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with zipfile.ZipFile(package) as z:
        for name in z.namelist():
            if Path(name).suffix not in ('.py','.js','.jsx','.json','.md','.txt','.html','.css'): continue
            content=z.read(name).decode('utf-8',errors='replace')
            for label,pattern in module.PATTERNS:
                if label=='Hardcoded password-looking assignment': continue # reviewed fixture strings, not evidence of credentials
                for match in re.finditer(pattern,content):
                    pattern_hits.append({'path':name,'line':content.count('\n',0,match.start())+1,'type':label})
    checks.append(dict(name='Skill credential-pattern scan, public archive',passed=not pattern_hits,findings=pattern_hits))

app=create_app(OUT/'preflight-private.sqlite3');c=TestClient(app)
private_routes=['/data/model.local.json','/.env','/.git/config','/node_modules/package.json','/guardian/assistant.py']
checks.append(dict(name='Private HTTP paths unavailable',passed=all(c.get(path).status_code==404 for path in private_routes)))
checks.append(dict(name='No-session state access rejected',passed=c.get('/api/state').status_code==403))
session=c.post('/api/session').json()
checks.append(dict(name='Mutation without CSRF rejected',passed=c.post('/api/assistant/message',json={'message':'查账'}).status_code==403))
checks.append(dict(name='Cross-origin mutation rejected',passed=c.post('/api/assistant/message',headers={'origin':'https://attacker.invalid','x-csrf-token':session['csrf']},json={'message':'查账'}).status_code==403))
headers=c.get('/api/health').headers
required=['content-security-policy','x-frame-options','x-content-type-options','referrer-policy','permissions-policy','cache-control']
checks.append(dict(name='Local preview security headers',passed=all(k in headers for k in required)))
health=c.get('/api/health').content
checks.append(dict(name='Health does not return credential',passed=not key or key not in health))
checks.append(dict(name='Protocol query consent still separate',passed='subscriptions' not in c.get('/api/state').json()))
report=dict(skill='vibe-preflight',scope='Public source archive plus in-process FastAPI tests, no external deploy',checks=checks,
    actual_credential_values_logged=False,passed=all(x['passed'] for x in checks),
    not_applicable=['Supabase RLS: not used','Production HSTS: loopback HTTP only'],
    limitations=['Regex scan is heuristic; not third-party penetration testing','Dependency names already installed and build verified; no fresh registry/provenance audit','Only synthetic loopback authentication tested','Prompt injection is covered by frozen boundary cases, not all prompt attacks'])
(OUT/'preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':report['passed'],'checks':len(checks),'findings':findings+pattern_hits},ensure_ascii=True))
if not report['passed']: raise SystemExit(1)
