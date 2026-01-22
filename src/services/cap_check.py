"""
CAP Check Service for MARTIN.

Implements the CAP_PASS validation logic per specification:
- CAP_PASS is valid ONLY if consecutive <=cap ticks occur AFTER confirm_ts
- Ticks in [confirm_ts, end_ts] are checked
- Requires CAP_MIN_TICKS consecutive ticks <= PRICE_CAP
"""

from src.adapters.polymarket.clob_client import ClobClient
from src.adapters.storage import CapCheckRepository
from src.domain.models import CapCheck, Trade
from src.domain.enums import CapStatus
from src.common.logging import get_logger
from src.common.exceptions import APIError

logger = get_logger(__name__)


class CapCheckService:
    """
    Service for CAP_PASS validation.
    
    IMPORTANT: CAP_PASS must be detected ONLY in [confirm_ts, end_ts].
    Any ticks before confirm_ts are IGNORED (MG-2 constraint).
    """
    
    def __init__(
        self,
        clob_client: ClobClient,
        cap_check_repo: CapCheckRepository,
        price_cap: float,
        cap_min_ticks: int,
    ):
        """
        Initialize CAP Check Service.
        
        Args:
            clob_client: CLOB API client for price history
            cap_check_repo: Repository for CAP check records
            price_cap: Maximum price for CAP_PASS
            cap_min_ticks: Minimum consecutive ticks <= price_cap
        """
        self._clob = clob_client
        self._repo = cap_check_repo
        self._price_cap = price_cap
        self._cap_min_ticks = cap_min_ticks
    
    def create_cap_check(
        self,
        trade: Trade,
        token_id: str,
        confirm_ts: int,
        end_ts: int,
    ) -> CapCheck:
        """
        Create a new CAP check record.
        
        Args:
            trade: Associated trade
            token_id: Token ID to check
            confirm_ts: When CAP check can begin
            end_ts: Window end timestamp
            
        Returns:
            Created CapCheck record
        """
        # Check if confirm_ts >= end_ts (LATE condition)
        if confirm_ts >= end_ts:
            cap_check = CapCheck(
                trade_id=trade.id,
                token_id=token_id,
                confirm_ts=confirm_ts,
                end_ts=end_ts,
                status=CapStatus.LATE,
            )
            logger.warning(
                "CAP check LATE - confirm_ts >= end_ts",
                trade_id=trade.id,
                confirm_ts=confirm_ts,
                end_ts=end_ts,
            )
        else:
            cap_check = CapCheck(
                trade_id=trade.id,
                token_id=token_id,
                confirm_ts=confirm_ts,
                end_ts=end_ts,
                status=CapStatus.PENDING,
            )
        
        return self._repo.create(cap_check)
    
    async def check_cap_pass(
        self,
        cap_check: CapCheck,
        current_ts: int | None = None,
    ) -> CapCheck:
        """
        Check if CAP_PASS condition is met.
        
        Rules per specification:
        1. Fetch prices history series from CLOB for token in [confirm_ts, end_ts]
        2. Iterate in time order, counting consecutive ticks <= price_cap
        3. IGNORE all ticks before confirm_ts (MG-2 constraint)
        4. If consecutive >= CAP_MIN_TICKS => PASS
        5. If end reached without pass => FAIL
        
        Args:
            cap_check: CAP check record to validate
            current_ts: Current timestamp (for partial checks)
            
        Returns:
            Updated CapCheck with status
        """
        if cap_check.status in (CapStatus.PASS, CapStatus.FAIL, CapStatus.LATE):
            return cap_check
        
        try:
            # Fetch price history from CLOB
            # IMPORTANT: Only fetch from confirm_ts onwards (MG-2)
            prices = await self._clob.get_prices_in_range(
                token_id=cap_check.token_id,
                start_ts=cap_check.confirm_ts,  # Start from confirm_ts
                end_ts=cap_check.end_ts,
            )
            
            logger.debug(
                "Fetched prices for CAP check",
                trade_id=cap_check.trade_id,
                price_count=len(prices),
                confirm_ts=cap_check.confirm_ts,
                end_ts=cap_check.end_ts,
            )
            
            # Check consecutive ticks <= price_cap
            consecutive = 0
            first_pass_ts = None
            price_at_pass = None
            
            for ts, price in prices:
                # CRITICAL: Ignore ticks before confirm_ts (MG-2 constraint)
                if ts < cap_check.confirm_ts:
                    continue
                
                if price <= self._price_cap:
                    consecutive += 1
                    
                    # Record first valid tick
                    if consecutive == 1:
                        first_pass_ts = ts
                        price_at_pass = price
                    
                    # Check if we've reached required ticks
                    if consecutive >= self._cap_min_ticks:
                        cap_check.status = CapStatus.PASS
                        cap_check.consecutive_ticks = consecutive
                        cap_check.first_pass_ts = first_pass_ts
                        cap_check.price_at_pass = price_at_pass
                        
                        logger.info(
                            "CAP_PASS achieved",
                            trade_id=cap_check.trade_id,
                            consecutive_ticks=consecutive,
                            first_pass_ts=first_pass_ts,
                            price_at_pass=price_at_pass,
                        )
                        
                        self._repo.update(cap_check)
                        return cap_check
                else:
                    # Reset consecutive count when price exceeds cap
                    consecutive = 0
                    first_pass_ts = None
                    price_at_pass = None
            
            # Check if we should mark as FAIL
            # Only fail if we've passed end_ts or current time >= end_ts
            check_ts = current_ts or int(__import__("time").time())
            
            if check_ts >= cap_check.end_ts:
                cap_check.status = CapStatus.FAIL
                cap_check.consecutive_ticks = consecutive
                
                logger.info(
                    "CAP_FAIL - insufficient consecutive ticks",
                    trade_id=cap_check.trade_id,
                    max_consecutive=consecutive,
                    required=self._cap_min_ticks,
                )
                
                self._repo.update(cap_check)
            else:
                # Still pending - update consecutive count
                cap_check.consecutive_ticks = consecutive
                if first_pass_ts:
                    cap_check.first_pass_ts = first_pass_ts
                    cap_check.price_at_pass = price_at_pass
                self._repo.update(cap_check)
            
            return cap_check
            
        except APIError as e:
            logger.error(
                "API error during CAP check",
                trade_id=cap_check.trade_id,
                error=str(e),
            )
            # Don't change status on API error - will retry
            raise
    
    async def process_pending_checks(
        self,
        current_ts: int | None = None,
    ) -> list[CapCheck]:
        """
        Process all pending CAP checks.
        
        Args:
            current_ts: Current timestamp
            
        Returns:
            List of processed CapCheck records
        """
        pending = self._repo.get_pending()
        results: list[CapCheck] = []
        
        for cap_check in pending:
            try:
                result = await self.check_cap_pass(cap_check, current_ts)
                results.append(result)
            except Exception as e:
                logger.error(
                    "Error processing CAP check",
                    cap_check_id=cap_check.id,
                    error=str(e),
                )
        
        return results
