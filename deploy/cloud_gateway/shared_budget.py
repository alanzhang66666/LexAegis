"""Atomic cross-gateway paid POST reservations. No payload or key is persisted."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
import zlib

import httpx

class Budget:
    def __init__(self,path,*,initial=0,limit=0):
        if type(initial) is not int or type(limit) is not int or initial<0 or limit<initial:
            raise ValueError('Invalid explicitly configured global allowance')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), initial INTEGER NOT NULL, ceiling INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, at REAL NOT NULL, body_sha256 TEXT NOT NULL, model TEXT, http_status INTEGER, response_model TEXT, usage TEXT, outcome TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO policy VALUES (1,?,?)',(initial,limit))
            actual=db.execute('SELECT initial,ceiling FROM policy WHERE id=1').fetchone()
            if actual!=(initial,limit):raise ValueError('Global allowance is immutable')
        os.chmod(self.path,0o600)
    def connection(self):
        db=sqlite3.connect(self.path,timeout=15,isolation_level='IMMEDIATE');db.execute('PRAGMA busy_timeout=15000');return db
    def status(self):
        with self.connection() as db:
            initial,ceiling=db.execute('SELECT initial,ceiling FROM policy WHERE id=1').fetchone()
            used=initial+db.execute('SELECT count(*) FROM attempts').fetchone()[0]
        return {'limit':ceiling,'reserved':used,'remaining':max(0,ceiling-used)}
    def reserve(self,body,model):
        ident='paid-post-'+uuid.uuid4().hex
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            initial,limit=db.execute('SELECT initial,ceiling FROM policy WHERE id=1').fetchone()
            if initial+db.execute('SELECT count(*) FROM attempts').fetchone()[0]>=limit:
                raise RuntimeError('User-authorized global cloud quota exhausted')
            db.execute('INSERT INTO attempts(id,at,body_sha256,model,outcome) VALUES (?,?,?,?,?)',
                (ident,time.time(),hashlib.sha256(body).hexdigest(),model,'reserved_before_external_post'))
        return ident
    def update(self,ident,**fields):
        fields={k:v for k,v in fields.items() if k in {'http_status','response_model','usage','outcome'}}
        if not fields:return
        with self.connection() as db:
            db.execute('UPDATE attempts SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),ident))

class MetadataStream(httpx.SyncByteStream):
    def __init__(self,stream,budget,ident,encoding=''):
        self.stream,self.budget,self.ident=stream,budget,ident;self.buffer=b''
        self.decoder=zlib.decompressobj(16+zlib.MAX_WBITS) if encoding.lower()=='gzip' else zlib.decompressobj() if encoding.lower()=='deflate' else None
    def process(self,line):
        if line.startswith(b'data:'):line=line[5:].strip()
        try:value=json.loads(line)
        except (ValueError,UnicodeError):return
        if not isinstance(value,dict):return
        fields={}
        if isinstance(value.get('model'),str) and re.fullmatch(r'[A-Za-z0-9_.:\-]{1,120}',value['model']):fields['response_model']=value['model']
        usage=value.get('usage')
        if isinstance(usage,dict):fields['usage']=json.dumps({k:v for k,v in usage.items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and 0<=v<10**9})
        self.budget.update(self.ident,**fields)
    def __iter__(self):
        try:
            for chunk in self.stream:
                decoded=self.decoder.decompress(chunk) if self.decoder else chunk
                self.buffer+=decoded
                while b'\n' in self.buffer:
                    line,self.buffer=self.buffer.split(b'\n',1);self.process(line.strip())
                if len(self.buffer)>65536:self.buffer=b''
                yield chunk
            self.process(self.buffer.strip());self.budget.update(self.ident,outcome='response_stream_ended')
        except Exception:
            self.budget.update(self.ident,outcome='unknown_stream_interrupted');raise
    def close(self):self.stream.close()

class BudgetClient(httpx.Client):
    def __init__(self,*args,budget,**kwargs):self.budget=budget;super().__init__(*args,**kwargs)
    def send(self,request,*,stream=False,**kwargs):
        paid=request.method=='POST' and request.url.host=='api.deepseek.com' and request.url.path.endswith('/chat/completions')
        if not paid:return super().send(request,stream=stream,**kwargs)
        body=request.read()
        try:model=json.loads(body).get('model')
        except ValueError:model=None
        ident=self.budget.reserve(body,model)
        try:
            response=super().send(request,stream=True,**kwargs)
            self.budget.update(ident,http_status=response.status_code,outcome='response_headers_received')
            if response.is_stream_consumed:
                for _ in MetadataStream(httpx.ByteStream(response.content),self.budget,ident):pass
            else:
                response.stream=MetadataStream(response.stream,self.budget,ident,response.headers.get('content-encoding',''))
            if not stream:response.read()
            return response
        except Exception:
            self.budget.update(ident,outcome='unknown_no_automatic_retry');raise
