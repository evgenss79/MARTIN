"""
Tests for secure vault module.

Tests encrypted storage and session management.
"""

import os
import time
import pytest
import base64
import secrets
import tempfile

# Store original env
_original_env = {}


def setup_module():
    """Save original environment."""
    for key in ["MASTER_ENCRYPTION_KEY", "POLYMARKET_PRIVATE_KEY", 
                "POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_PASSPHRASE"]:
        _original_env[key] = os.environ.get(key)


def teardown_module():
    """Restore original environment."""
    for key, value in _original_env.items():
        if value:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]


def _generate_test_key() -> str:
    """Generate a valid test master key."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


def _clear_env():
    """Clear relevant env vars."""
    for key in ["MASTER_ENCRYPTION_KEY", "POLYMARKET_PRIVATE_KEY",
                "POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_PASSPHRASE"]:
        if key in os.environ:
            del os.environ[key]


class TestSecureVault:
    """Tests for SecureVault class."""
    
    def test_vault_without_master_key(self):
        """Test vault initialization without master key."""
        _clear_env()
        
        from src.services.secure_vault import SecureVault
        
        vault = SecureVault()
        
        assert not vault.is_encryption_available
        assert not vault.has_valid_session
    
    def test_vault_with_master_key(self):
        """Test vault initialization with master key."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        
        vault = SecureVault()
        
        assert vault.is_encryption_available
        assert not vault.has_valid_session
    
    def test_store_and_retrieve_private_key(self):
        """Test encrypted storage of private key."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        
        vault = SecureVault()
        
        # Store a private key
        test_key = "1234567890abcdef" * 4  # 64 hex chars
        vault.store_private_key(test_key)
        
        # Retrieve it
        retrieved = vault.get_private_key()
        
        assert retrieved == "0x" + test_key
    
    def test_store_private_key_with_0x_prefix(self):
        """Test that 0x prefix is handled correctly."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        
        vault = SecureVault()
        
        test_key = "0x" + "abcdef1234567890" * 4
        vault.store_private_key(test_key)
        
        retrieved = vault.get_private_key()
        assert retrieved == test_key
    
    def test_store_invalid_private_key_fails(self):
        """Test that invalid private key is rejected."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        from src.common.exceptions import SecurityError
        
        vault = SecureVault()
        
        with pytest.raises(SecurityError):
            vault.store_private_key("too short")
        
        with pytest.raises(SecurityError):
            vault.store_private_key("not hex characters!" * 4)
    
    def test_store_without_encryption_fails(self):
        """Test that storing without encryption raises error."""
        _clear_env()
        
        from src.services.secure_vault import SecureVault
        from src.common.exceptions import SecurityError
        
        vault = SecureVault()
        
        with pytest.raises(SecurityError):
            vault.store_private_key("a" * 64)


class TestAuthSession:
    """Tests for AuthSession management."""
    
    def test_create_session(self):
        """Test session creation."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        
        vault = SecureVault(session_expiry_hours=24)
        
        session = vault.create_session(
            wallet_address="0x1234567890abcdef1234567890abcdef12345678",
            auth_type="wallet",
        )
        
        assert session.wallet_address == "0x1234567890abcdef1234567890abcdef12345678"
        assert session.auth_type == "wallet"
        assert session.is_valid
        assert not session.is_expired
        assert vault.has_valid_session
    
    def test_session_expiry(self):
        """Test session expiration."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault, AuthSession
        
        # Create a session that's already expired
        now = time.time()
        expired_session = AuthSession(
            wallet_address="0x123",
            auth_type="wallet",
            created_at=now - 7200,
            expires_at=now - 3600,  # Expired 1 hour ago
            session_id="test123",
        )
        
        assert expired_session.is_expired
        assert not expired_session.is_valid
    
    def test_session_time_remaining(self):
        """Test time remaining calculation."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import AuthSession
        from datetime import timedelta
        
        now = time.time()
        session = AuthSession(
            wallet_address="0x123",
            auth_type="wallet",
            created_at=now,
            expires_at=now + 3600,  # Expires in 1 hour
            session_id="test123",
        )
        
        remaining = session.time_remaining
        
        # Should be approximately 1 hour
        assert remaining > timedelta(minutes=59)
        assert remaining <= timedelta(hours=1)
    
    def test_invalidate_session(self):
        """Test session invalidation."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        
        vault = SecureVault()
        vault.create_session(
            wallet_address="0x123",
            auth_type="wallet",
        )
        
        assert vault.has_valid_session
        
        vault.invalidate_session()
        
        assert not vault.has_valid_session
        assert vault.current_session is None
    
    def test_session_to_dict_from_dict(self):
        """Test session serialization roundtrip."""
        from src.services.secure_vault import AuthSession
        
        now = time.time()
        original = AuthSession(
            wallet_address="0x123",
            auth_type="wallet",
            created_at=now,
            expires_at=now + 3600,
            session_id="test123",
            cached_headers={"key": "value"},
        )
        
        data = original.to_dict()
        restored = AuthSession.from_dict(data)
        
        assert restored.wallet_address == original.wallet_address
        assert restored.auth_type == original.auth_type
        assert restored.session_id == original.session_id
        assert restored.cached_headers == original.cached_headers


class TestSecureAuthStatus:
    """Tests for check_secure_auth_status function."""
    
    def test_paper_mode_not_authorized(self):
        """Test that paper mode returns not authorized."""
        _clear_env()
        
        from src.services.secure_vault import check_secure_auth_status
        
        is_auth, msg, details = check_secure_auth_status("paper")
        
        assert not is_auth
        assert "paper" in msg.lower()
        assert details["execution_mode"] == "paper"
    
    def test_live_mode_with_wallet_key(self):
        """Test live mode with wallet key is authorized."""
        _clear_env()
        os.environ["POLYMARKET_PRIVATE_KEY"] = "a" * 64
        
        from src.services.secure_vault import check_secure_auth_status
        
        is_auth, msg, details = check_secure_auth_status("live")
        
        assert is_auth
        assert "wallet" in msg.lower()
        assert details["auth_type"] == "wallet"
    
    def test_live_mode_with_api_keys(self):
        """Test live mode with API keys is authorized."""
        _clear_env()
        os.environ["POLYMARKET_API_KEY"] = "key"
        os.environ["POLYMARKET_API_SECRET"] = "secret"
        os.environ["POLYMARKET_PASSPHRASE"] = "pass"
        
        from src.services.secure_vault import check_secure_auth_status
        
        is_auth, msg, details = check_secure_auth_status("live")
        
        assert is_auth
        assert "api" in msg.lower()
        assert details["auth_type"] == "api_key"
    
    def test_live_mode_missing_credentials(self):
        """Test live mode without credentials is not authorized."""
        _clear_env()
        
        from src.services.secure_vault import check_secure_auth_status
        
        is_auth, msg, details = check_secure_auth_status("live")
        
        assert not is_auth
        assert "credential" in msg.lower() or "not authorized" in msg.lower()


class TestVaultPersistence:
    """Tests for vault persistence."""
    
    def test_save_and_load_vault(self):
        """Test vault save and load."""
        _clear_env()
        os.environ["MASTER_ENCRYPTION_KEY"] = _generate_test_key()
        
        from src.services.secure_vault import SecureVault
        
        # Create vault with temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            vault_path = f.name
        
        try:
            # Create and populate vault
            vault1 = SecureVault(vault_path=vault_path)
            vault1.store_private_key("abcdef1234567890" * 4)
            vault1.create_session(
                wallet_address="0xtest",
                auth_type="wallet",
            )
            
            # Create new vault instance and load
            vault2 = SecureVault(vault_path=vault_path)
            vault2.load()
            
            # Should have same data
            assert vault2.get_private_key() == "0x" + "abcdef1234567890" * 4
            assert vault2.has_valid_session
            assert vault2.current_session.wallet_address == "0xtest"
            
        finally:
            if os.path.exists(vault_path):
                os.unlink(vault_path)
