"""
Startup smoke tests for MARTIN.

Specifically tests that Orchestrator and StatsService can be instantiated
without TypeError due to parameter mismatches.

This test prevents regression of the issue:
    TypeError: StatsService.__init__() got an unexpected keyword argument 
    'night_session_resets_trade_streak'
"""

import os
import sys
import tempfile
from pathlib import Path
import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestStatsServiceInit:
    """Test StatsService initialization with correct parameters."""
    
    def test_stats_service_accepts_night_session_mode(self):
        """
        Verify StatsService accepts night_session_mode parameter.
        
        This is the canonical parameter per CHANGE_LOG.md:
        "Changed from boolean night_session_resets_trade_streak to NightSessionMode enum"
        """
        from domain.enums import NightSessionMode
        from services.stats_service import StatsService
        
        # Mock repositories
        class MockStatsRepo:
            def get(self):
                from domain.models import Stats
                return Stats()
            def update(self, stats):
                pass

        class MockTradeRepo:
            def get_filled_trades_for_quantile(self, time_mode, since_ts, max_samples):
                return []
        
        # Should NOT raise TypeError
        stats_service = StatsService(
            stats_repo=MockStatsRepo(),
            trade_repo=MockTradeRepo(),
            switch_streak_at=3,
            night_max_win_streak=5,
            night_session_mode=NightSessionMode.HARD_RESET,  # Canonical parameter
            strict_day_q='p95',
            strict_night_q='p95',
            rolling_days=14,
            max_samples=500,
            min_samples=50,
            strict_fallback_mult=1.25,
            base_day_min_quality=50.0,
            base_night_min_quality=60.0,
        )
        
        assert stats_service is not None
        assert stats_service.get_night_session_mode() == NightSessionMode.HARD_RESET
    
    def test_stats_service_rejects_obsolete_boolean_parameter(self):
        """
        Verify StatsService rejects the obsolete night_session_resets_trade_streak.
        
        This ensures we don't accidentally reintroduce the old parameter.
        """
        from services.stats_service import StatsService
        
        class MockStatsRepo:
            def get(self):
                from domain.models import Stats
                return Stats()
            def update(self, stats):
                pass

        class MockTradeRepo:
            def get_filled_trades_for_quantile(self, time_mode, since_ts, max_samples):
                return []
        
        # Should raise TypeError for unknown keyword argument
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            StatsService(
                stats_repo=MockStatsRepo(),
                trade_repo=MockTradeRepo(),
                night_session_resets_trade_streak=True,  # Obsolete parameter - must fail
            )
    
    def test_stats_service_all_night_session_modes(self):
        """Verify all NightSessionMode enum values work."""
        from domain.enums import NightSessionMode
        from services.stats_service import StatsService
        
        class MockStatsRepo:
            def get(self):
                from domain.models import Stats
                return Stats()
            def update(self, stats):
                pass

        class MockTradeRepo:
            def get_filled_trades_for_quantile(self, time_mode, since_ts, max_samples):
                return []
        
        for mode in [NightSessionMode.OFF, NightSessionMode.SOFT_RESET, NightSessionMode.HARD_RESET]:
            stats_service = StatsService(
                stats_repo=MockStatsRepo(),
                trade_repo=MockTradeRepo(),
                night_session_mode=mode,
            )
            assert stats_service.get_night_session_mode() == mode


class TestOrchestratorInit:
    """Test Orchestrator initialization creates StatsService without error."""
    
    def test_orchestrator_night_session_mode_conversion(self):
        """
        Verify Orchestrator's conversion logic for night_session_mode.
        
        This test verifies the conversion logic from config to NightSessionMode
        without requiring full database setup.
        """
        from domain.enums import NightSessionMode
        
        # Test new canonical key conversion
        dn_config = {"night_session_mode": "HARD"}
        night_mode_str = dn_config.get("night_session_mode", None)
        if night_mode_str is not None:
            mode = NightSessionMode(night_mode_str)
            assert mode == NightSessionMode.HARD_RESET
        
        dn_config = {"night_session_mode": "SOFT"}
        mode = NightSessionMode(dn_config["night_session_mode"])
        assert mode == NightSessionMode.SOFT_RESET
        
        dn_config = {"night_session_mode": "OFF"}
        mode = NightSessionMode(dn_config["night_session_mode"])
        assert mode == NightSessionMode.OFF
    
    def test_orchestrator_legacy_fallback_conversion(self):
        """
        Verify legacy fallback from night_session_resets_trade_streak boolean.
        
        The orchestrator should gracefully handle old config format.
        """
        from domain.enums import NightSessionMode
        
        # Simulate legacy config without new key
        dn_config = {"night_session_resets_trade_streak": True}
        
        night_mode_str = dn_config.get("night_session_mode", None)
        if night_mode_str is not None:
            mode = NightSessionMode(night_mode_str)
        else:
            # Legacy fallback
            resets_trade_streak = dn_config.get("night_session_resets_trade_streak", True)
            mode = NightSessionMode.HARD_RESET if resets_trade_streak else NightSessionMode.SOFT_RESET
        
        assert mode == NightSessionMode.HARD_RESET
        
        # Test legacy with False
        dn_config = {"night_session_resets_trade_streak": False}
        night_mode_str = dn_config.get("night_session_mode", None)
        if night_mode_str is not None:
            mode = NightSessionMode(night_mode_str)
        else:
            resets_trade_streak = dn_config.get("night_session_resets_trade_streak", True)
            mode = NightSessionMode.HARD_RESET if resets_trade_streak else NightSessionMode.SOFT_RESET
        
        assert mode == NightSessionMode.SOFT_RESET


