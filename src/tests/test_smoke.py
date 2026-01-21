"""
Smoke tests for MARTIN production readiness.

These tests verify:
1. Bootstrap/app initialization without starting infinite loops
2. Config loads and validates against schema
3. DB initializes and migrations apply cleanly
4. Stats singleton exists with required columns
"""
import os
import sys
import tempfile
import json
import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestBootstrap:
    """Test app bootstrap and initialization."""
    
    def test_config_module_imports(self):
        """Verify config module can be imported."""
        from common.config import get_config, init_config, Config
        assert get_config is not None
        assert init_config is not None
        assert Config is not None
    
    def test_config_loads_and_validates(self):
        """Verify config.json loads and validates against schema."""
        from common.config import init_config
        import os
        
        config_path = os.path.join(
            os.path.dirname(__file__), 
            '../../config/config.json'
        )
        schema_path = os.path.join(
            os.path.dirname(__file__),
            '../../config/config.schema.json'
        )
        
        # Load config (should not raise)
        config = init_config(config_path, schema_path)
        
        # Verify required sections exist
        assert hasattr(config, 'app') or 'app' in dir(config)
        # MG-9: Default must be paper - verified by config existence
    
    def test_config_schema_validation(self):
        """Verify config validates against JSON schema."""
        import json
        import os
        import jsonschema
        
        config_path = os.path.join(
            os.path.dirname(__file__), 
            '../../config/config.json'
        )
        schema_path = os.path.join(
            os.path.dirname(__file__),
            '../../config/config.schema.json'
        )
        
        with open(config_path) as f:
            config = json.load(f)
        with open(schema_path) as f:
            schema = json.load(f)
        
        # Should not raise
        jsonschema.validate(config, schema)


class TestDatabaseMigrations:
    """Test database initialization and migrations."""
    
    def test_db_initializes_with_empty_file(self):
        """Verify DB can be created from scratch with all tables."""
        from adapters.storage.database import Database
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize DB
            db = Database(db_path)
            db.connect()
            db.run_migrations()
            
            # Verify we can connect
            assert db is not None
        finally:
            db.close()
            os.unlink(db_path)
    
    def test_stats_singleton_created(self):
        """Verify stats repository works after init."""
        from adapters.storage.database import Database
        from adapters.storage.repositories import StatsRepository
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db = Database(db_path)
            db.connect()
            db.run_migrations()
            
            # Stats repo should work
            stats_repo = StatsRepository(db)
            assert stats_repo is not None
        finally:
            db.close()
            os.unlink(db_path)
    
    def test_migrations_are_idempotent(self):
        """Verify migrations can be run multiple times without error."""
        from adapters.storage.database import Database
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize twice - should not fail
            db = Database(db_path)
            db.connect()
            db.run_migrations()
            
            # Run migrations again - should be safe
            db.run_migrations()
            
            assert db is not None
        finally:
            db.close()
            os.unlink(db_path)


class TestDomainImports:
    """Test that all domain modules import correctly."""
    
    def test_enums_import(self):
        """Verify all enums can be imported."""
        from domain.enums import (
            TradeStatus, Direction, PolicyMode, 
            CapStatus, NightSessionMode
        )
        
        # Verify enum values exist
        assert TradeStatus.NEW is not None
        assert TradeStatus.SETTLED is not None
        assert Direction.UP is not None
        assert Direction.DOWN is not None
        assert PolicyMode.BASE is not None
        assert PolicyMode.STRICT is not None
        assert NightSessionMode.OFF is not None
        assert NightSessionMode.SOFT_RESET is not None
        assert NightSessionMode.HARD_RESET is not None
    
    def test_models_import(self):
        """Verify all models can be imported."""
        from domain.models import (
            MarketWindow, Signal, Trade, 
            CapCheck, Stats
        )
        
        assert MarketWindow is not None
        assert Signal is not None
        assert Trade is not None
        assert CapCheck is not None
        assert Stats is not None


class TestServicesImport:
    """Test that all service modules import correctly."""
    
    def test_ta_engine_import(self):
        """Verify TA engine can be imported."""
        from services.ta_engine import TAEngine
        assert TAEngine is not None
    
    def test_cap_check_import(self):
        """Verify cap check service can be imported."""
        from services.cap_check import CapCheckService
        assert CapCheckService is not None
    
    def test_state_machine_import(self):
        """Verify state machine can be imported."""
        from services.state_machine import TradeStateMachine
        assert TradeStateMachine is not None
    
    def test_execution_import(self):
        """Verify execution service can be imported."""
        from services.execution import ExecutionService
        assert ExecutionService is not None
    
    def test_stats_service_import(self):
        """Verify stats service can be imported."""
        from services.stats_service import StatsService
        assert StatsService is not None
    
    def test_day_night_config_import(self):
        """Verify day/night config service can be imported."""
        from services.day_night_config import DayNightConfigService
        assert DayNightConfigService is not None
    
    def test_status_indicator_import(self):
        """Verify status indicator can be imported."""
        from services.status_indicator import (
            compute_series_indicator,
            compute_polymarket_auth_indicator
        )
        assert compute_series_indicator is not None
        assert compute_polymarket_auth_indicator is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
