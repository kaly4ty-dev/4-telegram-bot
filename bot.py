import os, json, time, threading, traceback
import ccxt
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ========== ULTIMATE CONFIG - Handles ALL env name failures ==========
def get_env(*names):
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip().strip('"').strip("'")
    return None

BOT_TOKEN = get_env('BOT_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_BOT_TOKEN', 'TG_TOKEN', 'TOKEN', 'TELEGRAM_BOT_TOKEN')
MEXC_API_KEY = get_env('MEXC_API_KEY', 'MEXC_KEY', 'API_KEY')
MEXC_SECRET = get_env('MEXC_SECRET', 'MEXC_API_SECRET', 'MEXC_API_SECRET_KEY', 'API_SECRET')

print("=== ULTIMATE BOT STARTING ===")
print(f"BOT_TOKEN found: {bool(BOT_TOKEN)} len={len(BOT_TOKEN) if BOT_TOKEN else 0}")
print(f"MEXC_API_KEY found: {bool(MEXC_API_KEY)}")
print(f"MEXC_SECRET found: {bool(MEXC_SECRET)}")

if not BOT_TOKEN:
    print("❌ FATAL: No BOT_TOKEN found! Add BOT_TOKEN or TELEGRAM_TOKEN in Render")
    app_flask = Flask(__name__)
    @app_flask.route('/')
    def home():
        return "ERROR: BOT_TOKEN missing! Add it in Render Environment"
    if __name__ == '__main__':
        app_flask.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))
    exit(1)

COINS = {
    "BTC":   {"symbol": "BTC/USDT",   "tp": 5.0,  "sl": 1.5, "type": "major"},
    "ETH":   {"symbol": "ETH/USDT",   "tp": 6.0,  "sl": 2.0, "type": "major"},
    "SOL":   {"symbol": "SOL/USDT",   "tp": 7.0,  "sl": 2.0, "type": "major"},
    "PEPE":  {"symbol": "PEPE/USDT",  "tp": 12.0, "sl": 3.0, "type": "meme", "emoji": "🐸"},
    "DOGE":  {"symbol": "DOGE/USDT",  "tp": 10.0, "sl": 3.0, "type": "meme", "emoji": "🐕"},
    "SHIB":  {"symbol": "SHIB/USDT",  "tp": 12.0, "sl": 3.0, "type": "meme", "emoji": "🐶"},
    "BONK":  {"symbol": "BONK/USDT",  "tp": 15.0, "sl": 4.0, "type": "meme", "emoji": "🐾"},
    "FLOKI": {"symbol": "FLOKI/USDT", "tp": 15.0, "sl": 4.0, "type": "meme", "emoji": "🚀"},
    "WIF":   {"symbol": "WIF/USDT",   "tp": 15.0, "sl": 4.0, "type": "meme", "emoji": "🎩"},
}

TRADES_FILE = "active_trades.json"
active_trades = {}

def load_trades():
    global active_trades
    try:
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, 'r') as f:
                active_trades = json.load(f)
            print(f"✅ Loaded {len(active_trades)} saved trades")
    except Exception as e:
        print(f"Load trades error: {e}")

def save_trades():
    try:
        with open(TRADES_FILE, 'w') as f:
            json.dump(active_trades, f)
    except Exception as e:
        print(f"Save trades error: {e}")

load_trades()

