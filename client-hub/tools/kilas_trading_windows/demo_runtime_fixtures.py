"""In-memory HTTP/server fixtures. No sockets, DNS, credentials or inference."""
import json
from datetime import timedelta
from io import BytesIO
from threading import Event
from test_demo_control_v2 import Port,stamp,NOW

class FakeServer(Port):
    def __init__(self,clock):
        super().__init__(clock)
        self.connections=[]; self.stop_requested=False; self.requests=[]; self.run_started=None
        self.status=200; self.headers={'Content-Type':'application/json'}
        self.stall=False; self.delay=0
    def post(self,path,body):
        self.calls.append((path,body.copy()))
        return self.response(body)
    def response(self,body):
        p=super().response(body)
        if body['sequence']>0:
            if self.run_started is None: self.run_started=p['received_at']
            p['run_started_at']=self.run_started
        ack=body.get('ack')
        if self.stop_requested:
            p.update(desired_state='OFF',effective_desired_state='OFF',revision=2,command_id='b'*32,
                issued_at=stamp(NOW),command_expires_at=stamp(NOW+timedelta(seconds=30)),
                run_seconds=0,run_expires_at=None,run_started_at=None,worker_lease_expires_at=None,
                run_status='ENDED',end_reason='OFF_REQUESTED')
        elif ack and ack['actual_state'] in ('OFF','PROTECTING'):
            p.update(effective_desired_state='OFF',run_status='ENDED',end_reason='UNSAFE_ACK')
        return p
    def factory(self,*args,**kwargs):
        c=FakeConnection(self); self.connections.append(c); return c

class FakeSocket:
    def __init__(self,c): self.c=c; self.timeouts=[]
    def settimeout(self,value): self.timeouts.append(value)
    def close(self): self.c.close()

class FakeConnection:
    def __init__(self,server):
        self.server=server; self.sock=FakeSocket(self); self.timeout=0
        self.closed=False; self.release=Event(); self.body=None
    def connect(self): pass
    def request(self,method,path,body,headers):
        if self.closed: raise RuntimeError('closed')
        parsed=json.loads(body)
        # Never retain auth value, even in test evidence.
        self.server.requests.append(dict(method=method,path=path,body=parsed,
            header_names=sorted(headers),bearer_header_present=headers.get('Authorization','').startswith('Bearer ')))
        self.body=parsed
    def getresponse(self):
        if self.server.stall: self.release.wait(1)
        if self.closed: raise RuntimeError('closed')
        data=json.dumps(self.server.post('/products/services/trading/control/sync',self.body)).encode()
        return FakeResponse(self.server,data,self)
    def close(self): self.closed=True; self.release.set()

class FakeResponse:
    def __init__(self,server,data,connection):
        self.server,self.stream,self.connection=server,BytesIO(data),connection
        self.status=server.status
    def getheader(self,name,default=None): return self.server.headers.get(name,default)
    def read(self,n):
        if self.server.delay:
            self.connection.release.wait(self.server.delay)
            if self.connection.closed: raise RuntimeError('closed')
            n=1
        return self.stream.read(n)
