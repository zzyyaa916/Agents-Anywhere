#!/usr/bin/python3 -I
"""Fixed-user Fork native launcher. No root shell and no SSH key transfer."""
import array,base64,ctypes,json,os,pwd,select,signal,socket,stat,struct,subprocess,sys,syslog,threading,time,uuid
from pathlib import Path
CONFIG=Path('/etc/ai-ops/fork-runtime.json')
SOCKET=Path('/run/aa-fork-runtime/launch.sock')
JOBS=Path('/run/aa-fork-runtime/jobs')
LIMIT=128*1024
ROLES=('codex','claude','dsh')

def validate_request(value,peer_uid,allowed_uid):
 if peer_uid!=allowed_uid:raise PermissionError('Only the trusted Fork Connector can launch runtimes')
 if not isinstance(value,dict) or value.get('role') not in ROLES:raise ValueError('Unknown fixed runtime')
 args=value.get('args')
 if not isinstance(args,list) or len(args)>2048 or not all(isinstance(x,str) and '\0' not in x for x in args):raise ValueError('Invalid runtime arguments')
 env=value.get('environment',{})
 if not isinstance(env,dict) or not all(isinstance(k,str) and isinstance(v,str) and '\0' not in k+v and '=' not in k for k,v in env.items()):raise ValueError('Invalid environment')
 return value

def safe_environment(inherited,role,account,settings):
 env={k:v for k,v in inherited.items() if k in ('LANG','LC_ALL','TERM','COLORTERM','TZ','HTTP_PROXY','HTTPS_PROXY','NO_PROXY') or k.startswith(('OPENAI_','ANTHROPIC_','CLAUDE_','CODEX_','DSH_'))}
 for k in ('CODEX_HOME','CODEX_SQLITE_HOME','CLAUDE_CONFIG_DIR','CLAUDE_SECURESTORAGE_CONFIG_DIR','DSH_HOME','DSH_STATE_DIR','CODEX_EXEC_SERVER_PATH','CODEX_CODE_MODE_HOST_PATH'):
  env.pop(k,None)
 env.update(HOME=account.pw_dir,USER=account.pw_name,LOGNAME=account.pw_name,SHELL='/bin/bash',PATH='/usr/local/bin:/usr/bin:/bin',TMPDIR=str(Path(account.pw_dir)/'tmp'),AI_OPS_IDENTITY=role)
 env.update(settings['environment'])
 return env

def child(job):
 if os.getuid()!=0 or job.parent!=JOBS:raise PermissionError('Trusted root job required')
 fd=os.open(job,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd) as f:
  s=os.fstat(f.fileno())
  if s.st_uid!=0 or s.st_mode & 0o077 or s.st_nlink!=1:raise PermissionError('Untrusted job')
  value=json.load(f)
 job.unlink()
 cfg=json.loads(CONFIG.read_text());role=value['role'];settings=cfg['roles'][role];account=pwd.getpwnam(settings['account'])
 env=safe_environment(value.get('environment',{}),role,account,settings)
 os.initgroups(account.pw_name,account.pw_gid);os.setgid(account.pw_gid);os.setuid(account.pw_uid);os.umask(0o077)
 if ctypes.CDLL(None,use_errno=True).prctl(38,1,0,0,0)!=0:raise RuntimeError('Cannot set no_new_privs')
 cwd=value.get('cwd') or account.pw_dir
 try:os.chdir(cwd)
 except OSError:os.chdir(account.pw_dir)
 args=value['args']
 if args[:1]==['--aa-usage-probe']:
  import hashlib
  pin=cfg.get('claudeUsageProbe',{})
  node=hashlib.sha256(Path('/etc/machine-id').read_bytes().strip()).hexdigest()
  if role!='claude' or len(args)!=2 or not pin.get('enabled') or args[1]!=pin.get('connectorId') or node!=pin.get('machineId'):
   raise PermissionError('Usage probe not enabled on this node')
  helper=Path('/opt/agents-anywhere-fork-connector/bin/claude-usage-probe.py')
  meta=helper.stat()
  if meta.st_uid!=0 or meta.st_mode & 0o022 or helper.is_symlink():raise PermissionError('Untrusted usage helper')
  os.execve('/usr/bin/python3',['python3','-I',str(helper),settings['binary'],*settings.get('prefix_args',[])],env)
 if args[:1]==['--aa-history-delete']:
  if role!='claude' or len(args)!=3 or args[1] not in ('prepare','commit'):raise ValueError('Invalid native history cleanup')
  from uuid import UUID
  if str(UUID(args[2]))!=args[2]:raise ValueError('Invalid native history identity')
  helper=Path('/opt/agents-anywhere-fork-connector/bin/native-history-cleanup.py')
  meta=helper.stat()
  if meta.st_uid!=0 or meta.st_mode & 0o022 or helper.is_symlink():raise PermissionError('Untrusted cleanup helper')
  os.execve('/usr/bin/python3',['python3','-I',str(helper),args[1],args[2]],env)
 if args==['--ai-identity-check']:
  r=subprocess.run(['/usr/local/bin/ai-ssh','--identity'],capture_output=True,text=True,check=True)
  print(json.dumps({'uid':os.getuid(),'account':account.pw_name,'ssh_identity':r.stdout.strip(),'no_new_privs':True}));return
 for index,encoded in value.get('settings_files',{}).items():
  i=int(index)
  if role!='claude' or i<=0 or i>=len(args) or args[i-1]!='--settings':raise ValueError('Unexpected settings argument')
  import tempfile
  fd,name=tempfile.mkstemp(prefix='fork-claude-',suffix='.json',dir=env['TMPDIR'])
  with os.fdopen(fd,'wb') as f:f.write(base64.b64decode(encoded,validate=True))
  args[i]=name
 os.execve(settings['binary'],[settings['binary'],*settings.get('prefix_args',[]),*args],env)

