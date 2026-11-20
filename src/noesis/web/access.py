"""Per-request Access verification. The local verifier is the identity authority."""
import hashlib
import hmac
import http.client
import os
import re
import secrets

from noesis.application.web import AppError


class AccessIdentity:
    def __init__(self):
        enabled = os.environ.get('NOESIS_ACCESS_ENABLED', 'false').casefold()
        if enabled not in {'true', 'false'}:
            raise ValueError('NOESIS_ACCESS_ENABLED must be true or false')
        self.enabled = enabled == 'true'
        self.email = os.environ.get('NOESIS_ACCESS_EMAIL', '')
        self.owner = os.environ.get('NOESIS_ACCESS_OWNER', 'owner')
        if self.enabled:
            if self.email and not self.valid_email(self.email):
                raise ValueError('NOESIS_ACCESS_EMAIL must be one exact email address')
            if not self.owner or len(self.owner) > 128 or self.owner != self.owner.strip():
                raise ValueError('NOESIS_ACCESS_OWNER must be an existing username')
        self.csrf_key = secrets.token_bytes(32)

    @staticmethod
    def valid_email(email):
        return 3 <= len(email) <= 254 and re.fullmatch(r'[^\s,@]+@[^\s,@]+', email) is not None

    def verify(self, tokens):
        if len(tokens) != 1 or len(tokens[0]) > 16384 or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', tokens[0]):
            raise AppError('Invalid Access identity', 401)
        # No proxy environment, redirects, cookies, inbound email, or other headers.
        connection = http.client.HTTPConnection('127.0.0.1', 8790, timeout=1)
        try:
            connection.request('GET', '/verify', headers={'Cf-Access-Jwt-Assertion': tokens[0]})
            response = connection.getresponse()
            emails = [value for name, value in response.getheaders() if name.casefold() == 'x-hermes-verified-email']
            if response.status != 200 or len(emails) != 1 or not self.valid_email(emails[0]) or (self.email and emails[0].casefold() != self.email.casefold()):
                raise AppError('Invalid Access identity', 401)
        except (OSError, http.client.HTTPException):
            raise AppError('Access verifier unavailable', 503) from None
        finally:
            connection.close()
        return hashlib.sha256(tokens[0].encode('ascii')).digest()

    def csrf(self, uid, token_digest):
        # Stable within this worker and JWT; no session or raw JWT reaches the browser.
        return hmac.new(self.csrf_key, uid.encode() + b'\0' + token_digest, hashlib.sha256).hexdigest()
