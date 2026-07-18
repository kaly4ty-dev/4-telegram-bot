import os
import time
import telebot
import ccxt
import threading
from dotenv import load_dotenv
from flask import Flask
from tinydb import TinyDB, Query

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", 0))

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- DATABASE SETUP ---
# Initialize TinyDB. This will create a 'trades.json' file locally.
db = TinyDB('trades.json')
TradeQuery = Query()

# --- GLOBAL STATE ---
known_markets = set()
scanner_active = False
auto_buy_new_coins = False
AUTO_BUY_AMOUNT = 5 # USDT to spend on newly detected coins

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
    """Background thread that constantly checks active trades for TP/TSL."""
    while True:
        active_trades = get_all_trades()
        if active_trades:
            try:
                tickers = exchange.fetch_tickers()
                
                for trade in active_trades:
                    symbol = trade['symbol']
                    if symbol not in tickers: continue
                    
                    current_price = tickers[symbol]['last']
                    if not current_price: continue

                    # 1. Update highest price seen (for Trailing Stop)
                    if current_price > trade['highest_price']:
                        update_highest_price(symbol, current_price)
                        trade['highest_price'] = current_price # Update local variable for next checks

                    # 2. Check Take Profit (TP)
                    tp_price = trade['buy_price'] * (1 + (trade['tp_pct'] / 100))
                    if current_price >= tp_price:
                        bot.send_message(ALLOWED_USER_ID, f"🎯 *TAKE PROFIT TRIGGERED!*\nSelling {symbol} at `${current_price:.6f}`", parse_mode='Markdown')
                        try:
                            exchange.create_market_sell_order(symbol, trade['amount'])
                        except Exception as e:
                            bot.send_message(ALLOWED_USER_ID, f"❌ Failed to execute TP sell: {e}")
                        remove_trade(symbol)
                        continue
                    
                    # 3. Check Trailing Stop Loss (TSL)
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
                
        time.sleep(5) # Check prices every 5 seconds

def monitor_new_coins():
    """Background thread that checks for newly listed coins on MEXC."""
    global known_markets
    
    # Initial population of known markets
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
                                
                                # Save to TinyDB (Default 20% TP, 10% TSL)
                                save_trade(coin, base_amount, price, 20.0, 10.0)
                                bot.send_message(ALLOWED_USER_ID, f"✅ Auto-buy success. Added to smart tracker (20% TP, 10% TSL).")
                            except Exception as e:
                                bot.send_message(ALLOWED_USER_ID, f"❌ Auto-buy failed: {e}")

                    # Update known markets
                    known_markets = current_markets
            except Exception as e:
                print(f"Error in scanner: {e}")
                
        time.sleep(30) # Poll MEXC every 30 seconds for new listings


# ==========================================
# TELEGRAM COMMANDS
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message): return
    help_text = (
        "🤖 *Advanced MEXC Trading Bot (Database Enabled)*\n\n"
        "👉 `/balance` - Check balances\n"
        "👉 `/price <symbol>` - Get current price\n"
        "👉 `/smartbuy <symbol> <$USDT> <TP%> <TSL%>` - Buy with auto Take Profit & Trailing Stop\n"
        "👉 `/trades` - View monitored trades\n"
        "👉 `/sell <symbol> <amount>` - Manual Sell\n\n"
        "🔍 *Scanner & Auto-Sniper*\n"
        "👉 `/scanner` - Toggle new coin detection\n"
        "👉 `/autobuy` - Toggle instant buying of new coins"
    )
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['scanner'])
def toggle_scanner(message):
    if not is_authorized(message): return
    global scanner_active
    scanner_active = not scanner_active
    status = "ON 🟢" if scanner_active else "OFF 🔴"
    bot.reply_to(message, f"New Coin Scanner is now {status}")

@bot.message_handler(commands=['autobuy'])
def toggle_autobuy(message):
    if not is_authorized(message): return
    global auto_buy_new_coins
    auto_buy_new_coins = not auto_buy_new_coins
    status = "ON 🟢" if auto_buy_new_coins else "OFF 🔴"
    msg = f"Auto-Sniper for new coins is now {status}."
    if auto_buy_new_coins:
        msg += f"\n⚠️ *WARNING:* It will instantly buy ${AUTO_BUY_AMOUNT} of ANY new USDT pair listed on MEXC. This is risky due to volatility/rugs."
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['trades'])
def view_trades(message):
    if not is_authorized(message): return
    active_trades = get_all_trades()
    if not active_trades:
        bot.reply_to(message, "No active smart trades being monitored in the database.")
        return
        
    msg = "📊 *Active Monitored Trades:*\n\n"
    for trade in active_trades:
        msg += (
            f"🔹 *{trade['symbol']}*\n"
            f"  • Bought At: `${trade['buy_price']:.6f}`\n"
            f"  • Highest Reached: `${trade['highest_price']:.6f}`\n"
            f"  • Target TP: +{trade['tp_pct']}%\n"
            f"  • Trailing Stop: -{trade['tsl_pct']}%\n"
        )
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['smartbuy'])
def smart_buy_token(message):
    if not is_authorized(message): return
    try:
        parts = message.text.split()
        if len(parts) != 5:
            bot.reply_to(message, "⚠️ Usage: `/smartbuy COIN/USDT <$USDT> <TP%> <TSL%>`\nExample: `/smartbuy BTC/USDT 50 10 5`", parse_mode='Markdown')
            return

        symbol = parts[1].upper()
        quote_amount = float(parts[2])
        tp_pct = float(parts[3])
        tsl_pct = float(parts[4])
        
        bot.reply_to(message, f"⏳ Buying ${quote_amount} of {symbol}...")
        
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        base_amount = quote_amount / price
        
        # Execute Market Buy
        order = exchange.create_market_buy_order(symbol, base_amount)
        
        # Add to TinyDB
        save_trade(symbol, base_amount, price, tp_pct, tsl_pct)
        
        bot.reply_to(message, f"✅ *SMART BUY SUCCESS!*\nBought `{base_amount:.5f}` {symbol}\nTracking for {tp_pct}% Profit or {tsl_pct}% Trailing Stop.", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Trade Failed: {str(e)}")

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

@bot.message_handler(commands=['price'])
def check_price(message):
    if not is_authorized(message): return
    try:
        symbol = message.text.split()[1].upper()
        price = exchange.fetch_ticker(symbol)['last']
        bot.reply_to(message, f"📈 *{symbol}*: `${price}`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Usage: `/price BTC/USDT`")

@bot.message_handler(commands=['sell'])
def sell_token(message):
    if not is_authorized(message): return
    try:
        parts = message.text.split()
        symbol, base_amount = parts[1].upper(), float(parts[2])
        exchange.create_market_sell_order(symbol, base_amount)
        # Remove from database if manually sold
        remove_trade(symbol)
        bot.reply_to(message, f"✅ *SELL SUCCESS!*\nSold `{base_amount}` of `{symbol}`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Trade Failed: {str(e)}")

if __name__ == "__main__":
    if TELEGRAM_BOT_TOKEN:
        print("Starting health-check Flask server...")
        keep_alive()
        
        print("Starting background workers...")
        threading.Thread(target=monitor_trades, daemon=True).start()
        threading.Thread(target=monitor_new_coins, daemon=True).start()
        
        print("Starting Telegram bot polling...")
        bot.infinity_polling()