def handle(conn,cfg):
 fds=[];proc=None;job=None
 try:
  pid,uid,gid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
  packet,anc,flags,_=conn.recvmsg(LIMIT+1,socket.CMSG_SPACE(16*array.array('i').itemsize))
  for level,kind,data in anc:
   if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
    a=array.array('i');a.frombytes(data[:len(data)//a.itemsize*a.itemsize]);fds.extend(a)
  if flags & (socket.MSG_TRUNC|socket.MSG_CTRUNC) or len(packet)>LIMIT or len(fds)!=3:raise ValueError('Invalid launch packet')
  value=validate_request(json.loads(packet),uid,pwd.getpwnam(cfg['connector_account']).pw_uid)
  job=JOBS/(str(uuid.uuid4())+'.json')
  fd=os.open(job,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as f:json.dump(value,f)
  proc=subprocess.Popen(['/usr/bin/python3','-I',str(Path(__file__).resolve()),'child',str(job)],stdin=fds[0],stdout=fds[1],stderr=fds[2],start_new_session=True)
  syslog.syslog(json.dumps({'event':'fork_runtime_start','role':value['role'],'account':cfg['roles'][value['role']]['account'],'caller_uid':uid,'caller_pid':pid,'pid':proc.pid}))
  while proc.poll() is None:
   if not select.select([conn],[],[],.2)[0]:continue
   data=conn.recv(256)
   if not data:os.killpg(proc.pid,signal.SIGTERM);break
   message=json.loads(data)
   if message.get('signal') in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):os.killpg(proc.pid,message['signal'])
  code=proc.wait(timeout=30)
  conn.send(json.dumps({'exit_code':code}).encode())
  syslog.syslog(json.dumps({'event':'fork_runtime_end','role':value['role'],'pid':proc.pid,'exit_code':code}))
 except Exception as error:
  if proc is not None and proc.poll() is None:
   try:os.killpg(proc.pid,signal.SIGTERM)
   except ProcessLookupError:pass
  try:conn.send(json.dumps({'error':type(error).__name__,'exit_code':126}).encode())
  except OSError:pass
 finally:
  if job is not None:job.unlink(missing_ok=True)
  for fd in fds:os.close(fd)
  conn.close()

def serve():
 if os.getuid()!=0:raise PermissionError('Root service only')
 cfg=json.loads(CONFIG.read_text());account=pwd.getpwnam(cfg['connector_account'])
 SOCKET.parent.mkdir(mode=0o750,parents=True,exist_ok=True);os.chown(SOCKET.parent,0,account.pw_gid);SOCKET.parent.chmod(0o750)
 JOBS.mkdir(mode=0o700,exist_ok=True);JOBS.chmod(0o700)
 if SOCKET.exists():SOCKET.unlink()
 sock=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);sock.bind(str(SOCKET));os.chown(SOCKET,0,account.pw_gid);SOCKET.chmod(0o660);sock.listen(32)
 syslog.openlog('aa-fork-runtime',syslog.LOG_PID,syslog.LOG_AUTHPRIV)
 while True:
  conn,_=sock.accept();threading.Thread(target=handle,args=(conn,cfg),daemon=True).start()

def client(role,args):
 value={'role':role,'args':args,'environment':dict(os.environ),'cwd':os.getcwd(),'settings_files':{}}
 if role=='claude':
  for i,arg in enumerate(args[1:],1):
   if args[i-1]!='--settings':continue
   p=Path(arg)
   try:
    s=p.stat()
    if s.st_uid==os.getuid() and stat.S_ISREG(s.st_mode) and s.st_size<32768:value['settings_files'][str(i)]=base64.b64encode(p.read_bytes()).decode()
   except OSError:pass
 packet=json.dumps(value).encode()
 if len(packet)>LIMIT:raise ValueError('Launch environment too large')
 sock=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);sock.connect(str(SOCKET));sock.sendmsg([packet],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[0,1,2]))])
 def forward(signum,_):
  try:sock.send(json.dumps({'signal':signum}).encode())
  except OSError:pass
 for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,forward)
 result=json.loads(sock.recv(2048));sock.close()
 if result.get('error'):print('Fork runtime launcher: '+result['error'],file=sys.stderr)
 code=result.get('exit_code',126);return code if code>=0 else 128-code

if __name__=='__main__':
 if sys.argv[1:2]==['serve']:serve()
 elif sys.argv[1:2]==['child']:child(Path(sys.argv[2]))
 elif len(sys.argv)>1 and sys.argv[1] in ROLES:raise SystemExit(client(sys.argv[1],sys.argv[2:]))
 else:raise SystemExit('Use the configured fixed runtime entry')
