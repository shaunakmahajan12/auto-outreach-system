import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit


class Unavailable(Exception):
    pass


class Retryable(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def public_url(value, linkedin=False):
    if not isinstance(value,str) or len(value)>2048 or re.search(r'[\s\x00-\x1f\\]',value):
        raise ValueError('Invalid external URL')
    parsed=urlsplit(value)
    host=(parsed.hostname or '').lower()
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only public HTTPS URLs are supported')
    if not host or '.' not in host or host.endswith(('.local','.localhost','.internal','.test')) or host=='localhost':
        raise ValueError('Local URLs are not allowed')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('IP addresses are not supported')
    if re.fullmatch(r'[0-9.]+',host) or not re.fullmatch(r'[a-z0-9.-]+',host):
        raise ValueError('Invalid hostname')
    if linkedin:
        if host not in ('linkedin.com','www.linkedin.com') or not re.fullmatch(r'/in/[A-Za-z0-9_%-]+/?',parsed.path):
            raise ValueError('A LinkedIn /in/ profile URL is required')
        return urlunsplit(('https','www.linkedin.com',parsed.path.rstrip('/'),'',''))
    return value


class Keychain:
    service='local.application-outreach-assistant'
    def __init__(self):
        # Explicit native backend: never fall back to plaintext keyrings.
        from keyring.backends.macOS import Keyring
        self.backend=Keyring()
    def get(self,name):
        try:
            value=self.backend.get_password(self.service,name)
            return json.loads(value) if value else None
        except Exception:
            raise Unavailable('macOS Keychain unavailable. Unlock your login keychain and retry.') from None
    def put(self,name,value):
        try:
            self.backend.set_password(self.service,name,json.dumps(value))
        except Exception:
            raise Unavailable('Could not save credentials in macOS Keychain; nothing was saved to a file.') from None
    def delete(self,name):
        try:
            if self.backend.get_password(self.service,name):
                self.backend.delete_password(self.service,name)
        except Exception:
            raise Unavailable('Could not remove the Keychain entry.') from None
