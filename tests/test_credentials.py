"""Credential-store tests (no real keyring: Secret Service is stubbed)."""

import pytest

from app.config.credentials import (
    CredentialStoreError,
    KeyringUnavailableError,
    SecretServiceStore,
    SessionOnlyStore,
    _select_store,
    get_default_store,
)


def test_session_store_roundtrip():
    store = SessionOnlyStore()
    assert store.kind == "session"
    assert store.available is True
    assert store.get() is None
    store.set("sk-abc123")
    assert store.get() == "sk-abc123"
    store.delete()
    assert store.get() is None


def test_default_store_is_shared(_isolated_key_store):
    store = get_default_store()
    assert store is _isolated_key_store
    store.set("sk-shared")
    assert get_default_store().get() == "sk-shared"


class _FakeSecret:
    def __init__(self, value):
        self._value = value
        self.deleted = False

    def get_secret(self):
        return self._value

    def delete(self):
        self.deleted = True


class _FakeCollection:
    def __init__(self, locked=False, items=None, existing=None):
        self._locked = locked
        self._items = list(items or [])
        self._existing = existing if existing is not None else {}

    def is_locked(self):
        return self._locked

    def unlock(self):
        self._locked = False

    def search_items(self, attrs):
        return self._items

    def create_item(self, label, attrs, secret, replace=True):
        self._existing[label] = secret


class _FakeSecretStorage:
    def __init__(self, collection, fail_init=False):
        self._collection = collection
        self.fail_init = fail_init

    def dbus_init(self):
        if self.fail_init:
            raise RuntimeError("no session bus")
        return object()

    def get_default_collection(self, bus):
        return self._collection


def _patch_store(monkeypatch, fake_ss):
    import app.config.credentials as cred

    monkeypatch.setattr(cred, "_load_secretstorage", lambda: fake_ss)


def test_secret_service_available_and_roundtrip(monkeypatch):
    collection = _FakeCollection(items=[_FakeSecret(b"sk-secret")])
    _patch_store(monkeypatch, _FakeSecretStorage(collection))
    store = SecretServiceStore()
    assert store.available is True
    assert store.get() == "sk-secret"
    store.set("sk-new")
    assert collection._existing.get("BriizFlow OpenAI API key") == b"sk-new"
    store.delete()


def test_secret_service_unavailable_raises(monkeypatch):
    _patch_store(monkeypatch, _FakeSecretStorage(None, fail_init=True))
    store = SecretServiceStore()
    with pytest.raises(KeyringUnavailableError):
        store.get()


def test_missing_secretstorage_import_is_unavailable(monkeypatch):
    import app.config.credentials as cred

    monkeypatch.setattr(cred, "_load_secretstorage", lambda: None)
    store = SecretServiceStore()
    assert store.available is False
    with pytest.raises(KeyringUnavailableError):
        store.get()


def test_locked_collection_is_unlocked(monkeypatch):
    collection = _FakeCollection(locked=True, items=[_FakeSecret(b"unlocked-secret")])
    _patch_store(monkeypatch, _FakeSecretStorage(collection))
    store = SecretServiceStore()
    assert store.get() == "unlocked-secret"
    assert collection.is_locked() is False


def test_store_errors_raise_credential_store_error(monkeypatch):
    class _Boom(_FakeSecretStorage):
        def dbus_init(self):
            return object()

    class _BoomCollection(_FakeCollection):
        def search_items(self, attrs):
            raise RuntimeError("nope")

    _patch_store(monkeypatch, _Boom(_BoomCollection()))
    store = SecretServiceStore()
    with pytest.raises(CredentialStoreError):
        store.get()


def test_select_store_falls_back_to_session_when_keyring_unavailable(monkeypatch):
    import app.config.credentials as cred

    monkeypatch.setattr(cred, "_load_secretstorage", lambda: None)
    store = _select_store()
    assert isinstance(store, SessionOnlyStore)


def test_select_store_prefers_secret_service(monkeypatch):
    _patch_store(monkeypatch, _FakeSecretStorage(_FakeCollection()))
    store = _select_store()
    assert isinstance(store, SecretServiceStore)


def test_select_store_probe_does_not_delete_stored_key(monkeypatch):
    """The store-selection probe must be read-only: it must not wipe a key
    that is already saved in the keyring (regression: a delete() probe used to
    erase the user's key on every launch)."""
    item = _FakeSecret(b"sk-keep-me")
    collection = _FakeCollection(items=[item])
    _patch_store(monkeypatch, _FakeSecretStorage(collection))
    store = _select_store()
    assert isinstance(store, SecretServiceStore)
    assert item.deleted is False, "probe must not delete the stored key"
