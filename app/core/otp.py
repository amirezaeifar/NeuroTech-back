"""Redis-backed OTP challenges and authentication counters."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from redis.exceptions import RedisError

from app.core.redis_store import RedisStore
from app.core.security import generate_otp, keyed_digest
from app.domain.errors import (
    AuthenticationError,
    RateLimitExceededError,
    TemporarilyUnavailableError,
)
from app.domain.ports import SmsSender

_REQUEST_SCRIPT = """
if redis.call('EXISTS', KEYS[4]) == 1 then
  return {0, 'locked', redis.call('TTL', KEYS[4])}
end
if redis.call('EXISTS', KEYS[3]) == 1 then
  return {0, 'cooldown', redis.call('TTL', KEYS[3])}
end
local identity_count = redis.call('INCR', KEYS[1])
if identity_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
if identity_count > tonumber(ARGV[2]) then
  return {0, 'identity_limit', redis.call('TTL', KEYS[1])}
end
local ip_count = redis.call('INCR', KEYS[2])
if ip_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[1]) end
if ip_count > tonumber(ARGV[3]) then
  return {0, 'ip_limit', redis.call('TTL', KEYS[2])}
end
redis.call('SET', KEYS[3], '1', 'EX', ARGV[4])
redis.call('HSET', KEYS[5], 'digest', ARGV[5], 'attempts', 0,
  'identity_hash', ARGV[6], 'purpose', ARGV[7])
redis.call('EXPIRE', KEYS[5], ARGV[8])
return {1, 'created'}
"""

_VERIFY_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {0, 'expired'} end
local expected = redis.call('HGET', KEYS[1], 'digest')
local identity_hash = redis.call('HGET', KEYS[1], 'identity_hash')
local purpose = redis.call('HGET', KEYS[1], 'purpose')
if expected == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return {1, identity_hash, purpose}
end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  redis.call('SET', ARGV[3] .. identity_hash, '1', 'EX', ARGV[4])
  return {-1, 'locked'}
end
return {-1, tostring(attempts)}
"""


@dataclass(frozen=True, slots=True)
class OtpChallenge:
    challenge_id: str
    expires_in: int = 300
    resend_after: int = 60


class RedisOtpService:
    def __init__(self, store: RedisStore, sms_sender: SmsSender, secret: str) -> None:
        self.store = store
        self.sms_sender = sms_sender
        self.secret = secret
        self._request = store.client.register_script(_REQUEST_SCRIPT)
        self._verify = store.client.register_script(_VERIFY_SCRIPT)

    def request(self, *, phone: str, purpose: str, ip_address: str) -> OtpChallenge:
        identity_hash = keyed_digest(self.secret, phone)
        ip_hash = keyed_digest(self.secret, ip_address)
        challenge_id = str(uuid4())
        code = generate_otp()
        keys = [
            self.store.key("otp", "send", identity_hash),
            self.store.key("otp", "ip", ip_hash),
            self.store.key("otp", "cooldown", identity_hash),
            self.store.key("otp", "lock", identity_hash),
            self.store.key("otp", "challenge", challenge_id),
        ]
        try:
            result = self._request(
                keys=keys,
                args=[
                    3600,
                    5,
                    10,
                    60,
                    keyed_digest(self.secret, code),
                    identity_hash,
                    purpose,
                    300,
                ],
            )
        except RedisError as error:
            raise TemporarilyUnavailableError(
                "Authentication is temporarily unavailable."
            ) from error
        if int(result[0]) != 1:
            reason = str(result[1])
            retry_after = max(1, int(result[2])) if len(result) > 2 else 60
            if reason == "cooldown":
                raise RateLimitExceededError(
                    "Wait before requesting another verification code.", retry_after
                )
            if reason == "locked":
                raise RateLimitExceededError(
                    "Verification attempts are temporarily locked.", retry_after
                )
            raise RateLimitExceededError("OTP request limit exceeded.", retry_after)
        if hasattr(self.sms_sender, "send_verification"):
            self.sms_sender.send_verification(phone, code)
        else:
            self.sms_sender.send(phone, f"NeuroTech verification code: {code}")
        return OtpChallenge(challenge_id)

    def verify(self, *, challenge_id: str, code: str) -> tuple[str, str]:
        challenge_key = self.store.key("otp", "challenge", challenge_id)
        lock_prefix = self.store.key("otp", "lock", "")
        try:
            result = self._verify(
                keys=[challenge_key],
                args=[keyed_digest(self.secret, code), 5, lock_prefix, 900],
            )
        except RedisError as error:
            raise TemporarilyUnavailableError(
                "Authentication is temporarily unavailable."
            ) from error
        if int(result[0]) != 1:
            raise AuthenticationError("The verification code is invalid or expired.")
        return str(result[1]), str(result[2])

    def assert_password_login_allowed(self, identity: str) -> None:
        identity_hash = keyed_digest(self.secret, identity)
        try:
            lock_key = self.store.key("auth", "password-lock", identity_hash)
            retry_after = self.store.client.ttl(lock_key)
            if retry_after > 0:
                raise RateLimitExceededError(
                    "Too many failed login attempts. Try again later.", retry_after
                )
        except RedisError as error:
            raise TemporarilyUnavailableError(
                "Authentication is temporarily unavailable."
            ) from error

    def record_password_failure(self, identity: str) -> None:
        identity_hash = keyed_digest(self.secret, identity)
        counter = self.store.key("auth", "password-fail", identity_hash)
        lock = self.store.key("auth", "password-lock", identity_hash)
        try:
            with self.store.client.pipeline(transaction=True) as pipe:
                pipe.incr(counter)
                pipe.expire(counter, 900)
                count, _ = pipe.execute()
            if int(count) >= 5:
                self.store.client.set(lock, "1", ex=900)
        except RedisError as error:
            raise TemporarilyUnavailableError(
                "Authentication is temporarily unavailable."
            ) from error

    def clear_password_failures(self, identity: str) -> None:
        identity_hash = keyed_digest(self.secret, identity)
        try:
            self.store.client.delete(
                self.store.key("auth", "password-fail", identity_hash),
                self.store.key("auth", "password-lock", identity_hash),
            )
        except RedisError as error:
            raise TemporarilyUnavailableError(
                "Authentication is temporarily unavailable."
            ) from error
