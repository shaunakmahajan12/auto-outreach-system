# AWS deployment verification — October 13, 2026

The real application was deployed and tested in **us-east-2** using the project's
AWS Free Plan credits. This was a temporary private deployment for hands-on
verification, not an always-on public service.

## Architecture

- CloudFormation provisioned one Amazon Linux 2023 `m7i-flex.large` EC2 host
  (2 vCPUs, 8 GiB RAM), a private S3 release bucket, a Secrets Manager secret,
  an instance role/profile, and a security group with **zero inbound rules**.
- The app ran as a non-root Docker container. Ollama ran in another container
  on the same Docker network. The dashboard bound only to host `127.0.0.1:8765`;
  model port 11434 had no host publication.
- IAM-authorized Systems Manager port forwarding provided browser access.
  No inbound SSH, public app listener, domain, load balancer, or NAT gateway.
- The 40 GiB gp3 EBS disk was encrypted. IMDSv2 was required, with hop limit 2
  for container access to the narrowly scoped instance role.
- Source archives and workspace snapshots used encrypted private S3 storage
  with public access blocked and a bucket policy denying non-TLS requests.
  The source archive excluded credentials, `.env`, local data, and dependencies.
- Provider credentials transferred directly from macOS Keychain to Secrets
  Manager in memory. They were not included in images, templates, or logs.
  The cloud credential provider supported normal OAuth refresh through its role.

## Verified results

- Local `cfn-lint` validation passed. CloudFormation Guard passed the custom
  encryption, metadata-token, and no-ingress checks. AWS template validation
  passed, and CloudFormation reached `CREATE_COMPLETE`.
- The release archive's SHA-256 was checked on the host before the image build.
- `/health` and `/ready` passed; a headless Chromium browser rendered the real
  dashboard over the Session Manager tunnel with HTTP 200.
- Live Tsenta complete-history reads passed, validating 797 applications.
  One Serper public test query passed. The normal startup sync updated the
  cloud workspace from the source snapshot's 746 applications to 797.
- The AWS-hosted `qwen3:4b` model ranked fictional evidence and generated a
  validated fictional draft. This check did not send messages or use real
  contact data. `nomic-embed-text` was installed; a separate embedding inference
  test was not performed on AWS.
- All 281 immutable baseline members, 195 saved drafts, and 8 outreach events
  were preserved. The baseline fingerprint exactly matched the local snapshot.
- An offline SQLite backup/restore check compared full row contents across
  all 26 ledger tables and both graph-checkpoint tables. Integrity checks passed.
- Readiness passed after container restart and after the offline restore check.
- No outreach was sent. Automatic research, role extraction, polling, and raw
  tracing were disabled for the temporary host.

Release SHA-256:
`e3bf78c13632839137d032cf6f1b174b39836520592bc62c5e6aaca206c3acee`

Application image ID:
`sha256:2901d19c83f4b66a8ff41de7f73c556d1702d982ab0c4621e2cb31dfcccbb683`

## Cost and lifecycle

The project was verified as `FREE` and `ACTIVE`, with $100 in credits before
deployment. No paid-plan upgrade, subscription, or reserved commitment was made.
Compute pricing was $0.09576/hour; resources were operated only for the temporary
verification. AWS billing/credit usage can arrive after teardown, so the initial
credit balance is not a final usage statement.

Teardown is complete. The final inventory confirmed the EC2 instance terminated,
zero unattached volumes, zero Elastic IPs, and no remaining release bucket or
credential secret. CloudFormation deleted the stack and its service role,
instance profile, and security group; the separately retained EBS disk was then
deleted. All private S3 object versions were removed before bucket deletion.
The project remains `FREE` and `ACTIVE`; the API still reported $100 remaining
at the final check, subject to delayed usage accounting. Original workspace
databases remain on the Mac; normal cloud OAuth refresh was copied back to the
native Keychain. No hosting resources were left running by this verification.

## Evidence and repeatability

Deployment tooling is in `infra/aws/deploy_private.py`, `install_host.sh`,
and `private.guard`. The deployment script generates its project-specific
`private-stack.json` in ignored `.local/aws-deployment/`. This is single-project operational
tooling: regenerating the template resolves the selected project's default VPC,
subnet, and current Amazon Linux image. Provisioning creates resources and uses
credits; it should only be run for an intentional deployment. Keep the local
worker stopped while operating a cloud copy of the workspace.

Private raw AWS command results, resource IDs, the source summary, browser result,
and a dashboard screenshot are in ignored `.local/aws-deployment/`. The screenshot
contains personal application history and should not be committed or published.

This verifies a private single-host deployment. It does not establish public
HTTPS hosting, new OAuth registration/reconnect callbacks, production availability,
RDS hosting, or a general model-quality benchmark.

## Résumé wording

> Deployed and validated a Dockerized outreach automation system on AWS EC2 using
> CloudFormation, encrypted EBS storage, Secrets Manager, and IAM-controlled access
> through AWS Systems Manager.

Describe it as a temporary verified deployment if asked about current hosting.
