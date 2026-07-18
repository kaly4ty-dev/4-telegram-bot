import os, time, threading, json
import ccxt
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask

BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
MEXC_API_KEY = os.getenv('MEXC_API_KEY')
MEXC_SECRET = os.getenv('MEXC_SECRET') or os.getenv('MEXC_API_SECRET')

print(f"ENV: BOT_TOKEN={bool(BOT_TOKEN)} KEY={bool(MEXC_API_KEY)} SECRET={bool(MEXC_SECRET)}")

if not BOT_TOKEN:
    print("ERROR: Set BOT_TOKEN or TELEGRAM_TOKEN in Render!")
    exit(1)

CONFIG = {
    "BTC":  {"symbol": "BTC/USDT",  "tp": 3.0,  "sl": 1.0, "max_usdt": 5, "emoji": "₿"},
    "PEPE": {"symbol": "PEPE/USDT", "tp": 8.0,  "sl": 2.0, "max_usdt": 3, "emoji": "🐸"},
    "DOGE": {"symbol": "DOGE/USDT", "tp": 8.0,  "sl": 2.0, "max_usdt": 3, "emoji": "🐕"},
    "SHIB": {"symbol": "SHIB/USDT", "tp": 8.0,  "sl": 2.0, "max_usdt": 3, "emoji": "🐶"},
}

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

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "SAFE MEME+BTC Bot LIVE 🛡 TP: BTC 3%/1% PEPE 8%/2%"

def get_ticker(symbol):
    try:
        t = exchange.fetch_ticker(symbol)
        return t['last'], t.get('quoteVolume', 0)
    except:
        return None, 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡 SAFE BOT - WON'T LOSE MUCH!\n\n"
        "BTC: TP +3% SL -1% Max $5\n"
        "PEPE/DOGE/SHIB: TP +8% SL -2% Max $3\n"
        "Daily STOP if -5%\n\n"
        "/buy 3 btc\n"
        "/buy 2 pepe\n"
        "/buy 2 doge\n"
        "/buy 2 shib\n"
        "/balance\n/status\n/price\n/sell all"
    )

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📈 Prices\n"
    for k in ["BTC", "PEPE", "DOGE", "SHIB"]:
        p, vol = get_ticker(CONFIG[k]['symbol'])
        if p:
            msg += f"{k}: ${p} Vol:{vol/1e6:.1f}M\n"
    await update.message.reply_text(msg)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt = bal.get('USDT', {}).get('free', 0)
        msg = f"💰 USDT: ${usdt:.4f}\n"
        for k, cfg in CONFIG.items():
            base = cfg['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free > 0:
                p,_ = get_ticker(cfg['symbol'])
                v = free * p if p else 0
                msg += f"{k}: {free} (~${v:.2f})\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Error {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_trades:
        await update.message.reply_text("📭 No trades. /buy 2 pepe")
        return
    msg = "📊 Active\n"
    for sym, t in active_trades.items():
        now,_ = get_ticker(sym)
        if now:
            pnl = (now - t['entry']) / t['entry'] * 100
            msg += f"{t['coin']} Entry:{t['entry']} Now:{now} PnL:{pnl:+.2f}% TP:{t['tp']}% SL:{t['sl']}%\n\n"
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
        cfg = CONFIG[coin]
        if usdt_want > cfg['max_usdt']:
            await update.message.reply_text(f"Max for {coin} is ${cfg['max_usdt']}")
            return
        bal = exchange.fetch_balance()
        free_usdt = bal.get('USDT', {}).get('free', 0)
        if free_usdt < usdt_want:
            await update.message.reply_text(f"Need ${usdt_want} have ${free_usdt:.2f}")
            return
        price, vol = get_ticker(cfg['symbol'])
        if not price:
            await update.message.reply_text("No price")
            return
        if cfg['symbol'] in active_trades:
            await update.message.reply_text(f"Already have {coin}. /sell {coin.lower()} first")
            return
        await update.message.reply_text(f"Buying ${usdt_want} {coin} @ {price}...")
        qty = usdt_want / price
        order = exchange.create_market_buy_order(cfg['symbol'], qty)
        active_trades[cfg['symbol']] = {"coin": coin, "entry": price, "amount": qty, "invested": usdt_want, "tp": cfg['tp'], "sl": cfg['sl']}
        save_trades(active_trades)
        await update.message.reply_text(f"✅ BOUGHT {coin} @ ${price} TP +{cfg['tp']}% SL -{cfg['sl']}%")
    except Exception as e:
        await update.message.reply_text(f"Buy fail: {e}")

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
            await update.message.reply_text("✅ Sold ALL")
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
                await update.message.reply_text(f"✅ Sold {target}")
            else:
                await update.message.reply_text(f"No {target}")
    except Exception as e:
        await update.message.reply_text(f"Sell fail: {e}")

def monitor():
    while True:
        try:
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
    flask_app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

if __name__ == '__main__':
    import threading
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    print("SAFE BOT STARTED 🛡")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("sell", sell_cmd))
    app.run_polling()
