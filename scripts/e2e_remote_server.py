"""Real HTTPS/session browser test server with an ephemeral fictional workspace."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.auth import hash_password
import uvicorn

with tempfile.TemporaryDirectory(prefix='outreach-fictional-https-') as directory:
    root = Path(directory)
    cert = root / 'test.crt'
    key = root / 'test.key'
    subprocess.run(
        [
            'openssl',
            'req',
            '-x509',
            '-newkey',
            'rsa:2048',
            '-nodes',
            '-keyout',
            str(key),
            '-out',
            str(cert),
            '-days',
            '1',
            '-subj',
            '/CN=127.0.0.1',
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ.update(
        OUTREACH_DEMO='true',
        OUTREACH_DB=str(root / 'fictional.sqlite'),
        OUTREACH_REMOTE='true',
        OUTREACH_AUTO_ROLE_EXTRACTION='false',
        OUTREACH_AUTO_RESEARCH='false',
        TSENTA_POLL_ENABLED='false',
        EXTERNAL_BASE_URL='https://127.0.0.1:8766',
        ALLOWED_HOSTS='127.0.0.1:8766',
        ALLOWED_ORIGINS='https://127.0.0.1:8766',
        SESSION_SECRET='fictional-browser-test-secret-32-characters',
        OUTREACH_USERS=json.dumps(
            {
                'fictional': {
                    'role': 'operator',
                    'password_hash': hash_password('fictional-test-password'),
                }
            }
        ),
    )
    from backend.main import create_app

    uvicorn.run(
        create_app(start_worker=False),
        host='127.0.0.1',
        port=8766,
        ssl_keyfile=str(key),
        ssl_certfile=str(cert),
        access_log=False,
        log_level='warning',
    )
