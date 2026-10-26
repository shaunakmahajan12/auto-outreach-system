import ipaddress
import json
import re
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit


class Unavailable(Exception):
    pass


class Retryable(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class InvalidOutput(Retryable):
    """Provider returned invalid structured output or unapproved evidence references."""

    pass


def public_url(value, linkedin=False):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\x00-\x1f\\]', value):
        raise ValueError('Invalid external URL')
    parsed = urlsplit(value)
    host = (parsed.hostname or '').lower()
    if (
        parsed.scheme != 'https'
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError('Only public HTTPS URLs are supported')
    if (
        not host
        or '.' not in host
        or host.endswith(('.local', '.localhost', '.internal', '.test'))
        or host == 'localhost'
    ):
        raise ValueError('Local URLs are not allowed')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('IP addresses are not supported')
    if re.fullmatch(r'[0-9.]+', host) or not re.fullmatch(r'[a-z0-9.-]+', host):
        raise ValueError('Invalid hostname')
    if linkedin:
        if host not in ('linkedin.com', 'www.linkedin.com') or not re.fullmatch(
            r'/in/[A-Za-z0-9_%-]+/?', parsed.path
        ):
            raise ValueError('A LinkedIn /in/ profile URL is required')
        return urlunsplit(('https', 'www.linkedin.com', parsed.path.rstrip('/'), '', ''))
    return value


class CredentialStore(Protocol):
    def get(self, name: str) -> Any: ...
    def put(self, name: str, value: Any) -> None: ...
    def delete(self, name: str) -> None: ...


class Keychain:
    service = 'local.application-outreach-assistant'

    def __init__(self):
        # Explicit native backend: never fall back to plaintext keyrings.
        from keyring.backends.macOS import Keyring

        self.backend = Keyring()

    def get(self, name):
        try:
            value = self.backend.get_password(self.service, name)
            return json.loads(value) if value else None
        except Exception:
            raise Unavailable(
                'macOS Keychain unavailable. Unlock your login keychain and retry.'
            ) from None

    def put(self, name, value):
        try:
            self.backend.set_password(self.service, name, json.dumps(value))
        except Exception:
            raise Unavailable(
                'Could not save credentials in macOS Keychain; nothing was saved to a file.'
            ) from None

    def delete(self, name):
        try:
            if self.backend.get_password(self.service, name):
                self.backend.delete_password(self.service, name)
        except Exception:
            raise Unavailable('Could not remove the Keychain entry.') from None


class DeploymentSecrets:
    """Read-only deployment secret injection. Values never enter settings responses."""

    def get(self, name):
        import os

        raw = os.getenv('OUTREACH_SECRET_' + name.upper())
        if not raw:
            return None
        if name == 'tsenta':
            try:
                return json.loads(raw)
            except ValueError:
                raise Unavailable('Deployment Tsenta secret has invalid format.') from None
        return raw

    def put(self, name, value):
        raise Unavailable(
            'Update this credential through the deployment secret store and restart the app.'
        )

    def delete(self, name):
        raise Unavailable(
            'Remove this credential from the deployment secret store and restart the app.'
        )


class AwsSecrets:
    """Writable deployment credential provider for an existing Secrets Manager secret.

    Does not create secrets/resources. One app instance serializes credential updates.
    """

    def __init__(self, secret_id, client=None):
        import threading

        self.secret_id = secret_id
        self.client = client
        self.lock = threading.RLock()

    def _client(self):
        if self.client is None:
            try:
                import boto3

                self.client = boto3.client('secretsmanager')
            except Exception:
                raise Unavailable(
                    'AWS credential store requires the optional AWS SDK and a configured task role.'
                ) from None
        return self.client

    def _read(self):
        try:
            return json.loads(
                self._client().get_secret_value(SecretId=self.secret_id)['SecretString']
            )
        except Exception:
            raise Unavailable(
                'Deployment credential secret is unavailable or invalid; check task-role permissions.'
            ) from None

    def get(self, name):
        with self.lock:
            return self._read().get(name)

    def put(self, name, value):
        with self.lock:
            data = self._read()
            data[name] = value
            try:
                self._client().put_secret_value(
                    SecretId=self.secret_id, SecretString=json.dumps(data)
                )
            except Exception:
                raise Unavailable(
                    'Deployment credential update failed. Credentials were not logged.'
                ) from None

    def delete(self, name):
        with self.lock:
            data = self._read()
            data.pop(name, None)
            try:
                self._client().put_secret_value(
                    SecretId=self.secret_id, SecretString=json.dumps(data)
                )
            except Exception:
                raise Unavailable('Deployment credential removal failed.') from None
