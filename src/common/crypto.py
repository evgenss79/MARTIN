"""
Cryptographic utilities for MARTIN.

Implements AES-256-GCM encryption for secrets at rest.
Master key must be provided via MASTER_ENCRYPTION_KEY environment variable.

SEC-1: No plaintext secrets at rest
SEC-2: Master key handling via environment variable

SECURITY NOTES:
- Master key is 32 bytes (256 bits), base64 encoded in .env
- AES-256-GCM provides authenticated encryption
- Each encrypted value has unique IV (12 bytes)
- If MASTER_ENCRYPTION_KEY is missing, live mode MUST fail safely
"""

import os
import base64
import secrets
from dataclasses import dataclass
from typing import Optional

from src.common.logging import get_logger
from src.common.exceptions import SecurityError

logger = get_logger(__name__)


# Constants
KEY_SIZE = 32  # 256 bits
IV_SIZE = 12   # 96 bits for GCM
TAG_SIZE = 16  # 128 bits authentication tag


@dataclass
class EncryptedData:
    """
    Container for encrypted data.
    
    Format: base64(iv || ciphertext || tag)
    """
    iv: bytes
    ciphertext: bytes
    tag: bytes
    
    def to_base64(self) -> str:
        """Encode to base64 string for storage."""
        combined = self.iv + self.ciphertext + self.tag
        return base64.b64encode(combined).decode('utf-8')
    
    @classmethod
    def from_base64(cls, data: str) -> 'EncryptedData':
        """Decode from base64 string."""
        try:
            combined = base64.b64decode(data.encode('utf-8'))
            # Minimum: IV (12) + TAG (16) = 28 bytes, ciphertext can be empty
            if len(combined) < IV_SIZE + TAG_SIZE:
                raise SecurityError("Invalid encrypted data: too short")
            
            iv = combined[:IV_SIZE]
            tag = combined[-TAG_SIZE:]
            ciphertext = combined[IV_SIZE:-TAG_SIZE] if len(combined) > IV_SIZE + TAG_SIZE else b""
            
            return cls(iv=iv, ciphertext=ciphertext, tag=tag)
        except Exception as e:
            raise SecurityError(f"Failed to decode encrypted data: {e}")


class CryptoService:
    """
    Cryptographic service for encrypting/decrypting secrets.
    
    Uses AES-256-GCM for authenticated encryption.
    Master key must be set via MASTER_ENCRYPTION_KEY environment variable.
    
    Usage:
        crypto = CryptoService()  # Reads key from env
        encrypted = crypto.encrypt("my secret")
        decrypted = crypto.decrypt(encrypted)
    
    Security:
        - Master key is never logged
        - Original plaintext is never logged
        - Encryption uses unique random IV for each operation
    """
    
    def __init__(self, master_key: Optional[str] = None):
        """
        Initialize crypto service.
        
        Args:
            master_key: Base64-encoded 32-byte master key.
                       If None, reads from MASTER_ENCRYPTION_KEY env var.
                       
        Raises:
            SecurityError: If master key is missing or invalid
        """
        self._key = self._load_master_key(master_key)
        self._initialized = True
        logger.debug("Crypto service initialized")
    
    def _load_master_key(self, provided_key: Optional[str]) -> bytes:
        """
        Load and validate master encryption key.
        
        Args:
            provided_key: Key provided directly (for testing)
            
        Returns:
            Decoded 32-byte key
            
        Raises:
            SecurityError: If key is missing or invalid
        """
        key_b64 = provided_key or os.environ.get("MASTER_ENCRYPTION_KEY")
        
        if not key_b64:
            raise SecurityError(
                "MASTER_ENCRYPTION_KEY not set. "
                "Live mode requires encryption key for secure secret storage. "
                "Generate with: python -c \"import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())\""
            )
        
        try:
            key = base64.b64decode(key_b64.encode('utf-8'))
        except Exception as e:
            raise SecurityError(f"Invalid MASTER_ENCRYPTION_KEY format: {e}")
        
        if len(key) != KEY_SIZE:
            raise SecurityError(
                f"Invalid MASTER_ENCRYPTION_KEY length: {len(key)} bytes. "
                f"Expected {KEY_SIZE} bytes (256 bits)."
            )
        
        return key
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.
        
        Uses AES-256-GCM with random IV.
        
        Args:
            plaintext: String to encrypt
            
        Returns:
            Base64-encoded encrypted data (iv || ciphertext || tag)
            
        Raises:
            SecurityError: If encryption fails
        """
        if not self._initialized:
            raise SecurityError("Crypto service not initialized")
        
        try:
            # Import cryptography here to avoid hard dependency
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # Generate random IV
            iv = secrets.token_bytes(IV_SIZE)
            
            # Encrypt
            aesgcm = AESGCM(self._key)
            ciphertext_with_tag = aesgcm.encrypt(
                iv, 
                plaintext.encode('utf-8'), 
                None  # No additional authenticated data
            )
            
            # Split ciphertext and tag (GCM appends tag to ciphertext)
            ciphertext = ciphertext_with_tag[:-TAG_SIZE]
            tag = ciphertext_with_tag[-TAG_SIZE:]
            
            encrypted = EncryptedData(iv=iv, ciphertext=ciphertext, tag=tag)
            return encrypted.to_base64()
            
        except ImportError:
            raise SecurityError(
                "cryptography library not installed. "
                "Install with: pip install cryptography"
            )
        except Exception as e:
            raise SecurityError(f"Encryption failed: {e}")
    
    def decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            encrypted_data: Base64-encoded encrypted data
            
        Returns:
            Decrypted plaintext string
            
        Raises:
            SecurityError: If decryption fails (wrong key, tampered data, etc.)
        """
        if not self._initialized:
            raise SecurityError("Crypto service not initialized")
        
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # Parse encrypted data
            data = EncryptedData.from_base64(encrypted_data)
            
            # Decrypt
            aesgcm = AESGCM(self._key)
            ciphertext_with_tag = data.ciphertext + data.tag
            plaintext = aesgcm.decrypt(data.iv, ciphertext_with_tag, None)
            
            return plaintext.decode('utf-8')
            
        except ImportError:
            raise SecurityError(
                "cryptography library not installed. "
                "Install with: pip install cryptography"
            )
        except Exception as e:
            raise SecurityError(f"Decryption failed: {e}")


def generate_master_key() -> str:
    """
    Generate a new random master encryption key.
    
    Returns:
        Base64-encoded 32-byte key
    """
    key = secrets.token_bytes(KEY_SIZE)
    return base64.b64encode(key).decode('utf-8')


def is_master_key_configured() -> bool:
    """
    Check if master encryption key is configured.
    
    Returns:
        True if MASTER_ENCRYPTION_KEY env var is set
    """
    return bool(os.environ.get("MASTER_ENCRYPTION_KEY"))


def validate_master_key() -> tuple[bool, str]:
    """
    Validate the master encryption key configuration.
    
    Returns:
        Tuple of (is_valid, message)
    """
    key_b64 = os.environ.get("MASTER_ENCRYPTION_KEY")
    
    if not key_b64:
        return False, "MASTER_ENCRYPTION_KEY not set"
    
    try:
        key = base64.b64decode(key_b64.encode('utf-8'))
        if len(key) != KEY_SIZE:
            return False, f"Key length {len(key)} bytes, expected {KEY_SIZE}"
        return True, "Master key validated"
    except Exception as e:
        return False, f"Invalid key format: {e}"
