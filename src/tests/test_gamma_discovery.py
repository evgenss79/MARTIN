"""
Tests for Gamma market discovery.

Verifies:
- Event-driven discovery model (events[] with nested markets[])
- Market-level filtering for "up or down" variants
- Timestamp fallback logic (market-level → event-level)
- Time window filtering with grace periods
- Token ID extraction from various formats
- Discovery returns non-zero results for valid fixtures
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestUpOrDownPatternMatching:
    """Test pattern matching for 'up or down' market titles."""
    
    def test_matches_up_or_down(self):
        """Test matching 'up or down' pattern."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._is_up_or_down_market("BTC up or down") is True
        assert client._is_up_or_down_market("Will Bitcoin go UP OR DOWN?") is True
        assert client._is_up_or_down_market("ETH Up Or Down hourly") is True
    
    def test_matches_up_slash_down(self):
        """Test matching 'up/down' pattern."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._is_up_or_down_market("BTC up/down") is True
        assert client._is_up_or_down_market("Will ETH go UP/DOWN?") is True
    
    def test_matches_updown(self):
        """Test matching 'updown' pattern."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._is_up_or_down_market("BTC updown market") is True
        assert client._is_up_or_down_market("UpDown prediction") is True
    
    def test_no_match_for_unrelated(self):
        """Test non-matching market titles."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._is_up_or_down_market("Bitcoin price prediction") is False
        assert client._is_up_or_down_market("ETH above 2000") is False
        assert client._is_up_or_down_market("Will BTC reach ATH?") is False


class TestAssetMatching:
    """Test asset matching logic."""
    
    def test_matches_symbol(self):
        """Test matching by asset symbol."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._market_matches_asset("BTC up or down", "BTC", "Bitcoin") is True
        assert client._market_matches_asset("ETH hourly market", "ETH", "Ethereum") is True
    
    def test_matches_full_name(self):
        """Test matching by full asset name."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._market_matches_asset("Bitcoin up or down", "BTC", "Bitcoin") is True
        assert client._market_matches_asset("Ethereum hourly market", "ETH", "Ethereum") is True
    
    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._market_matches_asset("btc up or down", "BTC", "Bitcoin") is True
        assert client._market_matches_asset("BITCOIN price", "BTC", "Bitcoin") is True
    
    def test_no_match_wrong_asset(self):
        """Test no match for wrong asset."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        assert client._market_matches_asset("ETH up or down", "BTC", "Bitcoin") is False
        assert client._market_matches_asset("Solana market", "ETH", "Ethereum") is False


class TestEventDrivenParsing:
    """Test event-driven response parsing."""
    
    @pytest.mark.asyncio
    async def test_extracts_markets_from_events(self):
        """Test extracting markets from events[] structure."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        # Mock the _request method to return event-driven structure
        mock_response = {
            "events": [
                {
                    "id": "event1",
                    "title": "BTC Hourly Event",
                    "endDate": "2026-01-22T17:00:00Z",
                    "markets": [
                        {
                            "id": "market1",
                            "title": "BTC up or down",
                            "slug": "btc-up-or-down-1",
                            "conditionId": "condition1",
                            "endDate": "2026-01-22T17:00:00Z",
                            "outcomes": ["Up", "Down"],
                            "clobTokenIds": ["token_up_1", "token_down_1"],
                        },
                        {
                            "id": "market2",
                            "title": "BTC up or down 2",
                            "slug": "btc-up-or-down-2",
                            "conditionId": "condition2",
                            # No endDate - should fall back to event
                            "outcomes": ["Up", "Down"],
                            "clobTokenIds": ["token_up_2", "token_down_2"],
                        },
                    ],
                },
            ],
            "markets": [],  # No top-level markets
        }
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            
            events, markets = await client.search_markets("BTC up or down")
            
            assert len(events) == 1
            assert len(markets) == 2
            assert markets[0]["title"] == "BTC up or down"
            assert markets[1]["title"] == "BTC up or down 2"
            # Check event title propagation
            assert markets[0]["_event_title"] == "BTC Hourly Event"
    
    @pytest.mark.asyncio
    async def test_combines_top_level_and_nested_markets(self):
        """Test combining top-level markets and nested event markets."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        mock_response = {
            "events": [
                {
                    "id": "event1",
                    "title": "Event",
                    "markets": [
                        {"id": "nested1", "title": "Nested Market"},
                    ],
                },
            ],
            "markets": [
                {"id": "top1", "title": "Top Level Market"},
            ],
        }
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            
            events, markets = await client.search_markets("test")
            
            assert len(events) == 1
            assert len(markets) == 2
            # Top-level first, then nested
            assert markets[0]["title"] == "Top Level Market"
            assert markets[1]["title"] == "Nested Market"


