"""Synthetic-only Docker test double; never included in the deployment image."""
import json
from http.server import BaseHTTPRequestHandler,HTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,value):
        raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(200)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/v1/models':self.reply({'data':[{'id':'edge-small'}]})
        else:self.reply({'status':'ready','hostname':'synthetic-placeholder.trycloudflare.com'})
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        blocks=[]
        for message in body.get('messages',[]):
            try:value=json.loads(message.get('content',''))
            except ValueError:continue
            if isinstance(value,list):blocks=value;break
        selected=next((b for b in blocks if '1,200元' in b.get('text','')),None)
        result={'facts':[{'field':'amount','value':'1,200元','source_ids':[selected['id']],
            'quote':'1,200元','suggested_transform':'generalize'}]} if selected else {
            'decision':'allow_human_review','reason':'Synthetic test double only','risk_codes':[],'evidence_fact_ids':[]}
        self.reply({'id':'synthetic-stub','model':'edge-small','choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})

if __name__=='__main__':HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
