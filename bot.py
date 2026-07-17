import os, time, threading, json
import ccxt
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask

BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
MEXC_API_KEY = os.getenv('MEXC_API_KEY')
MEXC_SECRET = os.getenv('MEXC_SECRET') or os.getenv('MEXC_API_SECRET')

print(f"ENV CHECK: BOT_TOKEN={bool(BOT_TOKEN)} KEY={bool(MEXC_API_KEY)} SECRET={bool(MEXC_SECRET)}")
if not BOT_TOKEN:
    print("ERROR: Set BOT_TOKEN in Render!")
    exit(1)

CONFIG = {
    "BTC":  {"symbol": "BTC/USDT",  "tp": 3.0,  "sl": 1.0, "max_usdt": 5, "emoji": "BTC"},
    "PEPE": {"symbol": "PEPE/USDT", "tp": 8.0,  "sl": 2.0, "max_usdt": 3, "emoji": "PEPE"},
    "DOGE": {"symbol": "DOGE/USDT", "tp": 8.0,  "sl": 2.0, "max_usdt": 3, "emoji": "DOGE"},
    "SHIB": {"symbol": "SHIB/USDT", "tp": 8.0,  "sl": 2.0, "max_usdt": 3, "emoji": "SHIB"},
}

DAILY_MAX_LOSS_PCT = 5.0
MIN_24H_VOLUME = 1000000
TRADE_FILE = "active_trades.json"

def load_trades():
    try:
        if os.path.exists(TRADE_FILE):
            with open(TRADE_FILE, 'r') as f:
                return json.load(f)
    except: pass
    return {}
def save_trades(trades):
    try:
        with open(TRADE_FILE, 'w') as f:
            json.dump(trades, f)
    except: pass

active_trades = load_trades()
daily_pnl = {"date": str(date.today()), "pnl": 0.0}

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "SAFE MEME+BTC Bot LIVE!"