class TestTimestampFallback:
    """Test timestamp fallback from market-level to event-level."""
    
    def test_uses_market_level_end_date(self):
        """Test using market-level endDate when available."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        market_data = {
            "slug": "test-market",
            "conditionId": "cond1",
            "endDate": "2026-01-22T17:00:00Z",
            "outcomes": ["Up", "Down"],
            "clobTokenIds": ["up", "down"],
        }
        
        window = client._parse_market(market_data, "BTC")
        
        assert window is not None
        assert window.end_ts > 0
    
    def test_falls_back_to_event_level(self):
        """Test falling back to event-level timestamp."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        # Market has no endDate, but has _event_end_date
        market_data = {
            "slug": "test-market",
            "conditionId": "cond1",
            "_event_end_date": "2026-01-22T18:00:00Z",
            "outcomes": ["Up", "Down"],
            "clobTokenIds": ["up", "down"],
        }
        
        window = client._parse_market(market_data, "BTC")
        
        assert window is not None
        assert window.end_ts > 0
    
    def test_returns_none_if_no_timestamp(self):
        """Test returning None if no timestamp available."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        market_data = {
            "slug": "test-market",
            "conditionId": "cond1",
            # No endDate at all
            "outcomes": ["Up", "Down"],
            "clobTokenIds": ["up", "down"],
        }
        
        window = client._parse_market(market_data, "BTC")
        
        assert window is None


class TestTokenIdExtraction:
    """Test extraction of UP and DOWN token IDs."""
    
    def test_extracts_from_tokens_array(self):
        """Test extracting from tokens[] array."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        data = {
            "tokens": [
                {"outcome": "Up", "token_id": "up_token"},
                {"outcome": "Down", "token_id": "down_token"},
            ]
        }
        
        up, down = client._extract_token_ids(data)
        
        assert up == "up_token"
        assert down == "down_token"
    
    def test_extracts_from_outcomes_and_clob_token_ids(self):
        """Test extracting from outcomes[] and clobTokenIds[]."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        data = {
            "outcomes": ["Up", "Down"],
            "clobTokenIds": ["up_id", "down_id"],
        }
        
        up, down = client._extract_token_ids(data)
        
        assert up == "up_id"
        assert down == "down_id"
    
    def test_handles_yes_no_outcomes(self):
        """Test handling Yes/No as Up/Down equivalents."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        data = {
            "tokens": [
                {"outcome": "Yes", "token_id": "yes_token"},
                {"outcome": "No", "token_id": "no_token"},
            ]
        }
        
        up, down = client._extract_token_ids(data)
        
        assert up == "yes_token"  # Yes = Up
        assert down == "no_token"  # No = Down
    
    def test_handles_json_string_arrays(self):
        """Test handling outcomes/clobTokenIds as JSON strings."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        data = {
            "outcomes": '["Up", "Down"]',
            "clobTokenIds": '["up_str", "down_str"]',
        }
        
        up, down = client._extract_token_ids(data)
        
        assert up == "up_str"
        assert down == "down_str"


class TestTimeWindowFiltering:
    """Test time window filtering with grace periods."""
    
    @pytest.mark.asyncio
    async def test_accepts_active_markets(self):
        """Test accepting markets that haven't expired."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        # Current time
        now_ts = int(datetime.now(timezone.utc).timestamp())
        future_end = now_ts + 3600  # 1 hour from now
        
        mock_response = {
            "events": [],
            "markets": [
                {
                    "title": "BTC up or down",
                    "slug": "btc-hourly-active",
                    "conditionId": "cond1",
                    "endDate": future_end,
                    "outcomes": ["Up", "Down"],
                    "clobTokenIds": ["up", "down"],
                },
            ],
        }
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            
            windows = await client.discover_hourly_markets(["BTC"], current_ts=now_ts)
            
            assert len(windows) == 1
            assert windows[0].slug == "btc-hourly-active"
    
    @pytest.mark.asyncio
    async def test_accepts_recently_expired_within_grace(self):
        """Test accepting markets within grace period."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        now_ts = int(datetime.now(timezone.utc).timestamp())
        # Expired 2 minutes ago (within 5 min grace period)
        expired_end = now_ts - 120
        
        mock_response = {
            "events": [],
            "markets": [
                {
                    "title": "BTC up or down",
                    "slug": "btc-hourly-grace",
                    "conditionId": "cond1",
                    "endDate": expired_end,
                    "outcomes": ["Up", "Down"],
                    "clobTokenIds": ["up", "down"],
                },
            ],
        }
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            
            windows = await client.discover_hourly_markets(
                ["BTC"],
                current_ts=now_ts,
                grace_period_seconds=300,  # 5 min grace
            )
            
            # Should still be accepted (within grace)
            assert len(windows) == 1
    
    @pytest.mark.asyncio
    async def test_rejects_expired_beyond_grace(self):
        """Test rejecting markets expired beyond grace period."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        now_ts = int(datetime.now(timezone.utc).timestamp())
        # Expired 10 minutes ago (beyond 5 min grace)
        expired_end = now_ts - 600
        
        mock_response = {
            "events": [],
            "markets": [
                {
                    "title": "BTC up or down",
                    "slug": "btc-hourly-old",
                    "conditionId": "cond1",
                    "endDate": expired_end,
                    "outcomes": ["Up", "Down"],
                    "clobTokenIds": ["up", "down"],
                },
            ],
        }
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            
            windows = await client.discover_hourly_markets(
                ["BTC"],
                current_ts=now_ts,
                grace_period_seconds=300,  # 5 min grace
            )
            
            assert len(windows) == 0


