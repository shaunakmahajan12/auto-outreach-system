"""Build and verify an isolated fictional container; never mounts the live workspace."""
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def main():
    if not shutil.which('docker'):
        raise SystemExit('Docker is required. Install/start Docker, then rerun this smoke check.')
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['docker', 'build', '-t', 'outreach-smoke:local', str(root)], check=True)
    container = docker('run', '--detach', '--rm', '--publish', '127.0.0.1::8765',
                       '--tmpfs', '/app/.local:uid=10001,gid=10001,mode=0700',
                       '--env', 'OUTREACH_DEMO=true', '--env', 'TSENTA_POLL_ENABLED=false',
                       '--env', 'OUTREACH_AUTO_ROLE_EXTRACTION=false', 'outreach-smoke:local')
    try:
        port = docker('port', container, '8765/tcp').rsplit(':', 1)[1]
        base = f'http://127.0.0.1:{port}'
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def request(path, token=None, post=False):
            # Docker chooses the host port; retain the app's allowed internal authority.
            headers = {'Host':'127.0.0.1:8765'}
            if token:headers['x-outreach-token']=token
            req = urllib.request.Request(base+path, headers=headers, data=b'' if post else None)
            with client.open(req, timeout=5) as response:
                return json.load(response)

        deadline = time.monotonic()+60
        while True:
            try:
                if request('/ready')['ready']:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Fictional container did not become ready within 60 seconds.')
            time.sleep(1)
        bootstrap = request('/api/bootstrap')
        assert bootstrap['demo'] is True
        token = bootstrap['token']
        initial = request('/api/state', token)
        assert initial['baseline_valid'] and not initial['contacts']
        assert request('/api/demo/transition', token, True)['eligible'] == 0
        assert request('/api/demo/transition', token, True)['eligible'] == 1
        deadline = time.monotonic()+60
        while True:
            state = request('/api/state', token)
            if state['contacts']:
                assert 'FICTIONAL DEMO' in state['contacts'][0]['note']
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Fictional container did not prepare a draft within 60 seconds.')
            time.sleep(1)
        print('PASS: container startup, readiness, baseline, submission and draft preparation.')
    finally:
        docker('stop', container)


if __name__ == '__main__':
    main()
