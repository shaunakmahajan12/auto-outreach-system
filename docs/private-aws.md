# Private AWS deployment guide (not deployed)

This is a single-workspace application, not a multi-tenant SaaS product. The local
and fictional paths are tested. Live PostgreSQL, AWS, TLS and real model behavior
need environment verification before any private rollout. No cloud resources were
provisioned and no application was published.

A small private deployment can use one ECS container task behind an HTTPS load
balancer, RDS PostgreSQL/pgvector, Secrets Manager and a persistent encrypted volume
for `.local` checkpoints. Use one worker and one task; this code does not provide
cross-instance scheduling locks. An EC2 container host with an encrypted persistent
volume is also possible. The choice and sizing depend on your existing environment;
no cost/performance estimates are asserted here. Restrict inbound access to a VPN,
private load balancer or explicit trusted networks in addition to app authentication.

1. Build the Docker image in a trusted CI/host, scan dependencies and push to your
   private registry only after review. Keep `.env`, `.local`, captures and databases
   outside the build context. The supplied .dockerignore excludes them.
2. Configure a private RDS PostgreSQL instance and confirm `vector` extension
   availability for the exact engine version. The migration role needs permission
   to install the extension; the runtime role should have only application DML and
   sequence rights. Put RDS in private subnets with security groups allowing only
   the container host/task. Require database TLS and encrypted backups. RDS extension
   availability/version varies by engine; check the [RDS extension matrix](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html).
3. Perform the validated SQLite import from a secured migration environment. Inspect
   all row counts, baseline membership, edited drafts and event history. Preserve
   source/backup snapshots. Switch DATABASE_URL only after the live PostgreSQL CI
   test and your restore rehearsal succeed; see operations.md.
4. Mount a private persistent `.local` volume for PostgreSQL marker, single-process
   lock and LangGraph checkpoint database. Back it up separately from RDS. Do not
   run two instances against the same SQLite checkpoint file. A task with ephemeral
   storage alone cannot preserve resumability through task replacement.
5. Inject DATABASE_URL, SESSION_SECRET, OUTREACH_USERS and provider secrets via
   Secrets Manager. Use narrowly scoped execution-role permissions and omit secrets
   from logs, command arguments, image layers and health responses. ECS can inject
   secret values through task definitions; rotation requires a fresh task to pick
   them up. Review [ECS secret injection and rotation behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html).
6. Terminate HTTPS with a valid certificate and redirect HTTP to HTTPS. Configure
   load balancer health path `/health`; check `/ready` for ledger availability.
   Forward the original approved Host; do not blindly trust arbitrary forwarded
   host/origin headers. Set OUTREACH_REMOTE=true, BIND_HOST=0.0.0.0,
   EXTERNAL_BASE_URL=https://your-private-host, ALLOWED_HOSTS=your-private-host and
   ALLOWED_ORIGINS=https://your-private-host. Remote startup refuses incomplete auth.
7. OUTREACH_USERS is a secret JSON mapping of usernames to password_hash and role
   (`operator` or read-only `reader`). Generate a hash interactively without echo:

   ```
   .venv/bin/python -c "import getpass; from backend.auth import hash_password; print(hash_password(getpass.getpass('Password: ')))"
   ```

   Store the hash directly in your secret manager; do not commit it. SESSION_SECRET
   must be a random 32+ character secret. `/login` verifies scrypt password hashes,
   rotates the signed session, uses Secure/HttpOnly/SameSite=Lax cookies with an
   eight-hour expiry, checks a login nonce, and rate-limits failed attempts per
   client/username. Every API read requires authentication; writes require operator
   role and a session-bound CSRF header. The local bootstrap token is never accepted
   as remote authentication. Password/role changes require restart; rotate session
   secret to invalidate all sessions. Review this small auth system against your
   organization’s SSO/MFA and audit requirements before enabling remote access.
8. CREDENTIAL_STORE=deployment reads OUTREACH_SECRET_SERPER and
   OUTREACH_SECRET_TSENTA (the OAuth credential JSON). Deployment credentials are
   read-only in the app; update secrets externally. Tsenta OAuth token refresh writes
   currently require a writable credential provider; verify your integration and
   supply one before depending on long-lived Tsenta sessions. Local Keychain remains
   writable. Serper and Ollama have independent availability/failure paths.
9. Set TSENTA_OAUTH_CALLBACK explicitly. This repository has only verified the local
   callback. Confirm provider dynamic-client registration, allowed redirect URI,
   OAuth state/PKCE, refresh contract and callback reachability with Tsenta before
   TSENTA_CALLBACK_VERIFIED=true. Do not assume arbitrary AWS callback support.
10. A cloud task cannot reach localhost Ollama on your Mac. Use a private VPN/tunnel
    and a protected gateway to a reachable Ollama endpoint, or operate a private
    Ollama-compatible model host in your network. Keep port 11434 off the public
    internet. Configure OLLAMA_URL and OLLAMA_MODEL, test structured output, embedding
    model availability and network recovery. Sleeping/disconnected local hosts will
    pause preparation; cached results and edits remain. A different vendor endpoint
    needs an implemented/tested model adapter, not just a URL change.

Optional Langfuse is an independently deployed service. Enable it separately with
LANGFUSE_ENABLED and injected endpoint/keys after privacy review; no observability
server is required or started by compose.yaml. Raw tracing stays off unless
TRACE_RAW_CONTENT=true is explicitly chosen. Read docs/evaluation.md for scope.

Deployment gate: run PostgreSQL import/vector/ledger integration tests against the
chosen version, container build/smoke tests, HTTPS cookie/CSRF/authorization checks,
backup/restore rehearsal and real-provider recovery tests. Test successful and
failed OAuth redirects with your registered callback. No sent messages or invitations
should result from any deployment verification: sending remains manual.

Writable OAuth credentials: optionally install `requirements-aws.txt`, set
AWS_CREDENTIAL_SECRET_ID to an **existing** Secrets Manager secret containing a JSON
object with `tsenta` and `serper` keys, and grant the task role GetSecretValue and
PutSecretValue on that secret. AwsSecrets supports OAuth refresh and credential
removal without local plaintext files. This provider has mocked interface tests;
validate IAM/rotation behavior against your existing secret before using it. It
never creates a secret. Without this option, environment injection remains read-only.

For the optional writable AWS provider in the supplied image, build with
`docker build --build-arg INSTALL_AWS_SECRETS=true -t outreach-private .` on your build
host. The default image keeps this optional SDK out. This command only builds an
image; it does not create AWS resources or publish it.
