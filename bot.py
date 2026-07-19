import os
import time
import telebot
import ccxt
import threading
from dotenv import load_dotenv
from tinydb import TinyDB, Query
from flask import Flask, request, abort

# Load environment variables
load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "").strip()
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

# Render automatically provides this variable with your app URL (e.g. https://four-telegram-bot.onrender.com)
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()

allowed_user_str = os.getenv("ALLOWED_USER_ID", "").strip()
try:
    ALLOWED_USER_ID = int(allowed_user_str) if allowed_user_str else 0
except ValueError:
    ALLOWED_USER_ID = 0

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

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
# FLASK WEBHOOK SERVER (THE 409 FIX)
# ==========================================
app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    if not TELEGRAM_BOT_TOKEN:
        return "ERROR: Bot Token is missing!"
    return "✅ Bot Webhook Server is running and alive!"

# This route receives instant pushes from Telegram
@app.route('/' + TELEGRAM_BOT_TOKEN, methods=['POST'])
def receive_update():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

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
    except Exception as e:
        pass

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
                pass
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
            "👉 `/autobuy` - Toggle instant buying of new coins\n"
            "👉 `/status` - Check API Key Status"
        )
        bot.reply_to(message, help_text, parse_mode='Markdown')

    @bot.message_handler(commands=['status'])
    def check_status(message):
        if not is_authorized(message): return
        api_len = len(MEXC_API_KEY)
        sec_len = len(MEXC_SECRET_KEY)
        msg = "🤖 *Bot Diagnostics & Status:*\n\n"
        msg += f"🔑 **MEXC_API_KEY:** {'✅ Loaded' if api_len > 0 else '❌ MISSING'}\n"
        msg += f"🔐 **MEXC_SECRET_KEY:** {'✅ Loaded' if sec_len > 0 else '❌ MISSING'}\n"
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

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("Starting Webhook deployment...")
    
    if TELEGRAM_BOT_TOKEN:
        # Start the background workers
        threading.Thread(target=monitor_trades, daemon=True).start()
        threading.Thread(target=monitor_new_coins, daemon=True).start()
        
        # 1. Clear any old polling conflicts by removing the webhook first
        bot.remove_webhook()
        time.sleep(1)
        
        # 2. Tell Telegram to PUSH messages to Render instead of us PULLING (Fixes 409 forever)
        if RENDER_URL:
            webhook_url = f"{RENDER_URL.rstrip('/')}/{TELEGRAM_BOT_TOKEN}"
            bot.set_webhook(url=webhook_url)
            print(f"✅ Webhook successfully set to: {webhook_url}")
        else:
            print("⚠️ WARNING: RENDER_EXTERNAL_URL is not set. Webhooks might fail.")
    else:
        print("🛑 FATAL ERROR: TELEGRAM_BOT_TOKEN is missing!")

    # Start the Flask Webhook Server
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
