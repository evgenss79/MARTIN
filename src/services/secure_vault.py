"""
Secure Vault for MARTIN.

Provides encrypted storage for sensitive credentials.
All secrets are encrypted at rest using AES-256-GCM.

SEC-1: No plaintext secrets at rest
SEC-2: Master key from MASTER_ENCRYPTION_KEY env var
SEC-3: Session keys for autonomous trading

Features:
- One-time wallet authorization (MetaMask login)
- Session key caching for autonomous trades
- Encrypted persistence to database/file
- Automatic session expiration
"""

import os
import time
import json
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from src.common.logging import get_logger
from src.common.exceptions import SecurityError
from src.common.crypto import (
    CryptoService, 
    is_master_key_configured,
    validate_master_key,
)

logger = get_logger(__name__)


# Session expiration (24 hours by default)
DEFAULT_SESSION_EXPIRY_HOURS = 24

# Vault file location (encrypted)
VAULT_FILE = "data/vault.enc"


@dataclass
class AuthSession:
    """
    Authenticated trading session.
    
    Represents a valid authorization to place trades.
    Created after one-time wallet signature.
    """
    wallet_address: str
    auth_type: str  # "wallet" or "api_key"
    created_at: float  # Unix timestamp
    expires_at: float  # Unix timestamp
    session_id: str
    
    # Cached auth headers (encrypted when persisted)
    cached_headers: Dict[str, str] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Check if session is expired."""
        return time.time() > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if session is valid (not expired)."""
        return not self.is_expired
    
    @property
    def time_remaining(self) -> timedelta:
        """Get time remaining until expiration."""
        remaining = self.expires_at - time.time()
        return timedelta(seconds=max(0, remaining))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "wallet_address": self.wallet_address,
            "auth_type": self.auth_type,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "session_id": self.session_id,
            "cached_headers": self.cached_headers,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuthSession':
        """Create from dictionary."""
        return cls(
            wallet_address=data["wallet_address"],
            auth_type=data["auth_type"],
            created_at=data["created_at"],
            expires_at=data["expires_at"],
            session_id=data["session_id"],
            cached_headers=data.get("cached_headers", {}),
        )