def get_ticker(symbol):
    try:
        t = exchange.fetch_ticker(symbol)
        return t['last'], t.get('quoteVolume', 0)
    except:
        return None, 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = """SAFE BOT V3 - ANTI-LOSS
BTC: TP +3% | SL -1% | Max $5
PEPE/DOGE/SHIB: TP +8% | SL -2% | Max $3
Daily STOP if -5% loss

Commands:
/buy 3 btc
/buy 2 pepe
/buy 2 doge
/buy 2 shib
/balance
/status
/price
/sell btc /sell pepe /sell all
"""
    await update.message.reply_text(txt)

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Prices\n"
    for k in ["BTC", "PEPE", "DOGE", "SHIB"]:
        p, vol = get_ticker(CONFIG[k]['symbol'])
        if p:
            msg += f"{k}: ${p} Vol: ${vol/1e6:.1f}M\n"
    await update.message.reply_text(msg)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt = bal.get('USDT', {}).get('free', 0)
        msg = f"Wallet\nUSDT Free: ${usdt:.4f}\n\n"
        for k, cfg in CONFIG.items():
            base = cfg['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free > 0:
                p,_ = get_ticker(cfg['symbol'])
                usd_val = free * p if p else 0
                msg += f"{k}: {free} (~${usd_val:.2f})\n"
        msg += f"\nToday PnL: {daily_pnl['pnl']:.2f}%"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Balance error: {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_trades:
        await update.message.reply_text("No active trades. Use /buy 2 pepe")
        return
    msg = "Active Trades\n\n"
    for sym, t in active_trades.items():
        now,_ = get_ticker(sym)
        if now:
            pnl = (now - t['entry']) / t['entry'] * 100
            msg += f"{t['coin']} {sym}\nEntry: {t['entry']}\nNow: {now}\nPnL: {pnl:+.2f}%\nTP:+{t['tp']}% SL:-{t['sl']}%\n\n"
    await update.message.reply_text(msg)

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global daily_pnl
    try:
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /buy 2 pepe or /buy 3 btc")
            return
        usdt_want = float(context.args[0])
        coin = context.args[1].upper()
        if coin not in CONFIG:
            await update.message.reply_text(f"Use: {', '.join(CONFIG.keys())}")
            return
        if daily_pnl['date'] != str(date.today()):
            daily_pnl = {"date": str(date.today()), "pnl": 0.0}
        if daily_pnl['pnl'] <= -DAILY_MAX_LOSS_PCT:
            await update.message.reply_text(f"Daily -{DAILY_MAX_LOSS_PCT}% hit! Stopped today.")
            return
        cfg = CONFIG[coin]
        symbol = cfg['symbol']
        if usdt_want > cfg['max_usdt']:
            await update.message.reply_text(f"Safety Max for {coin} is ${cfg['max_usdt']}. Use /buy {cfg['max_usdt']} {coin.lower()}")
            return
        bal = exchange.fetch_balance()
        free_usdt = bal.get('USDT', {}).get('free', 0)
        if free_usdt < usdt_want:
            await update.message.reply_text(f"Need ${usdt_want}, you have ${free_usdt:.2f}")
            return
        price, vol = get_ticker(symbol)
        if not price:
            await update.message.reply_text("No price, retry")
            return
        if vol < MIN_24H_VOLUME and coin != "BTC":
            await update.message.reply_text(f"Low vol ${vol/1e6:.2f}M, skip.")
            return
        if symbol in active_trades:
            await update.message.reply_text(f"You already have {coin} active. /sell {coin.lower()} first")
            return
        await update.message.reply_text(f"Buying ${usdt_want} {coin} @ ${price}...")
        qty = usdt_want / price
        order = exchange.create_market_buy_order(symbol, qty)
        active_trades[symbol] = {"coin": coin, "entry": price, "amount": qty, "invested": usdt_want, "tp": cfg['tp'], "sl": cfg['sl'], "emoji": cfg['emoji']}
        save_trades(active_trades)
        await update.message.reply_text(f"BOUGHT {coin}\nPrice ${price}\nTP +{cfg['tp']}% SL -{cfg['sl']}%")
    except Exception as e:
        await update.message.reply_text(f"Buy failed: {e}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Use /sell pepe or /sell all")
            return
        target = context.args[0].upper()
        bal = exchange.fetch_balance()
        if target == "ALL":
            for k,cfg in CONFIG.items():
                base = cfg['symbol'].split('/')[0]
                free = bal.get(base, {}).get('free', 0)
                if free > 0:
                    try:
                        exchange.create_market_sell_order(cfg['symbol'], free)
                        if cfg['symbol'] in active_trades:
                            del active_trades[cfg['symbol']]
                    except: pass
            save_trades(active_trades)
            await update.message.reply_text("Sold ALL")
        else:
            if target not in CONFIG:
                await update.message.reply_text("Unknown")
                return
            cfg = CONFIG[target]
            base = cfg['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free > 0:
                exchange.create_market_sell_order(cfg['symbol'], free)
                if cfg['symbol'] in active_trades:
                    del active_trades[cfg['symbol']]
                save_trades(active_trades)
                await update.message.reply_text(f"Sold {target}")
            else:
                await update.message.reply_text(f"No {target}")
    except Exception as e:
        await update.message.reply_text(f"Sell fail: {e}")

def monitor():
    global daily_pnl
    while True:
        try:
            if daily_pnl['date'] != str(date.today()):
                daily_pnl = {"date": str(date.today()), "pnl": 0.0}
            for symbol, t in list(active_trades.items()):
                price, _ = get_ticker(symbol)
                if not price: continue
                pnl_pct = (price - t['entry']) / t['entry'] * 100
                if pnl_pct >= t['tp'] or pnl_pct <= -t['sl']:
                    try:
                        bal = exchange.fetch_balance()
                        base = symbol.split('/')[0]
                        free = bal.get(base, {}).get('free', 0)
                        if free > 0:
                            exchange.create_market_sell_order(symbol, free)
                            daily_pnl['pnl'] += pnl_pct
                        if symbol in active_trades:
                            del active_trades[symbol]
                        save_trades(active_trades)
                    except Exception as e:
                        print(f"Auto sell err {e}")
            time.sleep(4)
        except Exception as e:
            print(f"Monitor err {e}")
            time.sleep(5)

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    print("SAFE BOT STARTED")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("sell", sell_cmd))
    app.run_polling()
