"""Build a current review packet with an allowlist. It never publishes code."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
OUT=ROOT/'submission';OUT.mkdir(exist_ok=True)
packet=OUT/'xiaoman-current-candidate-2026-10-20.zip'
allowed=[]
for name in ('README.md','SECURITY.md','requirements.txt','requirements-dev.txt','package.json','package-lock.json','vite.config.js','frontend/index.html','run.py','model.local.example.json','.gitignore'):
    path=ROOT/name
    if path.is_file():allowed.append(path)
for folder,patterns in [('guardian',['*.py']),('frontend/src',['*.js','*.jsx','*.css']),('tests',['*.py']),('tools',['*.py','*.js','*.cjs'])]:
    for pattern in patterns:allowed.extend((ROOT/folder).rglob(pattern))
for name in ('作品简介.txt','技术说明.md','安全自评.md','提交检查.md','答辩逐页稿.md','现场问答.md','Claude审查处理与T1-T10实测.md','用户要求总验收清单.md'):
    path=OUT/name
    if path.is_file():allowed.append(path)
for name in ('final-regression.xml','live-results.json','ui-smoke.json','jev-shadow.json','first-regression.xml'):
    path=ROOT/'test-results/completion-round'/name
    if path.is_file():allowed.append(path)
names=[]
with zipfile.ZipFile(packet,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(allowed)):
        relative=path.relative_to(ROOT).as_posix()
        if any(part in {'data','node_modules','.git','__pycache__'} for part in path.relative_to(ROOT).parts):raise ValueError(relative)
        if path.suffix in {'.sqlite3','.pyc'} or path.name.startswith('.env'):raise ValueError(relative)
        archive.write(path,relative);names.append(relative)
manifest={'archive':packet.name,'files':len(names),'sha256':hashlib.sha256(packet.read_bytes()).hexdigest(),
    'contains_private_runtime_data':False,'contains_real_bank_data':False,
    'evidence_scope':'Local synthetic bank; author-visible checks; no blind user study or official submission.'}
(OUT/'CURRENT_PACKET_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
