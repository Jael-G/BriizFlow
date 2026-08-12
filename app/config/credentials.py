"""Narrow credential store for the OpenAI API key.

The key must never be written to ``settings.json``, logs, backups, debug
output, environment variables or command-line arguments. It lives in the
freedesktop Secret Service (the desktop keyring) when available; otherwise
BriizFlow falls back to a clearly-labelled :class:`SessionOnlyStore` that keeps the
key purely in memory and forgets it on exit. There is deliberately no
plaintext-on-disk fallback.

Threat model: a local desktop app must hold the key in process memory to make
the API request, so no design can prevent a local administrator, debugger,
malware running as the same user, or a compromised Python process from
extracting it. The goal is to prevent casual disclosure, plaintext-at-rest
leakage, accidental logging and UI shoulder-surfing — not to claim the key is
"completely unextractable". Prefer a restricted-scope OpenAI key with a
spending limit so it can be revoked/rotated independently.

The store object wraps the whole interface used by the runner and the settings
page:

* ``kind``        — ``"keyring"`` or ``"session"`` (for UI labelling)
* ``available``   — whether reads/writes can succeed right now
* ``get()``       — the key, or ``None`` when none is saved
* ``set(value)``  — store (replace) the key
* ``delete()``    — remove the stored key
"""

import logging

log = logging.getLogger(__name__)
SERVICE = "briizflow"
ACCOUNT = "openai-api-key"
_ATTRIBUTES = {"application": SERVICE, "account": ACCOUNT}


class CredentialStoreError(Exception):
    """Base class for credential-store failures. Messages never contain the
    secret itself."""


class KeyringUnavailableError(CredentialStoreError):
    """The secure Secret Service keyring is not available."""


def _load_secretstorage():
    """Import ``secretstorage`` lazily; ``None`` when it is not installed."""
    try:
        import secretstorage

        return secretstorage
    except ImportError:
        return None


class SecretServiceStore:
    """Stores the key in the freedesktop Secret Service (the system keyring).

    Uses :mod:`secretstorage` (a maintained pure-Python D-Bus integration).
    When the service is missing or the collection cannot be read, operations
    raise :class:`KeyringUnavailableError` / :class:`CredentialStoreError`
    rather than silently degrading to plaintext storage.
    """

    kind = "keyring"

    def __init__(self):
        self._bus = None

    @property
    def available(self):
        return _load_secretstorage() is not None

    def _require(self):
        """Return ``(secretstorage, bus)`` or raise KeyringUnavailableError."""
        ss = _load_secretstorage()
        if ss is None:
            raise KeyringUnavailableError("Secret Service is not available.")
        if self._bus is None:
            try:
                self._bus = ss.dbus_init()
            except Exception as exc:
                log.warning("Could not connect to the Secret Service: %s", exc)
                raise KeyringUnavailableError("Could not connect to the keyring.") from exc
        return ss, self._bus

    def _collection(self, ss, bus):
        collection = ss.get_default_collection(bus)
        if collection.is_locked():
            collection.unlock()
        return collection

    def get(self):
        """Return the saved key, or ``None``."""
        (ss, bus) = self._require()
        try:
            collection = self._collection(ss, bus)
            for item in collection.search_items(_ATTRIBUTES):
                secret = item.get_secret()
                if secret:
                    return secret.decode("utf-8")
            return None
        except KeyringUnavailableError:
            raise
        except Exception as exc:
            log.error("Could not read the API key from the keyring: %s", exc)
            raise CredentialStoreError("Could not read the API key.") from exc

    def set(self, value):
        """Store (replace) the key."""
        (ss, bus) = self._require()
        try:
            collection = self._collection(ss, bus)
            collection.create_item(
                "BriizFlow OpenAI API key",
                _ATTRIBUTES,
                str(value).encode("utf-8"),
                replace=True,
            )
            return None
        except CredentialStoreError:
            raise
        except Exception as exc:
            log.error("Could not save the API key to the keyring: %s", exc)
            raise CredentialStoreError("Could not save the API key.") from exc

    def delete(self):
        """Remove the stored key."""
        (ss, bus) = self._require()
        try:
            collection = self._collection(ss, bus)
            for item in list(collection.search_items(_ATTRIBUTES)):
                item.delete()
            return None
        except Exception as exc:
            log.error("Could not remove the API key from the keyring: %s", exc)
            raise CredentialStoreError("Could not remove the API key.") from exc


class SessionOnlyStore:
    """In-memory key store.

    The key lives only for this process and is dropped on exit; it is never
    persisted to disk. Used as the explicit, clearly-labelled fallback when no
    desktop Secret Service is available. It is *not* a security upgrade over
    the keyring — it just avoids writing an unencrypted secret to disk.
    """

    kind = "session"
    available = True

    def __init__(self):
        self._key = None

    def get(self):
        return self._key

    def set(self, value):
        self._key = value

    def delete(self):
        self._key = None


_default_store = None


def _select_store():
    """Pick the best store: the system keyring when available, otherwise the
    explicitly-labelled in-memory session store.

    ``available`` only checks that ``secretstorage`` imports; we additionally
    probe the real D-Bus connection here so a broken/locked keyring degrades to
    the session store instead of erroring on every subsequent operation.
    """
    store = SecretServiceStore()
    if store.available:
        try:
            # Read-only probe: verify the keyring is reachable WITHOUT touching
            # any stored key (a delete() probe would wipe the user's key).
            store.get()
            log.info("OpenAI API key will be stored in the system keyring.")
            return store
        except (KeyringUnavailableError, CredentialStoreError) as exc:
            log.warning(
                "Secret Service unusable (%s); the OpenAI API key will only "
                "be kept in memory for this session.",
                exc,
            )
            return SessionOnlyStore()
    log.warning(
        "Desktop Secret Service unavailable; the OpenAI API key will only "
        "be kept in memory for this session."
    )
    return SessionOnlyStore()


def get_default_store():
    """Return the process-wide key store.

    Cached so the settings page and the runner share one instance — essential
    for the in-memory fallback, where the key must be visible to both.
    """
    global _default_store
    if _default_store is None:
        _default_store = _select_store()
    return _default_store
