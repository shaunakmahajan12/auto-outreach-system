"""Single-process localhost launcher with a process lock and no access logs."""
import fcntl
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import uvicorn

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    load_dotenv(root/'.env')
    os.umask(0o077)
    (root/'.local').mkdir(exist_ok=True,mode=0o700)
    name='demo' if os.getenv('OUTREACH_DEMO','false').lower()=='true' else 'app'
    lock=open(root/'.local'/f'{name}.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another app instance is already running. Use its dashboard.')
    uvicorn.run('backend.main:create_app',factory=True,host=os.getenv('BIND_HOST','127.0.0.1'),port=8765,workers=1,access_log=False,log_level='warning')
