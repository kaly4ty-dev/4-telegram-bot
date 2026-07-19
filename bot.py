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

db_path = os.environ.get("DB_PATH", "trades.json")
db = TinyDB(db_path)
TradeQuery = Query()

known_markets = set()
scanner_active = False
auto_buy_new_coins = False
AUTO_BUY_AMOUNT = 5

def is_authorized(message):
    return message.from_user.id == ALLOWED_USER_ID

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    if not TELEGRAM_BOT_TOKEN: return "ERROR: Bot Token is missing!"
    return "✅ Bot Webhook Server is running and alive!"

@app.route('/' + TELEGRAM_BOT_TOKEN, methods=['POST'])
def receive_update():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

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
                        if bot: bot.send_message(ALLOWED_USER_ID, f"🎯 *TAKE PROFIT TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`")
                        try: exchange.create_market_sell_order(symbol, trade['amount'])
                        except: pass
                        db.remove(TradeQuery.symbol == symbol)
                        continue
                    
                    tsl_price = trade['highest_price'] * (1 - (trade['tsl_pct'] / 100))
                    if current_price <= tsl_price:
                        if bot: bot.send_message(ALLOWED_USER_ID, f"🛑 *TRAILING STOP TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`")
                        try: exchange.create_market_sell_order(symbol, trade['amount'])
                        except: pass
                        db.remove(TradeQuery.symbol == symbol)
        except: pass
        time.sleep(5)

def monitor_new_coins():
    global known_markets
    try:
        markets = exchange.fetch_markets()
        known_markets = {m['symbol'] for m in markets if m['quote'] == 'USDT'}
    except: pass

    while True:
        if scanner_active:
            try:
                markets = exchange.fetch_markets()
                current_markets = {m['symbol'] for m in markets if m['quote'] == 'USDT'}
                new_coins = current_markets - known_markets
                if new_coins:
                    for coin in new_coins:
                        if bot: bot.send_message(ALLOWED_USER_ID, f"🚨 *NEW COIN DETECTED ON MEXC:* `{coin}`", parse_mode='Markdown')
                        if auto_buy_new_coins:
                            try:
                                exchange.options['createMarketBuyOrderRequiresPrice'] = False
                                exchange.create_market_buy_order(coin, AUTO_BUY_AMOUNT)
                                ticker = exchange.fetch_ticker(coin)
                                price = ticker['last']
                                db.upsert({'symbol': coin, 'amount': AUTO_BUY_AMOUNT / price, 'buy_price': price, 'highest_price': price, 'tp_pct': 20.0, 'tsl_pct': 10.0}, TradeQuery.symbol == coin)
                            except: pass
                    known_markets = current_markets
            except: pass
        time.sleep(30)

if bot:
    @bot.message_handler(commands=['start', 'help', 'status'])
    def check_status(message):
        if not is_authorized(message): return
        msg = "🤖 *Bot Status:*\n🔑 API: Loaded\n🔐 Secret: Loaded\nCommands: /balance, /price, /smartbuy, /sell, /scanner"
        bot.reply_to(message, msg, parse_mode='Markdown')

    @bot.message_handler(commands=['balance'])
    def check_balance(message):
        if not is_authorized(message): return
        try:
            balance = exchange.fetch_balance()
            active = {k: v for k, v in balance['total'].items() if v > 0}
            msg = "💰 *Your MEXC Balances:*\n" + "\n".join([f"• {k}: `{v}`" for k, v in active.items()])
            bot.reply_to(message, msg if active else "Empty.", parse_mode='Markdown')
        except Exception as e: bot.reply_to(message, f"❌ Error: {str(e)}")

    @bot.message_handler(commands=['smartbuy'])
    def smart_buy_token(message):
        if not is_authorized(message): return
        try:
            parts = message.text.split()
            symbol, quote_amount, tp_pct, tsl_pct = parts[1].upper(), float(parts[2]), float(parts[3]), float(parts[4])
            bot.reply_to(message, f"⏳ Buying ${quote_amount} of {symbol}...")
            exchange.options['createMarketBuyOrderRequiresPrice'] = False
            exchange.create_market_buy_order(symbol, quote_amount)
            price = exchange.fetch_ticker(symbol)['last']
            db.upsert({'symbol': symbol, 'amount': quote_amount / price, 'buy_price': price, 'highest_price': price, 'tp_pct': tp_pct, 'tsl_pct': tsl_pct}, TradeQuery.symbol == symbol)
            bot.reply_to(message, f"✅ *SMART BUY SUCCESS!*\nSpent `${quote_amount}` on {symbol}\nTracking for {tp_pct}% Profit / {tsl_pct}% Stop.", parse_mode='Markdown')
        except Exception as e: bot.reply_to(message, f"❌ Trade Failed: {str(e)}")

    @bot.message_handler(commands=['sell'])
    def sell_token(message):
        if not is_authorized(message): return
        try:
            parts = message.text.split()
            symbol, amount = parts[1].upper(), float(parts[2])
            exchange.create_market_sell_order(symbol, amount)
            db.remove(TradeQuery.symbol == symbol)
            bot.reply_to(message, f"✅ *SELL SUCCESS!*")
        except Exception as e: bot.reply_to(message, f"❌ Trade Failed: {str(e)}")

if __name__ == "__main__":
    if TELEGRAM_BOT_TOKEN:
        threading.Thread(target=monitor_trades, daemon=True).start()
        threading.Thread(target=monitor_new_coins, daemon=True).start()
        bot.remove_webhook()
        time.sleep(1)
        if RENDER_URL:
            bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{TELEGRAM_BOT_TOKEN}")
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
