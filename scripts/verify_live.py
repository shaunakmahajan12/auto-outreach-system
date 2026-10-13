"""Read-only provider checks. Emits counts/status only; never writes the application ledger."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from backend.research import Ollama, Serper
from backend.security import Keychain, DeploymentSecrets, AwsSecrets, Unavailable, Retryable
from backend.tsenta import Tsenta


def credentials():
    if os.getenv('AWS_CREDENTIAL_SECRET_ID'):return AwsSecrets(os.environ['AWS_CREDENTIAL_SECRET_ID'])
    return DeploymentSecrets() if os.getenv('CREDENTIAL_STORE')=='deployment' else Keychain()


async def verify(selected,vault=None):
    results={}
    for name in selected:
        try:
            if name=='ollama':
                result=await Ollama().health()
                if not result['available']:raise Unavailable(result['message'])
                results[name]={'passed':True,'model':result['model']}
            elif name=='tsenta':
                rows=await Tsenta(vault).snapshot()
                results[name]={'passed':True,'validated_application_count':len(rows),
                               'scope':'complete read-only history; no ledger sync or import'}
            elif name=='serper':
                rows=await Serper(vault).results('site:example.com "Example Domain"')
                results[name]={'passed':True,'result_count':len(rows),'scope':'one public test query'}
        except (Unavailable,Retryable) as error:
            results[name]={'passed':False,'error':str(error)}
        except Exception as error:
            results[name]={'passed':False,'error_type':type(error).__name__}
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'providers':results,
            'limitations':['Existing credentials only; no OAuth registration, reconnect or remote callback verification.',
                           'Normal Tsenta token refresh may update the configured credential store.',
                           'Serper check consumes one search request; no contact research or outreach is queued.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',action='append',choices=['tsenta','serper','ollama'],required=True)
    args=parser.parse_args()
    load_dotenv(ROOT/'.env')
    selected=list(dict.fromkeys(args.provider))
    vault=credentials() if any(name!='ollama' for name in selected) else None
    result=asyncio.run(verify(selected,vault))
    print(json.dumps(result,indent=2))
    if not all(row['passed'] for row in result['providers'].values()):raise SystemExit(1)


if __name__=='__main__':main()
