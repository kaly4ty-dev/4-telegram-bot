
import os
import ccxt
import time
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ====== SAFE ENV LOADING ======
BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
MEXC_API_KEY = os.getenv('MEXC_API_KEY')
MEXC_SECRET = os.getenv('MEXC_SECRET') or os.getenv('MEXC_API_SECRET')

print(f"BOT_TOKEN: {bool(BOT_TOKEN)}")
print(f"MEXC_API_KEY: {bool(MEXC_API_KEY)}")
print(f"MEXC_SECRET: {bool(MEXC_SECRET)}")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN missing in Render Env")
    exit(1)

# ====== SPECIAL SAFE PARAMETERS - ANTI-LOSS ======
# BTC: Very safe, low TP/SL
# MEME: Slightly higher but still conservative
CONFIG = {
    "BTC": {"symbol": "BTC/USDT", "tp": 2.0, "sl": 1.0, "max_usdt": 5},
    "PEPE": {"symbol": "PEPE/USDT", "tp": 5.0, "sl": 2.0, "max_usdt": 3},
    "DOGE": {"symbol": "DOGE/USDT", "tp": 4.5, "sl": 2.0, "max_usdt": 3},
    "SHIB": {"symbol": "SHIB/USDT", "tp": 4.5, "sl": 2.0, "max_usdt": 3},
}

active_trades = {}
daily_loss = 0
MAX_DAILY_LOSS = 2.0 # stop if lose $2 in a day

