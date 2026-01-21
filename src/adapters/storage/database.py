"""
SQLite database connection and migration management.

Handles database initialization, connection pooling, and schema migrations.
"""

import sqlite3
from pathlib import Path
from typing import Any

from src.common.logging import get_logger
from src.common.exceptions import StorageError

logger = get_logger(__name__)


# Migration scripts in order
MIGRATIONS = [
    # Migration 1: Create base tables
    """
    -- market_windows table
    CREATE TABLE IF NOT EXISTS market_windows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        condition_id TEXT NOT NULL,
        up_token_id TEXT NOT NULL,
        down_token_id TEXT NOT NULL,
        start_ts INTEGER NOT NULL,
        end_ts INTEGER NOT NULL,
        outcome TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS idx_market_windows_asset ON market_windows(asset);
    CREATE INDEX IF NOT EXISTS idx_market_windows_start_ts ON market_windows(start_ts);
    CREATE INDEX IF NOT EXISTS idx_market_windows_end_ts ON market_windows(end_ts);
    CREATE INDEX IF NOT EXISTS idx_market_windows_slug ON market_windows(slug);
    
    -- signals table
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        window_id INTEGER NOT NULL,
        direction TEXT NOT NULL,
        signal_ts INTEGER NOT NULL,
        confirm_ts INTEGER NOT NULL,
        quality REAL NOT NULL,
        quality_breakdown TEXT,
        anchor_bar_ts INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (window_id) REFERENCES market_windows(id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_signals_window_id ON signals(window_id);
    CREATE INDEX IF NOT EXISTS idx_signals_signal_ts ON signals(signal_ts);
    
    -- trades table
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        window_id INTEGER NOT NULL,
        signal_id INTEGER,
        status TEXT NOT NULL DEFAULT 'NEW',
        time_mode TEXT,
        policy_mode TEXT NOT NULL DEFAULT 'BASE',
        decision TEXT NOT NULL DEFAULT 'PENDING',
        cancel_reason TEXT,
        token_id TEXT,
        order_id TEXT,
        fill_status TEXT NOT NULL DEFAULT 'PENDING',
        fill_price REAL,
        stake_amount REAL NOT NULL DEFAULT 0,
        pnl REAL,
        is_win INTEGER,
        trade_level_streak INTEGER NOT NULL DEFAULT 0,
        night_streak INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (window_id) REFERENCES market_windows(id),
        FOREIGN KEY (signal_id) REFERENCES signals(id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_trades_window_id ON trades(window_id);
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    CREATE INDEX IF NOT EXISTS idx_trades_decision ON trades(decision);
    CREATE INDEX IF NOT EXISTS idx_trades_fill_status ON trades(fill_status);
    CREATE INDEX IF NOT EXISTS idx_trades_time_mode ON trades(time_mode);
    CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at);
    
    -- cap_checks table
    CREATE TABLE IF NOT EXISTS cap_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL,
        token_id TEXT NOT NULL,
        confirm_ts INTEGER NOT NULL,
        end_ts INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        consecutive_ticks INTEGER NOT NULL DEFAULT 0,
        first_pass_ts INTEGER,
        price_at_pass REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (trade_id) REFERENCES trades(id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_cap_checks_trade_id ON cap_checks(trade_id);
    CREATE INDEX IF NOT EXISTS idx_cap_checks_status ON cap_checks(status);
    
    -- stats table (singleton)
    CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        trade_level_streak INTEGER NOT NULL DEFAULT 0,
        night_streak INTEGER NOT NULL DEFAULT 0,
        policy_mode TEXT NOT NULL DEFAULT 'BASE',
        total_trades INTEGER NOT NULL DEFAULT 0,
        total_wins INTEGER NOT NULL DEFAULT 0,
        total_losses INTEGER NOT NULL DEFAULT 0,
        last_strict_day_threshold REAL,
        last_strict_night_threshold REAL,
        last_quantile_update_ts INTEGER,
        is_paused INTEGER NOT NULL DEFAULT 0,
        day_only INTEGER NOT NULL DEFAULT 0,
        night_only INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Initialize stats singleton
    INSERT OR IGNORE INTO stats (id) VALUES (1);
    
    -- settings table for runtime config overrides
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- migrations tracking
    CREATE TABLE IF NOT EXISTS migrations (
        id INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
]


class Database:
    """
    SQLite database manager.
    
    Handles connection pooling, transactions, and migrations.
    """
    
    def __init__(self, dsn: str):
        """
        Initialize database connection.
        
        Args:
            dsn: Database connection string (e.g., "sqlite:///data/martin.db")
        """
        # Extract path from DSN
        if dsn.startswith("sqlite:///"):
            self._db_path = dsn[10:]  # Remove "sqlite:///"
        else:
            self._db_path = dsn
        
        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._conn: sqlite3.Connection | None = None
    
    def connect(self) -> sqlite3.Connection:
        """
        Get database connection.
        
        Returns:
            sqlite3.Connection: Database connection
        """
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn
    
    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        Execute SQL statement.
        
        Args:
            sql: SQL statement
            params: Query parameters
            
        Returns:
            sqlite3.Cursor: Cursor with results
        """
        conn = self.connect()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Database error", error=str(e), sql=sql[:100])
            raise StorageError(f"Database error: {e}")
    
    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """
        Execute SQL statement with multiple parameter sets.
        
        Args:
            sql: SQL statement
            params_list: List of parameter tuples
            
        Returns:
            sqlite3.Cursor: Cursor with results
        """
        conn = self.connect()
        try:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Database error", error=str(e), sql=sql[:100])
            raise StorageError(f"Database error: {e}")
    
    def executescript(self, sql: str) -> None:
        """
        Execute multiple SQL statements.
        
        Args:
            sql: SQL script
        """
        conn = self.connect()
        try:
            conn.executescript(sql)
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Database script error", error=str(e))
            raise StorageError(f"Database script error: {e}")
    
    def fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """
        Execute query and fetch one row.
        
        Args:
            sql: SQL query
            params: Query parameters
            
        Returns:
            Row as dictionary or None
        """
        conn = self.connect()
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """
        Execute query and fetch all rows.
        
        Args:
            sql: SQL query
            params: Query parameters
            
        Returns:
            List of rows as dictionaries
        """
        conn = self.connect()
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def run_migrations(self) -> None:
        """Apply pending database migrations."""
        conn = self.connect()
        
        # Check which migrations have been applied
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='migrations'"
            )
            has_migrations_table = cursor.fetchone() is not None
        except sqlite3.Error:
            has_migrations_table = False
        
        applied_migrations: set[int] = set()
        if has_migrations_table:
            cursor = conn.execute("SELECT id FROM migrations")
            applied_migrations = {row[0] for row in cursor.fetchall()}
        
        # Apply pending migrations
        for i, migration in enumerate(MIGRATIONS, start=1):
            if i not in applied_migrations:
                logger.info("Applying migration", migration_id=i)
                try:
                    conn.executescript(migration)
                    conn.execute("INSERT INTO migrations (id) VALUES (?)", (i,))
                    conn.commit()
                    logger.info("Migration applied successfully", migration_id=i)
                except sqlite3.Error as e:
                    conn.rollback()
                    logger.error("Migration failed", migration_id=i, error=str(e))
                    raise StorageError(f"Migration {i} failed: {e}")


# Global database instance
_database: Database | None = None


def get_database() -> Database:
    """
    Get the global database instance.
    
    Returns:
        Database: The database instance
        
    Raises:
        StorageError: If database has not been initialized
    """
    global _database
    if _database is None:
        raise StorageError("Database not initialized. Call init_database() first.")
    return _database


def init_database(dsn: str) -> Database:
    """
    Initialize the global database.
    
    Args:
        dsn: Database connection string
        
    Returns:
        Database: The initialized database instance
    """
    global _database
    _database = Database(dsn)
    _database.run_migrations()
    return _database
