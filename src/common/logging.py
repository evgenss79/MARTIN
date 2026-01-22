"""
Structured logging for MARTIN.

Provides JSON-formatted logging with context for all operations.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


# Standard record attributes to exclude from extra fields
_STANDARD_ATTRS = {
    "name", "msg", "args", "created", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs",
    "pathname", "process", "processName", "relativeCreated",
    "stack_info", "exc_info", "exc_text", "thread", "threadName",
    "taskName", "message"
}


class JsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Outputs log records as JSON objects with timestamp, level, message,
    and any additional context fields.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                log_obj[key] = value
        
        return json.dumps(log_obj, default=str)


class TextFormatter(logging.Formatter):
    """
    Key-value text formatter for structured logging.
    
    Outputs log records in key=value format for readability.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as key-value pairs."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        parts = [
            f"time={timestamp}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg=\"{record.getMessage()}\"",
        ]
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "taskName", "message"
            ):
                if isinstance(value, str):
                    parts.append(f'{key}="{value}"')
                else:
                    parts.append(f"{key}={value}")
        
        return " ".join(parts)


class ContextLogger:
    """
    Custom logger that supports structured logging with kwargs.
    
    Allows calling: logger.info("message", key=value, another=value)
    All kwargs are added to the log record's extra dict.
    """
    
    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None):
        """
        Initialize context logger.
        
        Args:
            logger: Underlying Python logger
            context: Default context to include in all messages
        """
        self._logger = logger
        self._context = context or {}
    
    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        """Internal log method that handles kwargs."""
        # Merge default context with provided kwargs
        extra = {**self._context, **kwargs}
        self._logger.log(level, msg, extra=extra)
    
    def debug(self, msg: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, msg, **kwargs)
    
    def info(self, msg: str, **kwargs: Any) -> None:
        """Log info message."""
        self._log(logging.INFO, msg, **kwargs)
    
    def warning(self, msg: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._log(logging.WARNING, msg, **kwargs)
    
    def error(self, msg: str, **kwargs: Any) -> None:
        """Log error message."""
        self._log(logging.ERROR, msg, **kwargs)
    
    def critical(self, msg: str, **kwargs: Any) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, msg, **kwargs)
    
    def exception(self, msg: str, **kwargs: Any) -> None:
        """Log exception with traceback."""
        extra = {**self._context, **kwargs}
        self._logger.exception(msg, extra=extra)


class ContextAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds context to all log messages.
    
    Allows adding persistent context fields that are included
    in every log message.
    """
    
    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Add context to log record."""
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(level: str = "INFO", format_type: str = "json") -> None:
    """
    Set up logging configuration.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        format_type: Output format ("json" or "text")
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create handler with appropriate formatter
    handler = logging.StreamHandler(sys.stdout)
    
    if format_type == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())
    
    root_logger.addHandler(handler)


def get_logger(name: str, **context: Any) -> ContextLogger:
    """
    Get a logger with optional context.
    
    Args:
        name: Logger name (usually __name__)
        **context: Additional context fields to include in all log messages
        
    Returns:
        ContextLogger: Logger with context support and kwargs for structured fields
    """
    logger = logging.getLogger(name)
    return ContextLogger(logger, context)
