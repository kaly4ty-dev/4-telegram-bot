import os
import ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
MEXC_KEY = os.getenv("MEXC_API_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")

print(f"BOT_TOKEN exists: {bool(BOT_TOKEN)}")
print(f"MEXC_KEY exists: {bool(MEXC_KEY)}")

# Setup MEXC
exchange = ccxt.mexc({
    'apiKey': MEXC_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True
})

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *Trading Bot Ready!*\n\n"
        "Commands:\n"
        "/balance - Check your MEXC USDT balance\n"
        "/price - Check BTC & SOL prices\n"
        "/status - Bot status\n"
        "/help - Help",
        parse_mode='Markdown'
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt = 0
        btc = 0
        sol = 0
        if 'USDT' in bal and bal['USDT']:
            usdt = bal['USDT'].get('free', 0) or 0
        if 'BTC' in bal and bal['BTC']:
            btc = bal['BTC'].get('free', 0) or 0
        if 'SOL' in bal and bal['SOL']:
            sol = bal['SOL'].get('free', 0) or 0
        await update.message.reply_text(f"💰 *MEXC Balance:*\nUSDT: ${usdt:.2f}\nBTC: {btc}\nSOL: {sol}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc_ticker = exchange.fetch_ticker('BTC/USDT')
        sol_ticker = exchange.fetch_ticker('SOL/USDT')
        await update.message.reply_text(f"📈 *Prices:*\nBTC: ${btc_ticker['last']:.2f}\nSOL: ${sol_ticker['last']:.2f}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 Bot is running on your laptop!\nMode: LIVE with MEXC\nTP: 5% | SL: 1.5%")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/balance - check money\n/price - check prices\n/start - restart")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set! Use: set BOT_TOKEN=your_token")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_cmd))
    print("Bot started with TRADING logic...")
    app.run_polling()

if __name__ == "__main__":
    main()

