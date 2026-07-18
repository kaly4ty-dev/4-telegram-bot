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
# FLASK WEB SERVER (KEEP-ALIVE FOR RENDER)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running and alive!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask server on port {port}...")
    # This must block, so we run it inside the thread. 
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# ==========================================
# CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", 0))

if not TELEGRAM_BOT_TOKEN:
    print("WARNING: TELEGRAM_BOT_TOKEN is not set in environment.")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

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
# DATABASE HELPERS
# ==========================================
def save_trade(symbol, amount, buy_price, tp_pct, tsl_pct):
    db.upsert({
        'symbol': symbol,
        'amount': amount,
        'buy_price': buy_price,
        'highest_price': buy_price,
        'tp_pct': tp_pct,
        'tsl_pct': tsl_pct
    }, TradeQuery.symbol == symbol)

def remove_trade(symbol):
    db.remove(TradeQuery.symbol == symbol)

def update_highest_price(symbol, highest_price):
    db.update({'highest_price': highest_price}, TradeQuery.symbol == symbol)

def get_all_trades():
    return db.all()

# ==========================================
# BACKGROUND WORKERS
# ==========================================
def monitor_trades():
    while True:
        try:
            active_trades = get_all_trades()
            if active_trades:
                tickers = exchange.fetch_tickers()
                for trade in active_trades:
                    symbol = trade['symbol']
                    if symbol not in tickers: continue
                    
                    current_price = tickers[symbol]['last']
                    if not current_price: continue

                    if current_price > trade['highest_price']:
                        update_highest_price(symbol, current_price)
                        trade['highest_price'] = current_price

                    tp_price = trade['buy_price'] * (1 + (trade['tp_pct'] / 100))
                    if current_price >= tp_price:
                        bot.send_message(ALLOWED_USER_ID, f"🎯 *TAKE PROFIT TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`", parse_mode='Markdown')
                        try:
                            exchange.create_market_sell_order(symbol, trade['amount'])
                        except Exception as e:
                            bot.send_message(ALLOWED_USER_ID, f"❌ Failed to execute TP sell: {e}")
                        remove_trade(symbol)
                        continue
                    
                    tsl_price = trade['highest_price'] * (1 - (trade['tsl_pct'] / 100))
                    if current_price <= tsl_price:
                        bot.send_message(ALLOWED_USER_ID, f"🛑 *TRAILING STOP TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`\n(Dropped from peak of `${trade['highest_price']:.6f}`)", parse_mode='Markdown')
                        try:
                            exchange.create_market_sell_order(symbol, trade['amount'])
                        except Exception as e:
                            bot.send_message(ALLOWED_USER_ID, f"❌ Failed to execute TSL sell: {e}")
                        remove_trade(symbol)
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
                        bot.send_message(ALLOWED_USER_ID, msg, parse_mode='Markdown')
                        
                        if auto_buy_new_coins:
                            bot.send_message(ALLOWED_USER_ID, f"⚡ Auto-buying ${AUTO_BUY_AMOUNT} of {coin}...")
                            try:
                                ticker = exchange.fetch_ticker(coin)
                                price = ticker['last']
                                base_amount = AUTO_BUY_AMOUNT / price
                                exchange.create_market_buy_order(coin, base_amount)
                                
                                save_trade(coin, base_amount, price, 20.0, 10.0)
                                bot.send_message(ALLOWED_USER_ID, f"✅ Auto-buy success. Added to smart tracker (20% TP, 10% TSL).")
                            except Exception as e:
                                bot.send_message(ALLOWED_USER_ID, f"❌ Auto-buy failed: {e}")

                    known_markets = current_markets
            except Exception as e:
                print(f"Error in scanner: {e}")
        time.sleep(30)

# ==========================================
# TELEGRAM COMMANDS
# ==========================================

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

# [Rest of commands omitted for brevity, keeping only essential ones]
@bot.message_handler(commands=['scanner'])
def toggle_scanner(message):
    if not is_authorized(message): return
    global scanner_active
    scanner_active = not scanner_active
    bot.reply_to(message, f"New Coin Scanner is now {'ON 🟢' if scanner_active else 'OFF 🔴'}")

@bot.message_handler(commands=['autobuy'])
def toggle_autobuy(message):
    if not is_authorized(message): return
    global auto_buy_new_coins
    auto_buy_new_coins = not auto_buy_new_coins
    bot.reply_to(message, f"Auto-Sniper is now {'ON 🟢' if auto_buy_new_coins else 'OFF 🔴'}.")

@bot.message_handler(commands=['trades'])
def view_trades(message):
    if not is_authorized(message): return
    active_trades = get_all_trades()
    if not active_trades:
        bot.reply_to(message, "No active smart trades being monitored.")
        return
    msg = "📊 *Active Trades:*\n\n"
    for t in active_trades:
        msg += f"🔹 *{t['symbol']}* | Bought: ${t['buy_price']:.6f} | High: ${t['highest_price']:.6f}\n"
    bot.reply_to(message, msg, parse_mode='Markdown')

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

if __name__ == "__main__":
    print("Starting deployment...")
    
    # 1. Start the Telegram Bot in a background thread
    print("Starting Telegram Bot listener...")
    def run_bot():
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Telegram polling crashed: {e}")
            
    threading.Thread(target=run_bot, daemon=True).start()
    
    # 2. Start the trading/monitoring workers
    print("Starting Trade Monitors...")
    threading.Thread(target=monitor_trades, daemon=True).start()
    threading.Thread(target=monitor_new_coins, daemon=True).start()
    
    # 3. Start the Flask server ON THE MAIN THREAD
    # Render requires the main process to open a web port. 
    # If the main process finishes (or if Flask is in a background thread and the main thread hits EOF), Render kills it.
    print("Starting Flask Web Server...")
    run_flask()