exchange = None
if MEXC_API_KEY and MEXC_SECRET:
    exchange = ccxt.mexc({
        'apiKey': MEXC_API_KEY,
        'secret': MEXC_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

# Flask for Render Web Service
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "SAFE BOT LIVE - BTC + MEME - TP 2-5% SL 1-2%"

def get_price(symbol):
    try:
        if exchange:
            return exchange.fetch_ticker(symbol)['last']
    except:
        pass
    return None

def get_balance():
    try:
        if exchange:
            bal = exchange.fetch_balance()
            return bal['USDT']['free']
    except Exception as e:
        print(f"Balance error {e}")
    return 0

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🛡️ *SPECIAL SAFE BOT - ANTI-LOSS*\n\n"
        "I won't let you lose money!\n"
        "BTC: TP +2% SL -1% (very safe)\n"
        "PEPE/DOGE/SHIB: TP +4.5-5% SL -2% (conservative)\n"
        "Max $3-5 per trade | Daily stop if -$2 loss\n\n"
        "*Commands:*\n"
        "/buy 3 btc - Buy $3 BTC\n"
        "/buy 2 pepe - Buy $2 PEPE\n"
        "/buy 2 doge\n"
        "/buy 2 shib\n"
        "/balance - Check money\n"
        "/status - Check trades + PnL\n"
        "/price - Check BTC/PEPE price\n"
        "/sell btc /sell pepe /sell all\n\n"
        "Start with SMALL: /buy 2 pepe"
    )
    await update.message.reply_text(txt, parse_mode='Markdown')

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📈 Prices:\n"
    for coin, cfg in CONFIG.items():
        p = get_price(cfg['symbol'])
        if p:
            msg += f"{coin}: ${p}\n"
    await update.message.reply_text(msg)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usdt = get_balance()
        await update.message.reply_text(f"💰 USDT Free: ${usdt:.4f}\nDaily PnL: ${daily_loss:.2f}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_trades:
        await update.message.reply_text("📭 No active trades. Your BTC is safe! Use /buy 2 pepe")
        return
    msg = "📊 Active Trades:\n\n"
    for sym, t in active_trades.items():
        now = get_price(sym)
        if now:
            pnl = (now - t['entry']) / t['entry'] * 100
            msg += f"{t['coin']} {sym}\nEntry: {t['entry']}\nNow: {now}\nPnL: {pnl:+.2f}%\nTP +{t['tp']}% SL -{t['sl']}%\n\n"
    await update.message.reply_text(msg)

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global daily_loss
    try:
        if daily_loss <= -MAX_DAILY_LOSS:
            await update.message.reply_text(f"🛑 Daily loss limit -${MAX_DAILY_LOSS} reached! Stop today to protect money.")
            return
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /buy 2 pepe  (amount + coin)")
            return
        try:
            amount = float(context.args[0])
        except:
            await update.message.reply_text("First must be number: /buy 2 pepe")
            return
        coin = context.args[1].upper()
        if coin not in CONFIG:
            await update.message.reply_text(f"Unknown coin. Use: {', '.join(CONFIG.keys())}")
            return
        
        cfg = CONFIG[coin]
        if amount > cfg['max_usdt']:
            await update.message.reply_text(f"🛡️ Safety limit! Max for {coin} is ${cfg['max_usdt']}. You tried ${amount}")
            return
        if amount < 1:
            await update.message.reply_text("Min $1")
            return

        price = get_price(cfg['symbol'])
        if not price:
            await update.message.reply_text("Can't get price, try again")
            return

        usdt_free = get_balance()
        if usdt_free < amount:
            await update.message.reply_text(f"❌ Need ${amount} but you have ${usdt_free:.2f}")
            return

        # Check if already have this coin
        if cfg['symbol'] in active_trades:
            await update.message.reply_text(f"Already have {coin} active. Wait TP/SL or /sell {coin.lower()}")
            return

        await update.message.reply_text(f"⏳ Buying ${amount} {coin} @ ${price}...")

        qty = amount / price
        # REAL BUY
        order = exchange.create_market_buy_order(cfg['symbol'], qty)

        active_trades[cfg['symbol']] = {
            "coin": coin,
            "entry": price,
            "amount": qty,
            "tp": cfg['tp'],
            "sl": cfg['sl'],
            "invested": amount
        }

        await update.message.reply_text(
            f"✅ BOUGHT {coin}\nQty: {qty:.6f}\nPrice: ${price}\n"
            f"🛡️ Auto TP +{cfg['tp']}% = ${price*(1+cfg['tp']/100):.4f}\n"
            f"SL -{cfg['sl']}% = ${price*(1-cfg['sl']/100):.4f}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Buy failed: {e}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global daily_loss
    try:
        if not context.args:
            await update.message.reply_text("Use /sell pepe or /sell all")
            return
        target = context.args[0].upper()
        if target == "ALL":
            bal = exchange.fetch_balance()
            for coin, cfg in CONFIG.items():
                base = cfg['symbol'].split('/')[0]
                free = bal.get(base, {}).get('free', 0)
                if free > 0:
                    try:
                        exchange.create_market_sell_order(cfg['symbol'], free)
                        if cfg['symbol'] in active_trades:
                            del active_trades[cfg['symbol']]
                    except Exception as e:
                        print(f"Sell {coin} err {e}")
            await update.message.reply_text("✅ Sold ALL to USDT")
        else:
            if target not in CONFIG:
                await update.message.reply_text("Unknown coin")
                return
            cfg = CONFIG[target]
            bal = exchange.fetch_balance()
            base = cfg['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free > 0:
                # calc pnl for daily
                now = get_price(cfg['symbol'])
                if cfg['symbol'] in active_trades and now:
                    entry = active_trades[cfg['symbol']]['entry']
                    pnl_pct = (now - entry)/entry*100
                    invested = active_trades[cfg['symbol']]['invested']
                    pnl_usd = invested * pnl_pct/100
                    daily_loss += pnl_usd if pnl_usd < 0 else 0
                exchange.create_market_sell_order(cfg['symbol'], free)
                if cfg['symbol'] in active_trades:
                    del active_trades[cfg['symbol']]
                await update.message.reply_text(f"✅ Sold {free} {target}")
            else:
                await update.message.reply_text(f"No {target} to sell")
    except Exception as e:
        await update.message.reply_text(f"Sell failed: {e}")

def monitor_loop():
    global daily_loss
    while True:
        try:
            for sym, tr in list(active_trades.items()):
                now = get_price(sym)
                if not now:
                    continue
                pnl = (now - tr['entry']) / tr['entry'] * 100
                if pnl >= tr['tp'] or pnl <= -tr['sl']:
                    try:
                        bal = exchange.fetch_balance()
                        base = sym.split('/')[0]
                        free = bal.get(base, {}).get('free', 0)
                        if free > 0:
                            exchange.create_market_sell_order(sym, free)
                            # track loss
                            pnl_usd = tr['invested'] * pnl / 100
                            if pnl_usd < 0:
                                daily_loss += pnl_usd
                            print(f"AUTO SOLD {sym} {pnl:.2f}%")
                        if sym in active_trades:
                            del active_trades[sym]
                    except Exception as e:
                        print(f"Auto sell err {e}")
            time.sleep(5)
        except Exception as e:
            print(f"Monitor err {e}")
            time.sleep(5)

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    print("SAFE MEME+BTC BOT STARTED - TP 2-5% SL 1-2%")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("sell", sell_cmd))
    app.run_polling()
