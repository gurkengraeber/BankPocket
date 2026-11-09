import os

import pytest

from bankpocket.vault import Vault, VaultError


def test_roundtrip_and_permissions(tmp_path):
    v = Vault.from_file(tmp_path / "secret.key")
    token = v.encrypt("12345")
    assert "12345" not in token
    assert v.decrypt_str(token) == "12345"
    assert os.stat(tmp_path / "secret.key").st_mode & 0o777 == 0o600
    # gleicher Schlüssel nach Neustart
    assert Vault.from_file(tmp_path / "secret.key").decrypt_str(token) == "12345"


def test_wrong_key_fails(tmp_path):
    token = Vault.from_file(tmp_path / "a.key").encrypt(b"geheim")
    with pytest.raises(VaultError):
        Vault.from_file(tmp_path / "b.key").decrypt(token)
