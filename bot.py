import os, time, threading
import ccxt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET")

# === MEME COINS LIST ===
MEME_COINS = {
    "PEPE": {"symbol": "PEPE/USDT", "tp": 10.0, "sl": 3.0, "decimals": 8},
    "DOGE": {"symbol": "DOGE/USDT", "tp": 8.0, "sl": 2.5, "decimals": 6},
    "SHIB": {"symbol": "SHIB/USDT", "tp": 10.0, "sl": 3.0, "decimals": 8},
    "BONK": {"symbol": "BONK/USDT", "tp": 15.0, "sl": 4.0, "decimals": 8},
    "FLOKI": {"symbol": "FLOKI/USDT", "tp": 12.0, "sl": 3.5, "decimals": 6},
    "WIF": {"symbol": "WIF/USDT", "tp": 12.0, "sl": 3.5, "decimals": 4},
    "BTC": {"symbol": "BTC/USDT", "tp": 5.0, "sl": 1.5, "decimals": 6},
}

active_trades = {}

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "MEME COIN BOT IS LIVE! 🐸🐶🚀"

def get_price(symbol):
    try:
        return exchange.fetch_ticker(symbol)['last']
    except:
        return None

# === TELEGRAM COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = """🔥 *MEME COIN BOT V2* 🔥

*Available Coins:*
🐸 PEPE - /buy 5 pepe
🐕 DOGE - /buy 5 doge
🐶 SHIB - /buy 5 shib
🐾 BONK - /buy 5 bonk
🔥 FLOKI - /buy 5 floki
🎩 WIF - /buy 5 wif
₿ BTC - /buy 5 btc

*Commands:*
/balance - check wallet
/status - check PnL
/sell pepe - sell pepe
/sell all - sell everything

*Auto TP/SL:*
Meme: +10-15% TP, -3-4% SL
BTC: +5% TP, -1.5% SL

Bot auto-sells when TP/SL hits!
"""
    await update.message.reply_text(txt, parse_mode='Markdown')

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt = bal['USDT']['free']
        msg = f"💰 *Balance*\nUSDT: ${usdt:.4f}\n\n"
        for coin, info in MEME_COINS.items():
            base = info['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free > 0:
                price = get_price(info['symbol'])
                value = free * price if price else 0
                msg += f"{coin}: {free} (~${value:.2f})\n"
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_trades:
        await update.message.reply_text("📭 No active trades")
        return
    msg = "📊 *ACTIVE TRADES*\n\n"
    for sym, t in active_trades.items():
        now = get_price(sym)
        if now:
            pnl = (now - t['entry']) / t['entry'] * 100
            coin = t['coin']
            msg += f"*{coin}* {sym}\nEntry: {t['entry']}\nNow: {now}\nPnL: {pnl:.2f}%\nTP:+{t['tp']}% SL:-{t['sl']}%\nAmount: {t['amount']}\n\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 2:
            await update.message.reply_text("Use: /buy 5 pepe")
            return
        usdt_amount = float(context.args[0])
        coin_name = context.args[1].upper()
        
        if coin_name not in MEME_COINS:
            await update.message.reply_text(f"Coin {coin_name} not supported. Use: {', '.join(MEME_COINS.keys())}")
            return
        
        info = MEME_COINS[coin_name]
        symbol = info['symbol']
        
        price = get_price(symbol)
        if not price:
            await update.message.reply_text("Can't get price")
            return
        
        qty = usdt_amount / price
        
        # MEXC needs proper precision for meme coins
        try:
            # Try market buy with quote amount (better for meme)
            order = exchange.create_market_buy_order(symbol, qty)
        except Exception as e:
            # Fallback: buy with cost
            order = exchange.create_order(symbol, 'market', 'buy', qty, None, {'quoteOrderQty': usdt_amount})
        
        active_trades[symbol] = {
            'entry': price,
            'amount': qty,
            'tp': info['tp'],
            'sl': info['sl'],
            'coin': coin_name
        }
        
        await update.message.reply_text(
            f"✅ *BOUGHT {coin_name}*\n"
            f"Qty: {qty}\nPrice: {price}\nCost: ${usdt_amount}\n\n"
            f"🤖 Auto: TP +{info['tp']}% (${price*(1+info['tp']/100)})\n"
            f"SL -{info['sl']}% (${price*(1-info['sl']/100)})",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Buy failed: {e}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Use: /sell pepe or /sell all")
            return
        target = context.args[0].upper()
        bal = exchange.fetch_balance()
        
        if target == "ALL":
            for coin, info in MEME_COINS.items():
                base = info['symbol'].split('/')[0]
                free = bal.get(base, {}).get('free', 0)
                if free > 0:
                    exchange.create_market_sell_order(info['symbol'], free)
                    if info['symbol'] in active_trades:
                        del active_trades[info['symbol']]
            await update.message.reply_text("✅ Sold ALL")
        else:
            if target not in MEME_COINS:
                await update.message.reply_text("Unknown coin")
                return
            info = MEME_COINS[target]
            base = info['symbol'].split('/')[0]
            free = bal.get(base, {}).get('free', 0)
            if free > 0:
                exchange.create_market_sell_order(info['symbol'], free)
                if info['symbol'] in active_trades:
                    del active_trades[info['symbol']]
                await update.message.reply_text(f"✅ Sold {free} {target} ~${free*get_price(info['symbol']):.2f}")
            else:
                await update.message.reply_text(f"No {target} balance")
    except Exception as e:
        await update.message.reply_text(f"Sell failed: {e}")

def monitor_trades():
    while True:
        try:
            for symbol, trade in list(active_trades.items()):
                now = get_price(symbol)
                if not now:
                    continue
                pnl = (now - trade['entry']) / trade['entry'] * 100
                if pnl >= trade['tp'] or pnl <= -trade['sl']:
                    try:
                        bal = exchange.fetch_balance()
                        base = symbol.split('/')[0]
                        free = bal.get(base, {}).get('free', 0)
                        if free > 0:
                            exchange.create_market_sell_order(symbol, free)
                            print(f"AUTO SOLD {symbol} PnL {pnl:.2f}%")
                        if symbol in active_trades:
                            del active_trades[symbol]
                    except Exception as e:
                        print(f"Auto sell error {symbol}: {e}")
            time.sleep(3)  # Faster check for meme coins!
        except:
            time.sleep(5)

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_trades, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("sell", sell_cmd))
    print("MEME COIN BOT STARTED 🐸🚀")
    app.run_polling()
