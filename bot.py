import os
import time
import telebot
import ccxt
import threading
from dotenv import load_dotenv
from tinydb import TinyDB, Query
from flask import Flask

# Load environment variables
load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "").strip()
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

# Safely parse ALLOWED_USER_ID
allowed_user_str = os.getenv("ALLOWED_USER_ID", "").strip()
try:
    ALLOWED_USER_ID = int(allowed_user_str) if allowed_user_str else 0
except ValueError:
    ALLOWED_USER_ID = 0

# Verify Telegram Token exists BEFORE initializing the bot
if not TELEGRAM_BOT_TOKEN:
    print("CRITICAL ERROR: TELEGRAM_BOT_TOKEN is not set!")
    print("Please go to Render.com -> Your Web Service -> Environment")
    print("And add the variable: TELEGRAM_BOT_TOKEN = <your_token_here>")
    
# Initialize Bot (Only if token exists, otherwise it will crash here)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

# Initialize MEXC
exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- DATABASE SETUP ---
db_path = os.environ.get("DB_PATH", "trades.json")
db = TinyDB(db_path)
TradeQuery = Query()

# --- GLOBAL STATE ---
known_markets = set()
scanner_active = False
auto_buy_new_coins = False
AUTO_BUY_AMOUNT = 5 # USDT

def is_authorized(message):
    return message.from_user.id == ALLOWED_USER_ID

# ==========================================
# FLASK WEB SERVER (KEEP-ALIVE FOR RENDER)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    if not TELEGRAM_BOT_TOKEN:
        return "ERROR: Bot Token is missing in Render Environment Variables! Please add TELEGRAM_BOT_TOKEN."
    return "Bot is running and alive!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask server on port {port}...")
    app.run(host='0.0.0.0', port=port, use_reloader=False)


# ==========================================
# BACKGROUND WORKERS
# ==========================================
def monitor_trades():
    while True:
        try:
            active_trades = db.all()
            if active_trades:
                tickers = exchange.fetch_tickers()
                for trade in active_trades:
                    symbol = trade['symbol']
                    if symbol not in tickers: continue
                    
                    current_price = tickers[symbol]['last']
                    if not current_price: continue

                    if current_price > trade['highest_price']:
                        db.update({'highest_price': current_price}, TradeQuery.symbol == symbol)
                        trade['highest_price'] = current_price

                    tp_price = trade['buy_price'] * (1 + (trade['tp_pct'] / 100))
                    if current_price >= tp_price:
                        if bot: bot.send_message(ALLOWED_USER_ID, f"🎯 *TAKE PROFIT TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`", parse_mode='Markdown')
                        try:
                            exchange.create_market_sell_order(symbol, trade['amount'])
                        except Exception as e:
                            if bot: bot.send_message(ALLOWED_USER_ID, f"❌ Failed to execute TP sell: {e}")
                        db.remove(TradeQuery.symbol == symbol)
                        continue
                    
                    tsl_price = trade['highest_price'] * (1 - (trade['tsl_pct'] / 100))
                    if current_price <= tsl_price:
                        if bot: bot.send_message(ALLOWED_USER_ID, f"🛑 *TRAILING STOP TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`\n(Dropped from peak of `${trade['highest_price']:.6f}`)", parse_mode='Markdown')
                        try:
                            exchange.create_market_sell_order(symbol, trade['amount'])
                        except Exception as e:
                            if bot: bot.send_message(ALLOWED_USER_ID, f"❌ Failed to execute TSL sell: {e}")
                        db.remove(TradeQuery.symbol == symbol)
        except Exception as e:
            print(f"Error in trade monitor: {e}")
        time.sleep(5)

