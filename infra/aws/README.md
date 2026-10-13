# Private AWS rollout

Status: a temporary EC2 deployment was completed and verified on October 13, 2026.
Teardown is complete; no hosting resources remain running. See the
[deployment verification](../../docs/aws-deployment-verification.md) for actual
architecture, results, limitations, and cleanup status. The procedure below is
the longer-lived rollout design; the temporary deployment built the image on the
host from a SHA-256-verified private S3 archive rather than using ECR.

For this single-workspace app, start with one EC2 host running the app and Ollama.
Use the tested SQLite ledger and checkpoint sidecar on encrypted persistent EBS.
PostgreSQL/RDS is an optional later database switch, not a prerequisite for hosting.
Running Ollama on the host avoids depending on the owner's Mac staying awake.
Instance sizing and expected monthly charges must be confirmed for the selected
region and usage budget; CPU-only model latency must be measured on the target host.

## Private access

- No inbound security-group rules, public application listener or SSH key.
- Access the dashboard using an IAM-authorized Session Manager port-forwarding
  session to host localhost:8765. The app container publishes only on host loopback.
- Ollama is reachable only on the app's internal Docker network; do not publish 11434.
- Use the existing localhost Tsenta callback through the active port-forward session.
  Verify it on the actual deployment before depending on reconnect/refresh.
- The host needs outbound access to AWS APIs, container registries and model/provider
  endpoints. Choose outbound networking before provisioning; a public subnet with no
  inbound rules and a public IP is one option. Private subnets require configured
  endpoints/egress and can introduce additional charges.

## Release and persistence

1. Authenticate the AWS CLI with a named SSO profile. Confirm account ID and region.
2. Produce the exact infrastructure change set and region-specific cost estimate.
   Include compute, EBS, snapshots/backups, public IPv4 or private egress, ECR and secrets.
3. Build the application image with `INSTALL_AWS_SECRETS=true` for the target CPU
   architecture and push a versioned image to private ECR. Pin deployment to its digest.
4. Provision the host with IMDSv2 required and encrypted persistent storage. Give its
   role only SSM connectivity, release-image pulls, its credential secret and its
   backup prefix. Preserve data volumes when replacing the host.
5. Keep one app worker. Mount a private writable persistent directory at `/app/.local`
   with UID/GID 10001. Use a separate persistent Ollama model directory. Configure
   restart policies and readiness checks.
6. Put provider credentials into a dedicated Secrets Manager secret; use AwsSecrets
   so OAuth refresh can persist. Do not bake credentials into the image or user data.
7. Stop the local worker for a consistent ledger/checkpoint snapshot, back up both,
   and transfer them privately. Validate integrity and baseline membership before
   starting the cloud worker. Preserve the original local copies; avoid two active
   workers operating the same workspace.
8. Verify health/readiness, the actual model, live search/history, OAuth reconnect and
   refresh, application UI and preserved manual drafts/events. Sending remains manual.
9. Rehearse restoring both ledger and checkpoints from encrypted backups on a
   separate path before enabling a backup schedule. Document stop/start and rollback.

If public HTTPS is chosen instead, add a domain, TLS termination and the app's signed
session authentication, CSRF and explicit host/origin configuration. The remote
Tsenta callback needs verification for that exact hostname. See
[the private deployment guide](../../docs/private-aws.md).

Required inputs: AWS account/profile, region, spending limit and private Session
Manager access versus a public HTTPS domain. No cloud provisioning can be targeted
until the account and region are known.

AWS references:

- [Session Manager port-forwarding sessions](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html)
- [Install Docker on Amazon Linux 2023](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/create-container-image.html)
- [EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