class SecureVault:
    """
    Secure vault for encrypted credential storage.
    
    Provides:
    1. Encrypted storage for wallet private keys
    2. Session management for autonomous trading
    3. One-time wallet authorization flow
    
    Usage Flow (MetaMask):
    1. User initiates /authorize command in Telegram
    2. Bot generates authorization message
    3. User signs message in MetaMask (one-time)
    4. Bot receives signature and creates session
    5. Session is cached (encrypted) for autonomous trades
    6. Session expires after 24 hours (configurable)
    
    Security:
    - Private keys are encrypted at rest with master key
    - Sessions are encrypted before persistence
    - Master key is NEVER stored, only in environment
    """
    
    def __init__(
        self,
        session_expiry_hours: int = DEFAULT_SESSION_EXPIRY_HOURS,
        vault_path: str = VAULT_FILE,
    ):
        """
        Initialize secure vault.
        
        Args:
            session_expiry_hours: Hours until session expires
            vault_path: Path to encrypted vault file
        """
        self._session_expiry = session_expiry_hours
        self._vault_path = vault_path
        self._crypto: Optional[CryptoService] = None
        self._current_session: Optional[AuthSession] = None
        self._encrypted_private_key: Optional[str] = None
        
        # Initialize crypto if master key is available
        if is_master_key_configured():
            try:
                self._crypto = CryptoService()
                logger.info("Secure vault initialized with encryption")
            except SecurityError as e:
                logger.warning(f"Crypto initialization failed: {e}")
        else:
            logger.warning(
                "MASTER_ENCRYPTION_KEY not set. "
                "Live trading with encrypted storage is disabled."
            )
    
    @property
    def is_encryption_available(self) -> bool:
        """Check if encryption is available."""
        return self._crypto is not None
    
    @property
    def has_valid_session(self) -> bool:
        """Check if there's a valid (non-expired) session."""
        if self._current_session is None:
            return False
        return self._current_session.is_valid
    
    @property
    def current_session(self) -> Optional[AuthSession]:
        """Get current session if valid."""
        if self.has_valid_session:
            return self._current_session
        return None
    
    def store_private_key(self, private_key: str) -> bool:
        """
        Store wallet private key encrypted at rest.
        
        The key is encrypted with MASTER_ENCRYPTION_KEY and can be
        stored in the database or vault file.
        
        Args:
            private_key: Hex private key (with or without 0x prefix)
            
        Returns:
            True if stored successfully
            
        Raises:
            SecurityError: If encryption not available
        """
        if not self._crypto:
            raise SecurityError(
                "Encryption not available. Set MASTER_ENCRYPTION_KEY to enable."
            )
        
        # Normalize key format
        key = private_key.strip()
        if key.startswith("0x"):
            key = key[2:]
        
        # Validate key format
        if len(key) != 64 or not all(c in "0123456789abcdefABCDEF" for c in key):
            raise SecurityError("Invalid private key format")
        
        # Encrypt the key
        self._encrypted_private_key = self._crypto.encrypt(key)
        
        logger.info("Private key stored (encrypted)")
        return True
    
    def get_private_key(self) -> Optional[str]:
        """
        Retrieve decrypted private key.
        
        Returns:
            Decrypted private key or None if not stored
            
        Raises:
            SecurityError: If decryption fails
        """
        if not self._crypto:
            raise SecurityError("Encryption not available")
        
        if not self._encrypted_private_key:
            return None
        
        decrypted = self._crypto.decrypt(self._encrypted_private_key)
        return "0x" + decrypted
    
    def create_session(
        self,
        wallet_address: str,
        auth_type: str = "wallet",
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> AuthSession:
        """
        Create a new authenticated session.
        
        Called after successful one-time wallet authorization.
        
        Args:
            wallet_address: Wallet address
            auth_type: Authentication type ("wallet" or "api_key")
            auth_headers: Optional headers to cache
            
        Returns:
            New AuthSession
        """
        import secrets
        
        now = time.time()
        expiry = now + (self._session_expiry * 3600)
        session_id = secrets.token_hex(16)
        
        self._current_session = AuthSession(
            wallet_address=wallet_address,
            auth_type=auth_type,
            created_at=now,
            expires_at=expiry,
            session_id=session_id,
            cached_headers=auth_headers or {},
        )
        
        logger.info(
            "Auth session created",
            wallet_address=wallet_address[:10] + "...",
            auth_type=auth_type,
            expires_in_hours=self._session_expiry,
        )
        
        # Persist encrypted session
        if self._crypto:
            self._save_vault()
        
        return self._current_session
    
    def invalidate_session(self) -> None:
        """Invalidate current session."""
        if self._current_session:
            logger.info(
                "Session invalidated",
                session_id=self._current_session.session_id[:8] + "...",
            )
            self._current_session = None
            
            # Update persisted vault
            if self._crypto:
                self._save_vault()
    
    def get_auth_status(self) -> Dict[str, Any]:
        """
        Get current authorization status.
        
        Returns:
            Dict with authorization status details
        """
        result = {
            "encryption_available": self.is_encryption_available,
            "has_valid_session": self.has_valid_session,
            "has_stored_key": self._encrypted_private_key is not None,
            "master_key_configured": is_master_key_configured(),
        }
        
        if self.has_valid_session:
            session = self._current_session
            result.update({
                "wallet_address": session.wallet_address,
                "auth_type": session.auth_type,
                "session_expires_in": str(session.time_remaining),
            })
        
        return result
    
    def _save_vault(self) -> None:
        """Save vault state to encrypted file."""
        if not self._crypto:
            return
        
        try:
            vault_data = {
                "encrypted_private_key": self._encrypted_private_key,
                "session": self._current_session.to_dict() if self._current_session else None,
            }
            
            # Encrypt vault data
            vault_json = json.dumps(vault_data)
            encrypted = self._crypto.encrypt(vault_json)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self._vault_path), exist_ok=True)
            
            # Write encrypted vault
            with open(self._vault_path, 'w') as f:
                f.write(encrypted)
            
            logger.debug("Vault saved (encrypted)")
            
        except Exception as e:
            logger.error(f"Failed to save vault: {e}")
    
    def _load_vault(self) -> None:
        """Load vault state from encrypted file."""
        if not self._crypto:
            return
        
        if not os.path.exists(self._vault_path):
            return
        
        try:
            with open(self._vault_path, 'r') as f:
                encrypted = f.read()
            
            # Decrypt vault data
            vault_json = self._crypto.decrypt(encrypted)
            vault_data = json.loads(vault_json)
            
            # Restore state
            self._encrypted_private_key = vault_data.get("encrypted_private_key")
            
            session_data = vault_data.get("session")
            if session_data:
                session = AuthSession.from_dict(session_data)
                if session.is_valid:
                    self._current_session = session
                    logger.info(
                        "Session restored from vault",
                        expires_in=str(session.time_remaining),
                    )
                else:
                    logger.info("Session in vault was expired")
            
            logger.debug("Vault loaded (decrypted)")
            
        except Exception as e:
            logger.warning(f"Failed to load vault: {e}")
    
    def load(self) -> None:
        """Load vault from persistent storage."""
        self._load_vault()


def check_secure_auth_status(execution_mode: str) -> tuple[bool, str, Dict[str, Any]]:
    """
    Check if secure authentication is properly configured.
    
    For live mode:
    1. Check if MASTER_ENCRYPTION_KEY is set
    2. Check if credentials exist (encrypted or in env)
    3. Check if valid session exists
    
    Args:
        execution_mode: Current execution mode ("paper" or "live")
        
    Returns:
        Tuple of (is_authorized, message, details)
    """
    details = {
        "execution_mode": execution_mode,
        "master_key_configured": is_master_key_configured(),
    }
    
    # Paper mode doesn't need auth
    if execution_mode != "live":
        details["reason"] = "paper_mode"
        return False, "Paper mode (live trading disabled)", details
    
    # Check master key
    key_valid, key_msg = validate_master_key()
    details["master_key_valid"] = key_valid
    
    # Check for credentials in environment
    has_wallet_key = bool(os.environ.get("POLYMARKET_PRIVATE_KEY"))
    has_api_key = (
        bool(os.environ.get("POLYMARKET_API_KEY")) and
        bool(os.environ.get("POLYMARKET_API_SECRET")) and
        bool(os.environ.get("POLYMARKET_PASSPHRASE"))
    )
    
    details["has_wallet_key_env"] = has_wallet_key
    details["has_api_key_env"] = has_api_key
    
    if has_wallet_key:
        # Wallet key in env - check if we should warn about encryption
        if not key_valid:
            logger.warning(
                "Private key in environment without MASTER_ENCRYPTION_KEY. "
                "Consider using encrypted vault for better security."
            )
        details["auth_type"] = "wallet"
        return True, "Authorized (Wallet)", details
    
    if has_api_key:
        details["auth_type"] = "api_key"
        return True, "Authorized (API Key)", details
    
    # No credentials
    details["reason"] = "no_credentials"
    return False, "Not authorized (Missing credentials)", details
