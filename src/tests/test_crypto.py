"""
Tests for crypto module.

Tests encryption/decryption functionality and master key validation.
"""

import os
import pytest
import base64
import secrets

# Store original env
_original_env = {}


def setup_module():
    """Save original environment."""
    _original_env["MASTER_ENCRYPTION_KEY"] = os.environ.get("MASTER_ENCRYPTION_KEY")


def teardown_module():
    """Restore original environment."""
    if _original_env.get("MASTER_ENCRYPTION_KEY"):
        os.environ["MASTER_ENCRYPTION_KEY"] = _original_env["MASTER_ENCRYPTION_KEY"]
    elif "MASTER_ENCRYPTION_KEY" in os.environ:
        del os.environ["MASTER_ENCRYPTION_KEY"]


def _generate_test_key() -> str:
    """Generate a valid test master key."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


class TestMasterKeyValidation:
    """Tests for master key validation."""
    
    def test_key_not_configured(self):
        """Test detection of missing key."""
        if "MASTER_ENCRYPTION_KEY" in os.environ:
            del os.environ["MASTER_ENCRYPTION_KEY"]
        
        from src.common.crypto import is_master_key_configured, validate_master_key
        
        assert not is_master_key_configured()
        
        is_valid, msg = validate_master_key()
        assert not is_valid
        assert "not set" in msg.lower()
    
    def test_valid_key_configured(self):
        """Test validation of correct key."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import is_master_key_configured, validate_master_key
        
        assert is_master_key_configured()
        
        is_valid, msg = validate_master_key()
        assert is_valid
        assert "validated" in msg.lower()
    
    def test_invalid_key_length(self):
        """Test rejection of wrong-length key."""
        # 16 bytes instead of 32
        short_key = base64.b64encode(secrets.token_bytes(16)).decode()
        os.environ["MASTER_ENCRYPTION_KEY"] = short_key
        
        from src.common.crypto import validate_master_key
        
        is_valid, msg = validate_master_key()
        assert not is_valid
        assert "length" in msg.lower()
    
    def test_invalid_key_format(self):
        """Test rejection of non-base64 key."""
        os.environ["MASTER_ENCRYPTION_KEY"] = "not-valid-base64!!!"
        
        from src.common.crypto import validate_master_key
        
        is_valid, msg = validate_master_key()
        assert not is_valid


class TestCryptoService:
    """Tests for CryptoService encryption/decryption."""
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test that encrypt -> decrypt returns original."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import CryptoService
        
        crypto = CryptoService()
        
        original = "my secret private key 0x1234567890abcdef"
        encrypted = crypto.encrypt(original)
        decrypted = crypto.decrypt(encrypted)
        
        assert decrypted == original
        assert encrypted != original  # Should be different
    
    def test_encrypt_different_each_time(self):
        """Test that same plaintext encrypts differently (random IV)."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import CryptoService
        
        crypto = CryptoService()
        
        plaintext = "same text"
        encrypted1 = crypto.encrypt(plaintext)
        encrypted2 = crypto.encrypt(plaintext)
        
        # Different ciphertexts due to random IV
        assert encrypted1 != encrypted2
        
        # But both decrypt to same plaintext
        assert crypto.decrypt(encrypted1) == plaintext
        assert crypto.decrypt(encrypted2) == plaintext
    
    def test_wrong_key_fails_decrypt(self):
        """Test that wrong key fails decryption."""
        # Encrypt with key 1
        key1 = _generate_test_key()
        os.environ["MASTER_ENCRYPTION_KEY"] = key1
        
        from src.common.crypto import CryptoService
        from src.common.exceptions import SecurityError
        
        crypto1 = CryptoService()
        encrypted = crypto1.encrypt("secret data")
        
        # Try to decrypt with key 2
        key2 = _generate_test_key()
        os.environ["MASTER_ENCRYPTION_KEY"] = key2
        crypto2 = CryptoService()
        
        with pytest.raises(SecurityError):
            crypto2.decrypt(encrypted)
    
    def test_tampered_data_fails(self):
        """Test that tampered ciphertext fails verification."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import CryptoService
        from src.common.exceptions import SecurityError
        
        crypto = CryptoService()
        encrypted = crypto.encrypt("original data")
        
        # Tamper with the encrypted data
        import base64
        data = base64.b64decode(encrypted)
        tampered = data[:-1] + bytes([data[-1] ^ 0xFF])  # Flip last byte
        tampered_b64 = base64.b64encode(tampered).decode()
        
        with pytest.raises(SecurityError):
            crypto.decrypt(tampered_b64)
    
    def test_unicode_data(self):
        """Test encryption of unicode strings."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import CryptoService
        
        crypto = CryptoService()
        
        original = "🔐 Секретный ключ 密钥"
        encrypted = crypto.encrypt(original)
        decrypted = crypto.decrypt(encrypted)
        
        assert decrypted == original
    
    def test_empty_string(self):
        """Test encryption of empty string."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import CryptoService
        
        crypto = CryptoService()
        
        encrypted = crypto.encrypt("")
        decrypted = crypto.decrypt(encrypted)
        
        assert decrypted == ""
    
    def test_long_data(self):
        """Test encryption of large data."""
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.common.crypto import CryptoService
        
        crypto = CryptoService()
        
        # 10KB of data
        original = "x" * 10000
        encrypted = crypto.encrypt(original)
        decrypted = crypto.decrypt(encrypted)
        
        assert decrypted == original


class TestGenerateMasterKey:
    """Tests for key generation utility."""
    
    def test_generate_key_correct_length(self):
        """Test generated key has correct length."""
        from src.common.crypto import generate_master_key
        
        key = generate_master_key()
        decoded = base64.b64decode(key)
        
        assert len(decoded) == 32
    
    def test_generate_key_unique(self):
        """Test generated keys are unique."""
        from src.common.crypto import generate_master_key
        
        keys = [generate_master_key() for _ in range(100)]
        
        # All should be unique
        assert len(set(keys)) == 100


class TestEncryptedData:
    """Tests for EncryptedData class."""
    
    def test_to_from_base64(self):
        """Test base64 serialization roundtrip."""
        from src.common.crypto import EncryptedData
        
        original = EncryptedData(
            iv=b"123456789012",  # 12 bytes
            ciphertext=b"encrypted data here",
            tag=b"1234567890123456",  # 16 bytes
        )
        
        encoded = original.to_base64()
        decoded = EncryptedData.from_base64(encoded)
        
        assert decoded.iv == original.iv
        assert decoded.ciphertext == original.ciphertext
        assert decoded.tag == original.tag
    
    def test_invalid_base64_fails(self):
        """Test that invalid base64 raises error."""
        from src.common.crypto import EncryptedData
        from src.common.exceptions import SecurityError
        
        with pytest.raises(SecurityError):
            EncryptedData.from_base64("not valid base64!!!")
    
    def test_too_short_data_fails(self):
        """Test that too-short data raises error."""
        from src.common.crypto import EncryptedData
        from src.common.exceptions import SecurityError
        
        # Less than IV + TAG minimum
        short = base64.b64encode(b"short").decode()
        
        with pytest.raises(SecurityError):
            EncryptedData.from_base64(short)
