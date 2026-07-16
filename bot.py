import os
import asyncio
import ccxt
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")
SYMBOL = "BTC/USDT"
TP = 5.0
SL = 1.5

# === EXCHANGE ===
exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True,
})

# === FLASK FOR RENDER ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Live! No Conflict!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# === TELEGRAM COMMANDS ===
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Bot Online! No more Conflict!\n\nCommands:\n/balance - Check USDT\n/price - BTC Price\n/buy 5 usdt - Buy BTC\n/sell - Sell all BTC")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt_free = bal.get('USDT', {}).get('free', 0)
        btc_free = bal.get('BTC', {}).get('free', 0)
        await update.message.reply_text(f"💰 Balance:\nUSDT: ${usdt_free:.2f}\nBTC: {btc_free:.8f}")
    except Exception as e:
        await update.message.reply_text(f"❌ Balance error: {e}")

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        await update.message.reply_text(f"📈 {SYMBOL}: ${ticker['last']:.2f}")
    except Exception as e:
        await update.message.reply_text(f"❌ Price error: {e}")

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Use: /buy 5 usdt")
            return
        text = " ".join(context.args).lower().replace("usdt","").strip()
        usd_amount = float(text)
        
        await update.message.reply_text(f"⏳ Buying ${usd_amount} of {SYMBOL}...")
        
        # Get price to calculate amount
        ticker = exchange.fetch_ticker(SYMBOL)
        price = ticker['last']
        amount = usd_amount / price

        # REAL BUY
        order = exchange.create_market_buy_order(SYMBOL, amount)
        await update.message.reply_text(f"✅ Bought! Order ID:\n{order['id']}\nTP: {TP}% | SL: {SL}%")
    except Exception as e:
        await update.message.reply_text(f"❌ Buy failed: {e}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Selling all BTC...")
        bal = exchange.fetch_balance()
        btc_free = bal.get('BTC', {}).get('free', 0)
        if btc_free < 0.000001:
            await update.message.reply_text("❌ No BTC to sell")
            return
        order = exchange.create_market_sell_order(SYMBOL, btc_free)
        await update.message.reply_text(f"✅ Sold! Order ID: {order['id']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Sell failed: {e}")

# === MAIN ===
async def main():
    # THIS FIXES THE CONFLICT ERROR FOREVER
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("price", price_cmd))
    application.add_handler(CommandHandler("buy", buy_cmd))
    application.add_handler(CommandHandler("sell", sell_cmd))

    # Delete any old webhook / pending updates that cause Conflict
    await application.bot.delete_webhook(drop_pending_updates=True)
    print("Webhook deleted, starting polling...")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    
    print("Bot polling started - No Conflict!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Start Flask in background thread for Render port
    Thread(target=run_flask, daemon=True).start()
    # Start bot
    asyncio.run(main())