def monitor_new_coins():
    global known_markets
    try:
        markets = exchange.fetch_markets()
        known_markets = {m['symbol'] for m in markets if m['quote'] == 'USDT'}
        print(f"Loaded {len(known_markets)} existing markets.")
    except Exception as e:
        print(f"Failed to load markets: {e}")

    while True:
        if scanner_active:
            try:
                markets = exchange.fetch_markets()
                current_markets = {m['symbol'] for m in markets if m['quote'] == 'USDT'}
                new_coins = current_markets - known_markets
                
                if new_coins:
                    for coin in new_coins:
                        msg = f"🚨 *NEW COIN DETECTED ON MEXC:* `{coin}`"
                        if bot: bot.send_message(ALLOWED_USER_ID, msg, parse_mode='Markdown')
                        
                        if auto_buy_new_coins:
                            if bot: bot.send_message(ALLOWED_USER_ID, f"⚡ Auto-buying ${AUTO_BUY_AMOUNT} of {coin}...")
                            try:
                                ticker = exchange.fetch_ticker(coin)
                                price = ticker['last']
                                base_amount = AUTO_BUY_AMOUNT / price
                                exchange.create_market_buy_order(coin, base_amount)
                                
                                db.upsert({
                                    'symbol': coin,
                                    'amount': base_amount,
                                    'buy_price': price,
                                    'highest_price': price,
                                    'tp_pct': 20.0,
                                    'tsl_pct': 10.0
                                }, TradeQuery.symbol == coin)
                                if bot: bot.send_message(ALLOWED_USER_ID, f"✅ Auto-buy success. Added to smart tracker (20% TP, 10% TSL).")
                            except Exception as e:
                                if bot: bot.send_message(ALLOWED_USER_ID, f"❌ Auto-buy failed: {e}")

                    known_markets = current_markets
            except Exception as e:
                print(f"Error in scanner: {e}")
        time.sleep(30)

# ==========================================
# TELEGRAM COMMANDS
# ==========================================

if bot:
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        if not is_authorized(message): return
        help_text = (
            "🤖 *Advanced MEXC Trading Bot*\n\n"
            "👉 `/balance` - Check balances\n"
            "👉 `/price <symbol>` - Get current price\n"
            "👉 `/smartbuy <symbol> <$USDT> <TP%> <TSL%>`\n"
            "👉 `/trades` - View monitored trades\n"
            "👉 `/sell <symbol> <amount>` - Manual Sell\n\n"
            "🔍 *Scanner & Auto-Sniper*\n"
            "👉 `/scanner` - Toggle new coin detection\n"
            "👉 `/autobuy` - Toggle instant buying of new coins"
        )
        bot.reply_to(message, help_text, parse_mode='Markdown')

    @bot.message_handler(commands=['balance'])
    def check_balance(message):
        if not is_authorized(message): return
        try:
            balance = exchange.fetch_balance()
            active_balances = {k: v for k, v in balance['total'].items() if v > 0}
            msg = "💰 *Your MEXC Balances:*\n" + "\n".join([f"• {k}: `{v}`" for k, v in active_balances.items()])
            bot.reply_to(message, msg if active_balances else "Wallet empty.", parse_mode='Markdown')
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {str(e)}")

    @bot.message_handler(commands=['status'])
    def check_status(message):
        if not is_authorized(message): return
        
        api_len = len(MEXC_API_KEY)
        sec_len = len(MEXC_SECRET_KEY)
        
        msg = "🤖 *Bot Diagnostics & Status:*\n\n"
        msg += f"🔑 **MEXC_API_KEY:** {'✅ Loaded' if api_len > 0 else '❌ MISSING'} (Length: {api_len})\n"
        msg += f"🔐 **MEXC_SECRET_KEY:** {'✅ Loaded' if sec_len > 0 else '❌ MISSING'} (Length: {sec_len})\n"
        
        if sec_len == 0:
            msg += "\n⚠️ *Fix:* Go to Render.com -> Environment. Add exactly `MEXC_SECRET_KEY`."
            
        bot.reply_to(message, msg, parse_mode='Markdown')

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("Starting deployment...")
    
    if not TELEGRAM_BOT_TOKEN:
        print("--------------------------------------------------")
        print("🛑 FATAL ERROR: TELEGRAM_BOT_TOKEN is missing!")
        print("The script is running, but the Telegram Bot will not start.")
        print("Please add your Token in Render.com -> Environment Variables")
        print("--------------------------------------------------")
    else:
        # Start the Telegram Bot in a background thread
        print("Starting Telegram Bot listener...")
        def run_bot():
            try:
                bot.infinity_polling(timeout=10, long_polling_timeout=5)
            except Exception as e:
                print(f"Telegram polling crashed: {e}")
                
        threading.Thread(target=run_bot, daemon=True).start()
    
    # Start the trading/monitoring workers
    print("Starting Trade Monitors...")
    threading.Thread(target=monitor_trades, daemon=True).start()
    threading.Thread(target=monitor_new_coins, daemon=True).start()
    
    # Start the Flask server ON THE MAIN THREAD
    print("Starting Flask Web Server...")
    run_flask()
