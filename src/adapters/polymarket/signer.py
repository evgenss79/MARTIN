"""
Wallet Signer for MARTIN.

Implements EIP-712 signing for Polymarket CLOB orders.
Supports wallet-based authentication using private key.

SECURITY NOTE: Private key must NEVER be in code. 
It must be provided via environment variable.
"""

import os
import hashlib
import hmac
import time
from typing import Any
from dataclasses import dataclass

from src.common.logging import get_logger
from src.common.exceptions import TradeError

logger = get_logger(__name__)


# Try to import eth libraries, but don't fail if not available
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct, encode_typed_data
    ETH_AVAILABLE = True
except ImportError:
    ETH_AVAILABLE = False
    Account = None


@dataclass
class OrderData:
    """
    Order data structure for Polymarket CLOB.
    
    Attributes:
        token_id: Token ID to trade
        side: BUY or SELL
        price: Order price (0.0 to 1.0)
        size: Order size in contracts
        nonce: Unique order nonce
        expiration: Order expiration timestamp
    """
    token_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    nonce: int
    expiration: int
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        return {
            "tokenID": self.token_id,
            "side": self.side,
            "price": str(self.price),
            "size": str(self.size),
            "nonce": self.nonce,
            "expiration": self.expiration,
        }


class WalletSigner:
    """
    Wallet-based signer for Polymarket CLOB orders.
    
    Uses Ethereum account signing for order authentication.
    Compatible with MetaMask-style wallets via private key.
    
    Usage:
        1. User exports private key from MetaMask
        2. Private key is stored in POLYMARKET_PRIVATE_KEY env var
        3. Signer uses key to sign orders
        
    Security:
        - Private key is NEVER logged
        - Private key is NEVER stored in code or config files
        - Only read from environment variable
    """
    
    # Polymarket CLOB chain ID (Polygon)
    CHAIN_ID = 137
    
    # CLOB contract addresses (Polygon mainnet)
    CLOB_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    
    def __init__(
        self,
        private_key: str | None = None,
        chain_id: int = 137,
    ):
        """
        Initialize wallet signer.
        
        Args:
            private_key: Ethereum private key (hex string, with or without 0x prefix)
                        If None, reads from POLYMARKET_PRIVATE_KEY env var
            chain_id: Chain ID (default: 137 for Polygon)
            
        Raises:
            TradeError: If eth libraries not available or key not provided
        """
        if not ETH_AVAILABLE:
            raise TradeError(
                "eth-account library not installed. "
                "Install with: pip install eth-account"
            )
        
        # Get private key from env if not provided
        if private_key is None:
            private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        
        if not private_key:
            raise TradeError(
                "Wallet private key not provided. "
                "Set POLYMARKET_PRIVATE_KEY environment variable."
            )
        
        # Normalize key format
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        
        self._chain_id = chain_id
        self._account = Account.from_key(private_key)
        self._address = self._account.address
        
        logger.info(
            "Wallet signer initialized",
            address=self._address,
            chain_id=chain_id,
        )
    
    @property
    def address(self) -> str:
        """Get wallet address."""
        return self._address
    
    def generate_nonce(self) -> int:
        """Generate unique order nonce."""
        return int(time.time() * 1000)
    
    def sign_order(self, order: OrderData) -> str:
        """
        Sign an order for Polymarket CLOB.
        
        Uses EIP-712 typed data signing.
        
        Args:
            order: Order data to sign
            
        Returns:
            Hex-encoded signature
        """
        # EIP-712 typed data for Polymarket CLOB order
        domain = {
            "name": "Polymarket CTF Exchange",
            "version": "1",
            "chainId": self._chain_id,
            "verifyingContract": self.CLOB_EXCHANGE_ADDRESS,
        }
        
        types = {
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ]
        }
        
        # Calculate amounts based on price and size
        # For BUY: makerAmount = size * price (USDC), takerAmount = size (contracts)
        # For SELL: makerAmount = size (contracts), takerAmount = size * price (USDC)
        if order.side == "BUY":
            maker_amount = int(order.size * order.price * 1e6)  # USDC has 6 decimals
            taker_amount = int(order.size * 1e6)
            side = 0
        else:
            maker_amount = int(order.size * 1e6)
            taker_amount = int(order.size * order.price * 1e6)
            side = 1
        
        message = {
            "salt": order.nonce,
            "maker": self._address,
            "signer": self._address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(order.token_id, 16) if order.token_id.startswith("0x") else int(order.token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": order.expiration,
            "nonce": order.nonce,
            "feeRateBps": 0,
            "side": side,
            "signatureType": 2,  # EIP-712
        }
        
        try:
            # Sign the typed data
            signed = self._account.sign_typed_data(domain, types, message)
            signature = signed.signature.hex()
            
            logger.debug(
                "Order signed",
                token_id=order.token_id[:16] + "...",
                side=order.side,
                price=order.price,
            )
            
            return signature
            
        except Exception as e:
            logger.error("Failed to sign order", error=str(e))
            raise TradeError(f"Order signing failed: {e}")
    
    def sign_message(self, message: str) -> str:
        """
        Sign a plain text message.
        
        Used for API authentication.
        
        Args:
            message: Message to sign
            
        Returns:
            Hex-encoded signature
        """
        msg = encode_defunct(text=message)
        signed = self._account.sign_message(msg)
        return signed.signature.hex()
    
    def generate_auth_headers(self, timestamp: int | None = None) -> dict[str, str]:
        """
        Generate authentication headers for CLOB API.
        
        Args:
            timestamp: Optional timestamp (uses current time if None)
            
        Returns:
            Dict of headers to include in API requests
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        # Sign the timestamp
        message = f"Polymarket Login\nTimestamp: {timestamp}"
        signature = self.sign_message(message)
        
        return {
            "POLY_ADDRESS": self._address,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_NONCE": str(self.generate_nonce()),
        }


class ApiKeySigner:
    """
    API key-based signer for Polymarket CLOB.
    
    Alternative to wallet signing when using API keys.
    Uses HMAC-SHA256 for request signing.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
    ):
        """
        Initialize API key signer.
        
        Args:
            api_key: Polymarket API key
            api_secret: Polymarket API secret
            passphrase: Polymarket passphrase
        """
        # Read from environment if not provided
        self._api_key = api_key or os.environ.get("POLYMARKET_API_KEY")
        self._api_secret = api_secret or os.environ.get("POLYMARKET_API_SECRET")
        self._passphrase = passphrase or os.environ.get("POLYMARKET_PASSPHRASE")
        
        if not all([self._api_key, self._api_secret, self._passphrase]):
            raise TradeError(
                "API credentials not provided. "
                "Set POLYMARKET_API_KEY, POLYMARKET_API_SECRET, and POLYMARKET_PASSPHRASE."
            )
        
        logger.info("API key signer initialized")
    
    @property
    def api_key(self) -> str:
        """Get API key."""
        return self._api_key
    
    def sign_request(
        self,
        method: str,
        path: str,
        body: str = "",
        timestamp: int | None = None,
    ) -> str:
        """
        Sign an API request.
        
        Args:
            method: HTTP method
            path: Request path
            body: Request body (JSON string)
            timestamp: Request timestamp
            
        Returns:
            HMAC signature
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        
        return signature
    
    def generate_auth_headers(
        self,
        method: str,
        path: str,
        body: str = "",
        timestamp: int | None = None,
    ) -> dict[str, str]:
        """
        Generate authentication headers for API request.
        
        Args:
            method: HTTP method
            path: Request path
            body: Request body
            timestamp: Request timestamp
            
        Returns:
            Dict of headers
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        signature = self.sign_request(method, path, body, timestamp)
        
        return {
            "POLY_API_KEY": self._api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_PASSPHRASE": self._passphrase,
        }
