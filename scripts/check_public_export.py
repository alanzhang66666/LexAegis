"""Inspect staged source only; never print matched credential or case values."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN={'gateway-secret','gateway.env','accounts.json','registered-manifest.json','global-policy.json'}

def inspect_blob(name,raw,private_values=()):
    path=Path(name);issues=[]
    if path.name in FORBIDDEN or path.suffix in {'.env','.sqlite','.db','.gguf','.safetensors'}:
        issues.append('runtime or credential file')
    if any(part in {'.data','.venv','node_modules','test-results','playwright-report'} for part in path.parts):
        issues.append('runtime directory')
    if re.search(rb'\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,})',raw):
        issues.append('credential-shaped token')
    if any(value and value in raw for value in private_values):issues.append('private local value')
    return issues

def inspect_archive_literals(name,raw,amounts,dates):
    if '/archive/' not in name or not name.endswith('.py.txt'):return []
    try:tree=ast.parse(raw.decode('utf-8').split('\n\n',1)[1])
    except (ValueError,SyntaxError,IndexError):return ['unreadable archived Python source']
    for node in ast.walk(tree):
        if not isinstance(node,ast.Constant):continue
        value=node.value
        if isinstance(value,(int,float)) and str(value) in amounts:return ['private archival numeric fixture']
        if isinstance(value,str) and (value in amounts or value in dates):return ['private archival numeric fixture']
    return []

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-manifest',type=Path)
    parser.add_argument('--private-env',type=Path,action='append',default=[])
    parser.add_argument('--private-secret',type=Path,action='append',default=[])
    parser.add_argument('--base',help='Inspect committed changes since this revision instead of the index')
    args=parser.parse_args(argv);values=[];amounts=set();dates=set()
    if args.private_manifest:
        seed=json.loads(args.private_manifest.read_text(encoding='utf-8'))
        values.extend([seed['document_name'],seed['document_sha256']])
        values.extend(row[1] for row in seed['facts'] if row[0]=='entity' and len(row[1])>=3)
        for field,value in seed['facts']:
            if field=='amount':
                for token in re.findall(r'[0-9][0-9,]*(?:\.[0-9]+)?',value):
                    if len(token.replace(',',''))>=4:amounts.update([token,token.replace(',','')])
            elif field=='date':
                parts=re.findall(r'[0-9]+',value)
                if len(parts)==3:dates.add(parts[0]+'-'+parts[1].zfill(2)+'-'+parts[2].zfill(2))
    if args.private_env:
        from dotenv import dotenv_values
        for file in args.private_env:
            values.extend(v for k,v in dotenv_values(file,interpolate=False).items() if v and ('KEY' in k or 'SECRET' in k))
    values.extend(p.read_text(encoding='utf-8').strip() for p in args.private_secret)
    homes={str(Path.home()),str(Path.home()).replace('\\','/'),str(Path.home()).replace('\\','\\\\')}
    values.extend(homes)
    encoded=[v.encode('utf-8') for v in values if len(v)>=8]
    # Short entity names still matter; do not impose the credential length on them.
    if args.private_manifest:encoded.extend(row[1].encode() for row in seed['facts'] if row[0]=='entity' and len(row[1])>=3)
    selection=['git','diff','--name-only','--diff-filter=ACMR','-z']
    selection.extend([args.base,'HEAD'] if args.base else ['--cached'])
    names=subprocess.check_output(selection,cwd=ROOT).decode().split('\0')
    failures=[];count=0
    for name in filter(None,names):
        raw=subprocess.check_output(['git','show',('HEAD:' if args.base else ':')+name],cwd=ROOT);count+=1
        issues=inspect_blob(name,raw,encoded)
        issues.extend(inspect_archive_literals(name,raw,amounts,dates))
        if issues:failures.append({'file':name,'issues':issues})
    print(json.dumps({'staged_files_checked':count,'passed':not failures,'problems':failures},ensure_ascii=False))
    return 1 if failures else 0

if __name__=='__main__':raise SystemExit(main())
