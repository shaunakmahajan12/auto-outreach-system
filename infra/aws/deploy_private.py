"""Deploy the private, single-host workspace. No credentials enter release archives."""
import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/aws-deployment'
LOCAL.mkdir(parents=True, exist_ok=True)
PROFILE = 'outreach'
STACK = 'outreach-private'
# Pinned for reproducible deploys; update deliberately after checking the release.
OLLAMA_IMAGE = 'ollama/ollama:0.34.1@sha256:0c0a83210471fb50226bcdc2d6611d20ab13ae87e024cc304c94a6a5765c5e65'

@functools.cache
def region():
    # The project's assigned Region, as configured for the deployment profile.
    r = subprocess.run(['aws', 'configure', 'get', 'region', '--profile', PROFILE], text=True, capture_output=True)
    if r.returncode or not r.stdout.strip():
        raise SystemExit(f'Set the Region for the {PROFILE} profile: aws configure set region <Region> --profile {PROFILE}')
    return r.stdout.strip()

def aws(*args, raw=False, data=None):
    r = subprocess.run(['aws', *args, '--profile', PROFILE, '--region', region(),
                        '--output', 'json'], input=data, text=True, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout if raw else (json.loads(r.stdout) if r.stdout.strip() else {})

def provision(create=True):
    plan = aws('freetier', 'get-account-plan-state')
    assert plan['accountPlanType'] == 'FREE', 'Free Plan required; will not upgrade'
    assert plan['accountPlanRemainingCredits']['amount'] > 10, 'Insufficient credits'
    ami = aws('ssm', 'get-parameter', '--name', '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64')['Parameter']['Value']
    vpc = aws('ec2', 'describe-vpcs', '--filters', 'Name=is-default,Values=true')['Vpcs'][0]['VpcId']
    subnet = aws('ec2', 'describe-subnets', '--filters', f'Name=vpc-id,Values={vpc}')['Subnets'][0]['SubnetId']
    resources = {
      'Releases': {'Type':'AWS::S3::Bucket','DeletionPolicy':'Delete','UpdateReplacePolicy':'Delete','Properties':{
        'PublicAccessBlockConfiguration':dict.fromkeys(['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets'],True),
        'BucketEncryption':{'ServerSideEncryptionConfiguration':[{'ServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]},
        'VersioningConfiguration':{'Status':'Enabled'},
        'LifecycleConfiguration':{'Rules':[{'Id':'ExpireReleases','Status':'Enabled','ExpirationInDays':30,
          # Versioned expiry only adds delete markers; also remove the superseded private copies.
          'NoncurrentVersionExpiration':{'NoncurrentDays':1},'AbortIncompleteMultipartUpload':{'DaysAfterInitiation':1}}]}}},
      'Credentials': {'Type':'AWS::SecretsManager::Secret','Properties':{'Description':'Private outreach provider credentials','SecretString':'{}'}},
      'HostRole': {'Type':'AWS::IAM::Role','Properties':{
        'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'ec2.amazonaws.com'},'Action':'sts:AssumeRole'}]},
        'ManagedPolicyArns':['arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'],
        'Policies':[{'PolicyName':'OutreachResources','PolicyDocument':{'Version':'2012-10-17','Statement':[
          {'Effect':'Allow','Action':['s3:GetObject'],'Resource':{'Fn::Sub':'${Releases.Arn}/*'}},
          {'Effect':'Allow','Action':['secretsmanager:GetSecretValue','secretsmanager:PutSecretValue'],'Resource':{'Ref':'Credentials'}}]}}]}},
      'HostProfile':{'Type':'AWS::IAM::InstanceProfile','Properties':{'Roles':[{'Ref':'HostRole'}]}},
      'HostSecurityGroup':{'Type':'AWS::EC2::SecurityGroup','Properties':{'GroupDescription':'Private outreach: no inbound connections','VpcId':vpc,'SecurityGroupIngress':[]}},
      'Host':{'Type':'AWS::EC2::Instance','Properties':{
        'ImageId':ami,'InstanceType':'m7i-flex.large','IamInstanceProfile':{'Ref':'HostProfile'},
        'NetworkInterfaces':[{'DeviceIndex':'0','AssociatePublicIpAddress':True,'SubnetId':subnet,'GroupSet':[{'Ref':'HostSecurityGroup'}]}],
        'MetadataOptions':{'HttpTokens':'required','HttpPutResponseHopLimit':2},
        'BlockDeviceMappings':[{'DeviceName':'/dev/xvda','Ebs':{'VolumeSize':40,'VolumeType':'gp3','Encrypted':True,'DeleteOnTermination':False}}],
        'Tags':[{'Key':'Name','Value':'outreach-private'},{'Key':'Project','Value':'auto-outreach-system'}],
        'UserData':{'Fn::Base64':'#!/bin/bash\nset -euo pipefail\ndnf install -y docker\nsystemctl enable --now docker\nmkdir -p /srv/outreach/data /srv/outreach/models /srv/outreach/backups\nchmod 700 /srv/outreach/data /srv/outreach/backups\nchown 10001:10001 /srv/outreach/data\n'}}}
    }
    resources['ReleasePolicy']={'Type':'AWS::S3::BucketPolicy','Properties':{'Bucket':{'Ref':'Releases'},'PolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[{'Fn::GetAtt':['Releases','Arn']},{'Fn::Sub':'${Releases.Arn}/*'}],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}}}
    for name, resource in resources.items():
        resource['Metadata']={'com.aws.cloudformation.Context':{'why':'Temporary private deployment verification; original workspace remains local','must':['Keep application and model ports private; remove all cloud copies after verification']}}
    template={'AWSTemplateFormatVersion':'2010-09-09','Description':'Temporary outreach application deployment using one private-access host; remove after verification to conserve free credits.','Metadata':{'AWSToolsMetrics':{'AWSAgentToolkit':'aws-cloudformation@3'}},'Resources':resources,'Outputs':{
      'InstanceId':{'Value':{'Ref':'Host'}},'ReleaseBucket':{'Value':{'Ref':'Releases'}},'CredentialSecret':{'Value':{'Ref':'Credentials'}}}}
    path=LOCAL/'private-stack.json'
    path.write_text(json.dumps(template,indent=2)+'\n')
    print('Template bytes:',path.stat().st_size)
    if create:
        print(aws('cloudformation','validate-template','--template-body','file://'+str(path)))
        print(aws('cloudformation','create-stack','--stack-name',STACK,'--template-body','file://'+str(path),'--capabilities','CAPABILITY_IAM','--tags','Key=Project,Value=auto-outreach-system'))

def outputs():
    stack=aws('cloudformation','describe-stacks','--stack-name',STACK)['Stacks'][0]
    print('Stack status:',stack['StackStatus'])
    out={v['OutputKey']:v['OutputValue'] for v in stack.get('Outputs',[])}
    if out:
        (LOCAL/'outputs.json').write_text(json.dumps(out,indent=2)+'\n')
    return out

def release():
    out=outputs()
    assert out, 'Stack not ready'
    archive=LOCAL/'release.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name in ['Dockerfile','requirements.lock.txt','requirements-aws.txt','backend','scripts','migrations','alembic.ini','frontend']:
            def clean(info):
                parts=Path(info.name).parts
                if any(p in ('node_modules','dist','__pycache__','.local','.env','.git') for p in parts):return None
                return info
            tar.add(ROOT/name,arcname=name,filter=clean)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    key=f'releases/{digest}.tar.gz'
    aws('s3','cp',str(archive),f's3://{out["ReleaseBucket"]}/{key}',raw=True)
    # SQLite online backups produce consistent standalone copies, excluding transient WAL files.
    with tarfile.open(LOCAL/'workspace.tar.gz','w:gz') as tar:
        for name in ['outreach.sqlite','outreach.sqlite.checkpoints.sqlite']:
            source=ROOT/'.local'/name
            if not source.exists():continue
            target=LOCAL/name
            with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            os.chmod(target,0o600)
            tar.add(target,arcname=name)
    aws('s3','cp',str(LOCAL/'workspace.tar.gz'),f's3://{out["ReleaseBucket"]}/workspace.tar.gz',raw=True)
    # Secret material goes directly from the native Keychain to Secrets Manager via stdin.
    import sys
    sys.path.insert(0,str(ROOT))
    from backend.security import Keychain
    vault=Keychain()
    secrets={name:vault.get(name) for name in ('serper','tsenta')}
    aws('secretsmanager','put-secret-value','--secret-id',out['CredentialSecret'],
        '--secret-string','file:///dev/stdin',data=json.dumps(secrets))
    script=(ROOT/'infra/aws/install_host.sh').read_text()
    script=script.replace('__REGION__',region()).replace('__OLLAMA_IMAGE__',OLLAMA_IMAGE).replace('__BUCKET__',out['ReleaseBucket']).replace('__KEY__',key).replace('__SHA__',digest).replace('__SECRET__',out['CredentialSecret'])
    params=LOCAL/'install-parameters.json'
    params.write_text(json.dumps({'commands':[script],'executionTimeout':['3600']}))
    result=aws('ssm','send-command','--instance-ids',out['InstanceId'],'--document-name','AWS-RunShellScript','--parameters','file://'+str(params),'--timeout-seconds','3600')
    (LOCAL/'install-command.json').write_text(json.dumps(result,indent=2))
    print('Install command:',result['Command']['CommandId'])

def delete_versions(bucket, prefix=None):
    while True:
        versions=aws('s3api','list-object-versions','--bucket',bucket,*(['--prefix',prefix] if prefix else []))
        objects=[{'Key':v['Key'],'VersionId':v['VersionId']} for k in ['Versions','DeleteMarkers'] for v in versions.get(k,[])
                 if prefix is None or v['Key']==prefix]
        if not objects:break
        path=LOCAL/'delete-objects.json';path.write_text(json.dumps({'Objects':objects[:1000],'Quiet':True}))
        result=aws('s3api','delete-objects','--bucket',bucket,'--delete','file://'+str(path))
        assert not result.get('Errors'),result

def command_status():
    out=json.loads((LOCAL/'outputs.json').read_text())
    cmd=json.loads((LOCAL/'install-command.json').read_text())['Command']['CommandId']
    result=aws('ssm','get-command-invocation','--command-id',cmd,'--instance-id',out['InstanceId'])
    (LOCAL/'install-result.json').write_text(json.dumps(result,indent=2))
    print('Install status:',result['Status'])
    if result['Status']=='Success':
        # The host holds the restored workspace now; keep no private ledger copy in S3.
        delete_versions(out['ReleaseBucket'],'workspace.tar.gz')
        print('Removed the uploaded workspace copy from the release bucket.')
    print(result.get('StandardOutputContent','')[-2500:])
    print(result.get('StandardErrorContent','')[-1500:])

def verify():
    out=json.loads((LOCAL/'outputs.json').read_text())
    commands=['set -eu',
      'curl -fsS http://127.0.0.1:8765/health',
      'curl -fsS http://127.0.0.1:8765/ready',
      'curl -fsS -o /dev/null -w "UI HTTP %{http_code}\\n" http://127.0.0.1:8765/',
      'docker exec outreach-app python scripts/verify_live.py --provider ollama --provider tsenta --provider serper',
      'docker exec outreach-app python scripts/check_local_model.py',
      '''docker exec outreach-app python -c "import sqlite3,json;from pathlib import Path;p=Path('/app/.local/outreach.sqlite');c=sqlite3.connect(p);counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['applications','baseline_members','drafts','outreach_events']};b=sqlite3.connect('/app/.local/aws-restore-check.sqlite');c.backup(b);assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert all(b.execute('SELECT count(*) FROM '+t).fetchone()[0]==n for t,n in counts.items());print(json.dumps({'integrity':'ok','restore':'passed','counts':counts}));b.close();Path('/app/.local/aws-restore-check.sqlite').unlink()"''',
      'docker restart outreach-app',
      'sleep 10',
      'curl -fsS http://127.0.0.1:8765/ready',
      'docker ps --format "{{.Names}} {{.Status}} {{.Ports}}"',
    ]
    params=LOCAL/'verify-parameters.json';params.write_text(json.dumps({'commands':['\n'.join(commands)],'executionTimeout':['1200']}))
    result=aws('ssm','send-command','--instance-ids',out['InstanceId'],'--document-name','AWS-RunShellScript','--parameters','file://'+str(params),'--timeout-seconds','1200')
    (LOCAL/'verify-command.json').write_text(json.dumps(result,indent=2))
    print('Verification command:',result['Command']['CommandId'])

def verify_status():
    out=json.loads((LOCAL/'outputs.json').read_text())
    cmd=json.loads((LOCAL/'verify-command.json').read_text())['Command']['CommandId']
    result=aws('ssm','get-command-invocation','--command-id',cmd,'--instance-id',out['InstanceId'])
    (LOCAL/'verify-result.json').write_text(json.dumps(result,indent=2))
    print('Verification status:',result['Status'])
    print(result.get('StandardOutputContent',''))
    print(result.get('StandardErrorContent',''))

def cleanup():
    out=json.loads((LOCAL/'outputs.json').read_text())
    # Preserve any normal OAuth refresh performed by the cloud verification.
    import sys
    sys.path.insert(0,str(ROOT))
    from backend.security import Keychain
    latest=json.loads(aws('secretsmanager','get-secret-value','--secret-id',out['CredentialSecret'])['SecretString'])
    vault=Keychain()
    if latest.get('tsenta'):
        vault.put('tsenta',latest['tsenta'])
    instance=aws('ec2','describe-instances','--instance-ids',out['InstanceId'])['Reservations'][0]['Instances'][0]
    volumes=[v['Ebs']['VolumeId'] for v in instance['BlockDeviceMappings']]
    (LOCAL/'cleanup-volumes.json').write_text(json.dumps(volumes))
    delete_versions(out['ReleaseBucket'])
    aws('cloudformation','delete-stack','--stack-name',STACK)
    print('Stack deletion requested; retained disk identifiers saved for final removal')

def cleanup_finish():
    stacks=aws('cloudformation','list-stacks','--stack-status-filter','DELETE_IN_PROGRESS','DELETE_FAILED','CREATE_COMPLETE')['StackSummaries']
    assert not any(s['StackName']==STACK for s in stacks),'Stack deletion not complete'
    for volume in json.loads((LOCAL/'cleanup-volumes.json').read_text()):
        disk=aws('ec2','describe-volumes','--volume-ids',volume)['Volumes'][0]
        assert disk['State']=='available' and not disk['Attachments']
        aws('ec2','delete-volume','--volume-id',volume)
    print('Retained deployment disks deleted')

def audit():
    out=json.loads((LOCAL/'outputs.json').read_text())
    results={
      'instances':aws('ec2','describe-instances','--filters','Name=tag:Project,Values=auto-outreach-system')['Reservations'],
      'volumes':aws('ec2','describe-volumes','--filters','Name=status,Values=available')['Volumes'],
      'addresses':aws('ec2','describe-addresses')['Addresses'],
      'plan':aws('freetier','get-account-plan-state'),
      'buckets':aws('s3api','list-buckets')['Buckets'],
      'secrets':aws('secretsmanager','list-secrets')['SecretList'],
    }
    (LOCAL/'cleanup-audit.json').write_text(json.dumps(results,indent=2))
    print(json.dumps({'instance_states':[i['State']['Name'] for r in results['instances'] for i in r['Instances']], 'unattached_volumes':len(results['volumes']),'elastic_ips':len(results['addresses']),'release_bucket_remaining':any(b['Name']==out['ReleaseBucket'] for b in results['buckets']),'credential_secret_remaining':any(s['ARN']==out['CredentialSecret'] for s in results['secrets']),'plan':results['plan']},indent=2))

if __name__=='__main__':
    actions={'prepare':lambda:provision(False),'provision':provision,'status':outputs,'release':release,'install-status':command_status,'verify':verify,'verify-status':verify_status,'cleanup':cleanup,'cleanup-finish':cleanup_finish,'audit':audit}
    p=argparse.ArgumentParser();p.add_argument('action',choices=actions)
    actions[p.parse_args().action]()
