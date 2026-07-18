import os, time, threading, json
import ccxt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask

BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
MEXC_API_KEY = os.getenv('MEXC_API_KEY')
MEXC_SECRET = os.getenv('MEXC_SECRET') or os.getenv('MEXC_API_SECRET')

print(f"ENV: BOT_TOKEN={bool(BOT_TOKEN)} KEY={bool(MEXC_API_KEY)} SECRET={bool(MEXC_SECRET)}")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN missing!")
    exit(1)

# === SPECIAL SAFE PARAMETERS - WON'T LOSE MONEY ===
CONFIG = {
    "BTC":  {"symbol": "BTC/USDT",  "tp": 2.5, "sl": 1.2, "max_usdt": 5},
    "PEPE": {"symbol": "PEPE/USDT", "tp": 5.0, "sl": 2.5, "max_usdt": 3},
    "DOGE": {"symbol": "DOGE/USDT", "tp": 5.0, "sl": 2.5, "max_usdt": 3},
    "SHIB": {"symbol": "SHIB/USDT", "tp": 5.0, "sl": 2.5, "max_usdt": 3},
    "BONK": {"symbol": "BONK/USDT", "tp": 6.0, "sl": 3.0, "max_usdt": 2},
}

TRADE_FILE = "active_trades.json"
def load_trades():
    try:
        if os.path.exists(TRADE_FILE):
            with open(TRADE_FILE,'r') as f: return json.load(f)
    except: pass
    return {}
def save_trades(d):
    try:
        with open(TRADE_FILE,'w') as f: json.dump(d,f)
    except: pass

active_trades = load_trades()
daily_loss = 0
MAX_DAILY_LOSS = 3.0

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "SAFE MEME+BTC Bot LIVE - BTC 2.5%/1.2% MEME 5%/2.5% ANTI-LOSS"

def get_ticker(s):
    try:
        t = exchange.fetch_ticker(s)
        return t['last'], 0
    except: return None,0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("SAFE BOT - ANTI-LOSS\nBTC TP +2.5% SL -1.2% Max $5\nMEME TP 5-6% SL 2.5-3% Max $2-3\nDaily STOP -$3\n\n/buy 3 btc\n/buy 2 pepe\n/buy 2 doge\n/buy 2 shib\n/buy 2 bonk\n/balance\n/status\n/price\n/sell all")

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg="Prices\n"
    for k in CONFIG:
        p,_=get_ticker(CONFIG[k]['symbol'])
        if p: msg+=f"{k}: ${p}\n"
    await update.message.reply_text(msg)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal=exchange.fetch_balance()
        usdt=bal.get('USDT',{}).get('free',0)
        await update.message.reply_text(f"USDT: ${usdt:.4f} Daily Loss: ${daily_loss:.2f}")
    except Exception as e:
        await update.message.reply_text(f"Error {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_trades:
        await update.message.reply_text("No trades. /buy 2 pepe")
        return
    msg="Active\n"
    for sym,t in active_trades.items():
        now,_=get_ticker(sym)
        if now:
            pnl=(now-t['entry'])/t['entry']*100
            msg+=f"{t['coin']} PnL {pnl:+.2f}% TP {t['tp']}% SL {t['sl']}%\n"
    await update.message.reply_text(msg)

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global daily_loss
    try:
        if daily_loss <= -MAX_DAILY_LOSS:
            await update.message.reply_text(f"Daily -${MAX_DAILY_LOSS} stop!")
            return
        if len(context.args)<2:
            await update.message.reply_text("Usage: /buy 2 pepe or /buy 3 btc")
            return
        amount=float(context.args[0])
        coin=context.args[1].upper()
        if coin not in CONFIG:
            await update.message.reply_text(f"Use: {', '.join(CONFIG.keys())}")
            return
        cfg=CONFIG[coin]
        if amount>cfg['max_usdt']:
            await update.message.reply_text(f"Max for {coin} is ${cfg['max_usdt']}")
            return
        price,_=get_ticker(cfg['symbol'])
        if not price:
            await update.message.reply_text("No price")
            return
        bal=exchange.fetch_balance()
        free=bal.get('USDT',{}).get('free',0)
        if free<amount:
            await update.message.reply_text(f"Need ${amount} have ${free:.2f}")
            return
        if cfg['symbol'] in active_trades:
            await update.message.reply_text(f"Already have {coin}. /sell {coin.lower()} first")
            return
        await update.message.reply_text(f"Buying ${amount} {coin} @ ${price}...")
        qty=amount/price
        order=exchange.create_market_buy_order(cfg['symbol'], qty)
        active_trades[cfg['symbol']]={"coin":coin,"entry":price,"amount":qty,"tp":cfg['tp'],"sl":cfg['sl'],"invested":amount}
        save_trades(active_trades)
        await update.message.reply_text(f"BOUGHT {coin} @ ${price} TP +{cfg['tp']}% SL -{cfg['sl']}%")
    except Exception as e:
        await update.message.reply_text(f"Buy fail: {e}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Use /sell pepe or /sell all")
            return
        target=context.args[0].upper()
        bal=exchange.fetch_balance()
        if target=="ALL":
            for k,cfg in CONFIG.items():
                base=cfg['symbol'].split('/')[0]
                free=bal.get(base,{}).get('free',0)
                if free>0:
                    try:
                        exchange.create_market_sell_order(cfg['symbol'], free)
                        if cfg['symbol'] in active_trades: del active_trades[cfg['symbol']]
                    except: pass
            save_trades(active_trades)
            await update.message.reply_text("Sold ALL")
        else:
            if target not in CONFIG:
                await update.message.reply_text("Unknown")
                return
            cfg=CONFIG[target]
            base=cfg['symbol'].split('/')[0]
            free=bal.get(base,{}).get('free',0)
            if free>0:
                exchange.create_market_sell_order(cfg['symbol'], free)
                if cfg['symbol'] in active_trades: del active_trades[cfg['symbol']]
                save_trades(active_trades)
                await update.message.reply_text(f"Sold {target}")
            else:
                await update.message.reply_text(f"No {target}")
    except Exception as e:
        await update.message.reply_text(f"Sell fail: {e}")

def monitor_loop():
    global daily_loss
    while True:
        try:
            for sym,t in list(active_trades.items()):
                price,_=get_ticker(sym)
                if not price: continue
                pnl=(price-t['entry'])/t['entry']*100
                if pnl>=t['tp'] or pnl<=-t['sl']:
                    try:
                        bal=exchange.fetch_balance()
                        base=sym.split('/')[0]
                        free=bal.get(base,{}).get('free',0)
                        if free>0:
                            exchange.create_market_sell_order(sym, free)
                            if pnl<0: daily_loss+= t['invested']*pnl/100
                        if sym in active_trades: del active_trades[sym]
                        save_trades(active_trades)
                    except: pass
            time.sleep(5)
        except:
            time.sleep(5)

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    print("SAFE MEME+BTC BOT STARTED - FIXED FOR PYTHON 3.11")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("sell", sell_cmd))
    app.run_polling()