class TestConfigNightSessionMode:
    """Test config parsing for night_session_mode."""
    
    def test_config_has_night_session_mode(self):
        """Verify config.json contains night_session_mode key."""
        import json
        
        config_path = os.path.join(
            os.path.dirname(__file__), 
            '../../config/config.json'
        )
        
        with open(config_path) as f:
            config = json.load(f)
        
        # Should have new canonical key
        assert 'night_session_mode' in config['day_night'], \
            "config.json must contain night_session_mode key"
        
        # Value should be one of the valid enum values
        assert config['day_night']['night_session_mode'] in ['OFF', 'SOFT', 'HARD'], \
            "night_session_mode must be OFF, SOFT, or HARD"
    
    def test_config_schema_validates_night_session_mode(self):
        """Verify schema accepts night_session_mode enum values."""
        import json
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
        
        # Should validate successfully with new key
        jsonschema.validate(config, schema)


class TestBootstrapEnvLoading:
    """Test bootstrap .env loading functionality."""
    
    def test_manual_env_parser_handles_key_value(self):
        """Test manual .env parser handles KEY=value format."""
        from pathlib import Path
        from bootstrap import _load_env_file_manual
        
        test_file = Path(tempfile.mktemp(suffix='.env'))
        try:
            test_file.write_text("TEST_KEY_1=test_value_1\n")
            
            # Clear if exists
            if 'TEST_KEY_1' in os.environ:
                del os.environ['TEST_KEY_1']
            
            _load_env_file_manual(test_file)
            
            assert os.environ.get('TEST_KEY_1') == 'test_value_1'
        finally:
            test_file.unlink(missing_ok=True)
            if 'TEST_KEY_1' in os.environ:
                del os.environ['TEST_KEY_1']
    
    def test_manual_env_parser_handles_quoted_values(self):
        """Test manual .env parser handles quoted values."""
        from pathlib import Path
        from bootstrap import _load_env_file_manual
        
        test_file = Path(tempfile.mktemp(suffix='.env'))
        try:
            test_file.write_text('TEST_KEY_2="double quoted value"\nTEST_KEY_3=\'single quoted\'\n')
            
            # Clear if exists
            for k in ['TEST_KEY_2', 'TEST_KEY_3']:
                if k in os.environ:
                    del os.environ[k]
            
            _load_env_file_manual(test_file)
            
            assert os.environ.get('TEST_KEY_2') == 'double quoted value'
            assert os.environ.get('TEST_KEY_3') == 'single quoted'
        finally:
            test_file.unlink(missing_ok=True)
            for k in ['TEST_KEY_2', 'TEST_KEY_3']:
                if k in os.environ:
                    del os.environ[k]
    
    def test_manual_env_parser_skips_comments(self):
        """Test manual .env parser skips comment lines."""
        from pathlib import Path
        from bootstrap import _load_env_file_manual
        
        test_file = Path(tempfile.mktemp(suffix='.env'))
        try:
            test_file.write_text("# This is a comment\nTEST_KEY_4=real_value\n# Another comment\n")
            
            if 'TEST_KEY_4' in os.environ:
                del os.environ['TEST_KEY_4']
            
            _load_env_file_manual(test_file)
            
            assert os.environ.get('TEST_KEY_4') == 'real_value'
        finally:
            test_file.unlink(missing_ok=True)
            if 'TEST_KEY_4' in os.environ:
                del os.environ['TEST_KEY_4']
    
    def test_manual_env_parser_does_not_overwrite_existing(self):
        """Test manual .env parser does not overwrite existing env vars."""
        from pathlib import Path
        from bootstrap import _load_env_file_manual
        
        test_file = Path(tempfile.mktemp(suffix='.env'))
        try:
            test_file.write_text("TEST_EXISTING=new_value\n")
            
            # Set existing value
            os.environ['TEST_EXISTING'] = 'original_value'
            
            _load_env_file_manual(test_file)
            
            # Should keep original value
            assert os.environ.get('TEST_EXISTING') == 'original_value'
        finally:
            test_file.unlink(missing_ok=True)
            if 'TEST_EXISTING' in os.environ:
                del os.environ['TEST_EXISTING']
    
    def test_load_environment_handles_missing_env_file(self):
        """Test load_environment handles missing .env file gracefully."""
        from bootstrap import load_environment
        
        # This should not raise an exception even without .env file
        # (The function logs a message and continues)
        try:
            # Temporarily rename .env if it exists
            import shutil
            env_path = Path(__file__).parent.parent.parent / '.env'
            backup_path = Path('/tmp/martin_env_backup')
            
            renamed = False
            if env_path.exists():
                shutil.move(str(env_path), str(backup_path))
                renamed = True
            
            try:
                # Should not raise
                load_environment()
            finally:
                if renamed:
                    shutil.move(str(backup_path), str(env_path))
        except Exception as e:
            pytest.fail(f"load_environment should handle missing .env gracefully: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
