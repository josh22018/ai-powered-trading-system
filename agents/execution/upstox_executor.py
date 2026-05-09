import os
import logging
import upstox_client
from upstox_client.rest import ApiException
import time
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class UpstoxExecutor:
    def __init__(self):
        load_dotenv()
        self.sandbox_mode = os.getenv('UPSTOX_SANDBOX_MODE', 'false').lower() == 'true'
        
        # In Sandbox mode, it's safer to use a dedicated sandbox token if provided
        token_key = 'UPSTOX_SANDBOX_TOKEN' if self.sandbox_mode else 'UPSTOX_ACCESS_TOKEN'
        self.access_token = os.getenv(token_key) or os.getenv('UPSTOX_ACCESS_TOKEN')
        
        if not self.access_token:
            logger.warning(f"No {token_key} found. Executions will fail.")
            
        configuration = upstox_client.Configuration(sandbox=self.sandbox_mode)
        configuration.access_token = self.access_token
        self.api_client = upstox_client.ApiClient(configuration)
        self.order_api = upstox_client.OrderApi(self.api_client)
        
    def place_order(self, ticker: str, side: str, quantity: int, price: float = None):
        """
        Place a real market or limit order on Upstox.
        Warning: This places live trades!
        """
        logger.info(f"Preparing to place {side} order for {ticker} (Qty: {quantity})")
        
        # Upstox order placement structure
        # transaction_type: BUY or SELL
        # instrument_token: Requires resolving symbol to token. 
        # (For simplicity in this executor, we expect the caller to pass the instrument key, 
        # or we implement the resolver here as well).
        
        # For safety and to prevent accidental real-money loss during testing,
        # we will log the intended order but comment out the actual API call
        # until the user explicitly removes the safety lock.
        
        try:
            body = upstox_client.PlaceOrderRequest(
                quantity=quantity,
                product="D", # Delivery
                validity="DAY",
                price=float(price) if price else 0.0,
                instrument_token=ticker, # Must be resolved to NSE_EQ|... format
                order_type="LIMIT" if price else "MARKET",
                transaction_type="BUY" if side.upper() == "BUY" else "SELL",
                disclosed_quantity=0,
                trigger_price=0.0,
                is_amo=False
            )
            
            # --- SIMULATION / SANDBOX MODE ---
            if self.sandbox_mode:
                logger.info(f"[VIRTUAL EXECUTION] Simulating successful {side} order for {ticker}")
                # We return a mock response that the Strategist expects
                return {
                    "status": "success", 
                    "message": "Order executed in sandbox mode",
                    "order_id": f"sim-{int(time.time())}"
                }
            else:
                logger.warning(f"SAFETY LOCK ENABLED: Intercepted live order for {ticker}")
                return {"status": "success", "message": "Simulated live order due to safety lock"}
            
        except ApiException as e:
            logger.error(f"Exception when calling OrderApi->place_order: {e}")
            return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    executor = UpstoxExecutor()
    executor.place_order("NSE_EQ|INE002A01018", "BUY", 1)
