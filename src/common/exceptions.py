"""
Custom exceptions for MARTIN.

Provides specific exception types for different error categories.
"""


class MartinError(Exception):
    """Base exception for MARTIN errors."""
    pass


class ConfigError(MartinError):
    """Configuration-related errors."""
    pass


class APIError(MartinError):
    """External API errors."""
    
    def __init__(self, message: str, status_code: int | None = None, response: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class RateLimitError(APIError):
    """Rate limit exceeded error (HTTP 429)."""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class TimeoutError(APIError):
    """Request timeout error."""
    pass


class DataError(MartinError):
    """Data processing errors."""
    pass


class TAError(MartinError):
    """Technical analysis errors."""
    pass


class TradeError(MartinError):
    """Trading-related errors."""
    pass


class StorageError(MartinError):
    """Database/storage errors."""
    pass


class TelegramError(MartinError):
    """Telegram bot errors."""
    pass
