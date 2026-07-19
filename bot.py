import os
import time
import requests
import base58
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")
RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")

# Token setup
# By default, trading WSOL for USDC. You can swap these to trade meme coins.
# Example: Base token = MEME mint address, Quote token = USDC or SOL
BASE_TOKEN_MINT = "So11111111111111111111111111111111111111112"  # WSOL
BASE_DECIMALS = 9
QUOTE_TOKEN_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
QUOTE_DECIMALS = 6

# Grid settings
LOWER_PRICE = 130.0   # Lower boundary of the grid
UPPER_PRICE = 170.0   # Upper boundary of the grid
GRID_LEVELS = 5       # Number of grid levels
TRADE_SIZE = 5.0      # Amount of Quote Token (e.g. 5 USDC) to spend per buy order
CHECK_INTERVAL = 10   # Seconds to wait between price checks
SLIPPAGE_BPS = 50     # Slippage tolerance in basis points (50 = 0.5%)

# Jupiter API endpoints (Best aggregator on Solana)
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"
# ---------------------

def calculate_grids(lower, upper, levels):
    """Calculates price levels for the grid."""
    step = (upper - lower) / (levels - 1)
    return [lower + (step * i) for i in range(levels)]

def get_price_and_quote(input_mint, output_mint, amount_in_lamports):
    """Fetches quote from Jupiter API to determine current price or route."""
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount_in_lamports,
        "slippageBps": SLIPPAGE_BPS
    }
    try:
        response = requests.get(JUPITER_QUOTE_API, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching quote: {e}")
        return None

def execute_swap(client, keypair, quote_response):
    """Builds and executes the swap transaction via Jupiter."""
    if not PRIVATE_KEY:
        print("[!] No private key provided. Running in PAPER TRADING mode.")
        return None

    try:
        # Request serialized transaction from Jupiter
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto"
        }
        res = requests.post(JUPITER_SWAP_API, json=payload)
        res.raise_for_status()
        swap_data = res.json()
        
        swap_transaction = swap_data.get("swapTransaction")
        if not swap_transaction:
            print("Failed to get swapTransaction from Jupiter.")
            return None

        # Decode transaction
        raw_tx = base58.b58decode(swap_transaction)
        tx = VersionedTransaction.from_bytes(raw_tx)
        
        # Sign transaction
        signed_tx = VersionedTransaction(tx.message, [keypair])
        
        # Send transaction
        tx_sig = client.send_raw_transaction(bytes(signed_tx), opts=None)
        print(f"✅ Transaction submitted! Signature: https://solscan.io/tx/{tx_sig.value}")
        return tx_sig.value

    except Exception as e:
        print(f"❌ Swap execution failed: {e}")
        return None

def main():
    print("🚀 Starting Solana Grid Trading Bot via Jupiter API...")
    
    keypair = None
    if PRIVATE_KEY:
        try:
            keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY))
            print(f"Wallet loaded: {keypair.pubkey()}")
        except Exception as e:
            print(f"Invalid private key format: {e}")
            return
    else:
        print("⚠️ Running in PAPER TRADING mode. Set SOLANA_PRIVATE_KEY in .env to trade live.")

    client = Client(RPC_URL, commitment=Confirmed)
    
    # 1. Setup the grids
    grids = calculate_grids(LOWER_PRICE, UPPER_PRICE, GRID_LEVELS)
    print(f"📊 Grid Levels: {[round(g, 4) for g in grids]}")
    
    # Track the last executed grid level
    last_grid_index = None

    while True:
        try:
            # Check price by getting a quote for 1 Base Token to Quote Token
            base_unit = int(1 * (10 ** BASE_DECIMALS))
            quote_data = get_price_and_quote(BASE_TOKEN_MINT, QUOTE_TOKEN_MINT, base_unit)
            
            if not quote_data:
                time.sleep(CHECK_INTERVAL)
                continue
                
            out_amount = int(quote_data["outAmount"])
            current_price = out_amount / (10 ** QUOTE_DECIMALS)
            print(f"Current Price: {current_price:.4f} USDC")

            # Determine nearest grid level
            nearest_index = min(range(len(grids)), key=lambda i: abs(grids[i] - current_price))
            nearest_grid = grids[nearest_index]

            if last_grid_index is None:
                # Initialize state on first run
                last_grid_index = nearest_index
                print(f"Initialized state at grid level {nearest_index} (${nearest_grid:.4f})")
            
            else:
                # 2. Grid Trading Logic
                if nearest_index < last_grid_index:
                    # Price dropped to a lower grid level -> BUY!
                    print(f"📉 Price dropped to Grid {nearest_index} (${nearest_grid:.4f}). Executing BUY...")
                    
                    # Quote to buy BASE token using TRADE_SIZE of QUOTE token
                    trade_amount_lamports = int(TRADE_SIZE * (10 ** QUOTE_DECIMALS))
                    buy_quote = get_price_and_quote(QUOTE_TOKEN_MINT, BASE_TOKEN_MINT, trade_amount_lamports)
                    
                    if buy_quote:
                        execute_swap(client, keypair, buy_quote)
                    
                    last_grid_index = nearest_index

                elif nearest_index > last_grid_index:
                    # Price rose to a higher grid level -> SELL!
                    print(f"📈 Price rose to Grid {nearest_index} (${nearest_grid:.4f}). Executing SELL...")
                    
                    # Calculate how much BASE token to sell based on USD target size
                    sell_amount_lamports = int((TRADE_SIZE / current_price) * (10 ** BASE_DECIMALS))
                    sell_quote = get_price_and_quote(BASE_TOKEN_MINT, QUOTE_TOKEN_MINT, sell_amount_lamports)
                    
                    if sell_quote:
                        execute_swap(client, keypair, sell_quote)
                    
                    last_grid_index = nearest_index
            
        except Exception as e:
            print(f"An error occurred in the main loop: {e}")
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