class TestDiscoveryIntegration:
    """Integration tests for full discovery flow."""
    
    @pytest.mark.asyncio
    async def test_discovers_btc_and_eth_markets(self):
        """Test discovering markets for both BTC and ETH."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        now_ts = int(datetime.now(timezone.utc).timestamp())
        future_end = now_ts + 3600
        
        def mock_request_response(method, path, params=None):
            query = params.get("q", "") if params else ""
            if "BTC" in query.upper() or "BITCOIN" in query.upper():
                return {
                    "events": [{
                        "title": "BTC Hourly",
                        "markets": [{
                            "title": "BTC up or down",
                            "slug": "btc-hourly",
                            "conditionId": "cond_btc",
                            "endDate": future_end,
                            "outcomes": ["Up", "Down"],
                            "clobTokenIds": ["btc_up", "btc_down"],
                        }]
                    }],
                    "markets": [],
                }
            elif "ETH" in query.upper() or "ETHEREUM" in query.upper():
                return {
                    "events": [{
                        "title": "ETH Hourly",
                        "markets": [{
                            "title": "ETH up or down",
                            "slug": "eth-hourly",
                            "conditionId": "cond_eth",
                            "endDate": future_end,
                            "outcomes": ["Up", "Down"],
                            "clobTokenIds": ["eth_up", "eth_down"],
                        }]
                    }],
                    "markets": [],
                }
            return {"events": [], "markets": []}
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = mock_request_response
            
            windows = await client.discover_hourly_markets(["BTC", "ETH"], current_ts=now_ts)
            
            assert len(windows) == 2
            slugs = [w.slug for w in windows]
            assert "btc-hourly" in slugs
            assert "eth-hourly" in slugs
    
    @pytest.mark.asyncio
    async def test_deduplicates_by_slug(self):
        """Test that duplicate slugs are filtered out."""
        from adapters.polymarket.gamma_client import GammaClient
        
        client = GammaClient()
        
        now_ts = int(datetime.now(timezone.utc).timestamp())
        future_end = now_ts + 3600
        
        mock_response = {
            "events": [],
            "markets": [
                # Same slug appears twice
                {
                    "title": "BTC up or down",
                    "slug": "btc-hourly-dup",
                    "conditionId": "cond1",
                    "endDate": future_end,
                    "outcomes": ["Up", "Down"],
                    "clobTokenIds": ["up1", "down1"],
                },
                {
                    "title": "BTC up or down (duplicate)",
                    "slug": "btc-hourly-dup",  # Same slug!
                    "conditionId": "cond2",
                    "endDate": future_end + 100,
                    "outcomes": ["Up", "Down"],
                    "clobTokenIds": ["up2", "down2"],
                },
            ],
        }
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            
            windows = await client.discover_hourly_markets(["BTC"], current_ts=now_ts)
            
            # Should only have one (deduplicated by slug)
            assert len(windows) == 1
            assert windows[0].slug == "btc-hourly-dup"


class TestParseTimestamp:
    """Test timestamp parsing from various formats."""
    
    def test_parses_unix_seconds(self):
        """Test parsing Unix timestamp in seconds."""
        from adapters.polymarket.gamma_client import GammaClient
        
        ts = GammaClient._parse_timestamp(1706000000)
        assert ts == 1706000000
    
    def test_parses_unix_milliseconds(self):
        """Test parsing Unix timestamp in milliseconds."""
        from adapters.polymarket.gamma_client import GammaClient
        
        ts = GammaClient._parse_timestamp(1706000000000)
        assert ts == 1706000000
    
    def test_parses_iso_format(self):
        """Test parsing ISO format timestamp."""
        from adapters.polymarket.gamma_client import GammaClient
        
        ts = GammaClient._parse_timestamp("2024-01-23T12:00:00Z")
        assert ts > 0
    
    def test_parses_iso_with_offset(self):
        """Test parsing ISO format with timezone offset."""
        from adapters.polymarket.gamma_client import GammaClient
        
        ts = GammaClient._parse_timestamp("2024-01-23T12:00:00+00:00")
        assert ts > 0
    
    def test_returns_zero_for_none(self):
        """Test returning 0 for None input."""
        from adapters.polymarket.gamma_client import GammaClient
        
        ts = GammaClient._parse_timestamp(None)
        assert ts == 0
    
    def test_returns_zero_for_invalid(self):
        """Test returning 0 for invalid input."""
        from adapters.polymarket.gamma_client import GammaClient
        
        ts = GammaClient._parse_timestamp("not a timestamp")
        assert ts == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