exchange = None
if MEXC_API_KEY and MEXC_SECRET:
    exchange = ccxt.mexc({
        'apiKey': MEXC_API_KEY,
        'secret': MEXC_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

def get_price(symbol):
    try:
        if not exchange:
            return None
        return exchange.fetch_ticker(symbol)['last']
    except:
        return None

def get_balance():
    try:
        if not exchange:
            return None
        return exchange.fetch_balance()
    except Exception as e:
        print(f"Balance error: {e}")
        return None

app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return f"ULTIMATE MEME+Btc BOT LIVE! Trades: {len(active_trades)} | Coins: {', '.join(COINS.keys())}"

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """🔥 **ULTIMATE TRADING BOT** 🔥
Fixes all failures!

**Buy:**
/buy 5 btc - BTC +5% / -1.5%
/buy 5 pepe - PEPE +12% / -3% 🐸
/buy 5 doge - DOGE +10% / -3% 🐕
/buy 5 shib - SHIB +12% / -3% 🐶
/buy 5 bonk - BONK +15% / -4% 🐾
/buy 5 floki - FLOKI +15% / -4%
/buy 5 wif - WIF +15% / -4%
/buy 3 eth
/buy 3 sol

**Other:**
/balance - wallet
/status - all trades + PnL
/price - BTC + memes price
/sell btc - sell one
/sell all - sell everything
/memes - top meme prices

Best Result:
Meme = fast +15% because volatile!
BTC = safe +5%

Bot auto-saves trades so redeploy won't lose them!
"""
    await update.message.reply_text(msg, parse_mode='Markdown')

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prices = []
        for c in ["BTC", "PEPE", "DOGE", "SHIB"]:
            p = get_price(COINS[c]['symbol'])
            if p:
                if p < 0.01:
                    prices.append(f"{c}: ${p:.8f}")
                else:
                    prices.append(f"{c}: ${p:,.4f}")
        await update.message.reply_text("📈 **Prices**\n" + "\n".join(prices), parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = get_balance()
        if not bal:
            await update.message.reply_text("❌ MEXC keys missing. Add MEXC_API_KEY + MEXC_SECRET in Render")
            return
        usdt = bal.get('USDT', {}).get('free', 0)
        msg = f"💰 **Balance**\nUSDT: ${usdt:.4f}\n\n"
        for coin, info in COINS.items():
            base = info['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free and free > 0:
                p = get_price(info['symbol'])
                val = free * p if p else 0
                if val > 0.01:
                    msg += f"{coin}: {free:.6f} (~${val:.2f})\n"
        if msg.count('\n') == 3:
            msg += "No coins yet. Use /buy 5 pepe"
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Balance error: {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_trades:
        await update.message.reply_text("📭 No active trades.\n\nUse:\n/buy 5 btc\n/buy 5 pepe\n/balance to see wallet")
        return
    msg = "📊 **ACTIVE TRADES**\n\n"
    total_pnl = 0
    for sym, t in active_trades.items():
        now = get_price(sym)
        if not now:
            now = t['entry']
        pnl = (now - t['entry']) / t['entry'] * 100
        total_pnl += pnl
        emoji = COINS.get(t['coin'], {}).get('emoji', '📈')
        msg += f"{emoji} **{t['coin']}** {sym}\nEntry: ${t['entry']:.8f}\nNow: ${now:.8f}\nPnL: {pnl:+.2f}% | ${t['usdt']}\nTP: +{t['tp']}% SL: -{t['sl']}%\n\n"
    msg += f"**Total avg PnL: {total_pnl/len(active_trades):+.2f}%**"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def memes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🐸 **MEME PRICES**\n\n"
    for coin in ["PEPE", "DOGE", "SHIB", "BONK", "FLOKI", "WIF"]:
        p = get_price(COINS[coin]['symbol'])
        if p:
            emoji = COINS[coin].get('emoji','')
            msg += f"{emoji} {coin}: ${p:.8f}\n"
    await update.message.reply_text(msg)

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not exchange:
            await update.message.reply_text("❌ MEXC keys missing! Add MEXC_API_KEY + MEXC_SECRET in Render")
            return
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage:\n/buy 5 btc\n/buy 2 pepe\nCoins: btc, eth, sol, pepe, doge, shib, bonk, floki, wif")
            return
        try:
            amount_usdt = float(context.args[0])
        except:
            await update.message.reply_text("First arg must be number: /buy 5 pepe")
            return
        coin_name = context.args[1].upper()
        if coin_name not in COINS:
            await update.message.reply_text(f"❌ {coin_name} not supported.\nSupported: {', '.join(COINS.keys())}")
            return
        info = COINS[coin_name]
        symbol = info['symbol']
        bal = get_balance()
        usdt_free = bal.get('USDT', {}).get('free', 0) if bal else 0
        if usdt_free < amount_usdt:
            base = symbol.split('/')[0]
            base_free = bal.get(base, {}).get('free', 0) if bal else 0
            await update.message.reply_text(f"❌ Insufficient USDT.\nHave: ${usdt_free:.2f}\nNeed: ${amount_usdt}\n{base} held: {base_free}\n\nUse /sell all to free USDT")
            return
        price = get_price(symbol)
        if not price:
            await update.message.reply_text(f"❌ Can't get price for {symbol}")
            return
        qty = amount_usdt / price
        await update.message.reply_text(f"⏳ Buying ${amount_usdt} {coin_name} @ ${price}...\nQty: {qty}")
        try:
            order = exchange.create_market_buy_order(symbol, qty)
            order_id = order.get('id', 'N/A')
        except Exception as e:
            try:
                order = exchange.create_order(symbol, 'market', 'buy', qty, None, {'quoteOrderQty': amount_usdt})
                order_id = order.get('id', 'N/A')
            except Exception as e2:
                await update.message.reply_text(f"❌ Buy failed:\n{e}\nFallback: {e2}\nTry smaller: /buy 1 {coin_name.lower()}")
                return
        active_trades[symbol] = {
            'entry': float(price),
            'amount': float(qty),
            'usdt': float(amount_usdt),
            'tp': float(info['tp']),
            'sl': float(info['sl']),
            'coin': coin_name,
            'time': time.time()
        }
        save_trades()
        await update.message.reply_text(
            f"✅ **BOUGHT {coin_name}!**\nPrice: ${price}\nQty: {qty:.6f}\nCost: ${amount_usdt}\nOrder: {order_id}\n\n🤖 Auto: TP +{info['tp']}% → ${price*(1+info['tp']/100):.8f}\nSL -{info['sl']}% → ${price*(1-info['sl']/100):.8f}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Buy error: {e}\n{traceback.format_exc()[:800]}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not exchange:
            await update.message.reply_text("❌ MEXC keys missing")
            return
        if not context.args:
            await update.message.reply_text("Use: /sell btc or /sell all")
            return
        target = context.args[0].upper()
        bal = get_balance()
        if not bal:
            await update.message.reply_text("Can't get balance")
            return
        sold = []
        if target == "ALL":
            for coin, info in COINS.items():
                base = info['symbol'].split('/')[0]
                free = bal.get(base, {}).get('free', 0)
                if free and free > 0:
                    try:
                        p = get_price(info['symbol'])
                        if p and free * p < 0.5:
                            continue
                        exchange.create_market_sell_order(info['symbol'], free)
                        sold.append(coin)
                        if info['symbol'] in active_trades:
                            del active_trades[info['symbol']]
                    except Exception as e:
                        print(f"Sell {coin} error: {e}")
            save_trades()
            await update.message.reply_text(f"✅ Sold: {', '.join(sold) if sold else 'Nothing'}")
        else:
            if target not in COINS:
                await update.message.reply_text(f"Unknown {target}. Use: {', '.join(COINS.keys())} or ALL")
                return
            info = COINS[target]
            base = info['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free and free > 0:
                try:
                    exchange.create_market_sell_order(info['symbol'], free)
                    if info['symbol'] in active_trades:
                        del active_trades[info['symbol']]
                    save_trades()
                    p = get_price(info['symbol'])
                    val = free * p if p else 0
                    await update.message.reply_text(f"✅ Sold {free:.6f} {target} ~${val:.2f}")
                except Exception as e:
                    await update.message.reply_text(f"Sell failed: {e}")
            else:
                await update.message.reply_text(f"No {target} to sell")
    except Exception as e:
        await update.message.reply_text(f"Sell error: {e}")

def monitor():
    print("Monitor started")
    while True:
        try:
            if not exchange or not active_trades:
                time.sleep(5)
                continue
            for symbol, trade in list(active_trades.items()):
                try:
                    now = get_price(symbol)
                    if not now:
                        continue
                    pnl = (now - trade['entry']) / trade['entry'] * 100
                    if pnl >= trade['tp'] or pnl <= -trade['sl']:
                        try:
                            bal = get_balance()
                            if not bal:
                                continue
                            base = symbol.split('/')[0]
                            free = bal.get(base, {}).get('free', 0)
                            if free and free > 0:
                                if free * now < 0.5 and symbol != "BTC/USDT":
                                    if free * now < 0.3:
                                        continue
                                exchange.create_market_sell_order(symbol, free)
                                print(f"AUTO SOLD {symbol} PnL {pnl:.2f}%")
                        except Exception as e:
                            print(f"Auto sell fail {symbol}: {e}")
                            continue
                        if symbol in active_trades:
                            del active_trades[symbol]
                            save_trades()
                except Exception as e:
                    print(f"Monitor inner error {symbol}: {e}")
            time.sleep(3)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(5)

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start_cmd))
        app.add_handler(CommandHandler("price", price_cmd))
        app.add_handler(CommandHandler("balance", balance_cmd))
        app.add_handler(CommandHandler("status", status_cmd))
        app.add_handler(CommandHandler("buy", buy_cmd))
        app.add_handler(CommandHandler("sell", sell_cmd))
        app.add_handler(CommandHandler("memes", memes_cmd))
        print("✅ ULTIMATE BOT STARTED!")
        print(f"Tracking: {list(active_trades.keys())}")
        app.run_polling()
    except Exception as e:
        if "InvalidToken" in str(e):
            print("❌ TELEGRAM TOKEN INVALID!")
            while True:
                time.sleep(60)
        else:
            print(f"Bot crash: {e}")
            traceback.print_exc()
            while True:
                time.sleep(60)
