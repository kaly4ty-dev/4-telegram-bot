import os
import asyncio
import ccxt
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")
SYMBOL = "BTC/USDT"
TP_PERCENT = 5.0
SL_PERCENT = 1.5

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True,
})

# Store trade info
trade_info = {
    "entry_price": None,
    "btc_amount": 0,
    "active": False
}

app = Flask(__name__)
@app.route('/')
def home():
    return f"Bot Live! Auto TP {TP_PERCENT}% / SL {SL_PERCENT}%"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = f"Active: {trade_info['active']}\nEntry: ${trade_info['entry_price']}" if trade_info['active'] else "No active trade"
    await update.message.reply_text(f"🚀 Auto TP/SL Bot Live!\n\nTP: +{TP_PERCENT}%\nSL: -{SL_PERCENT}%\n\n{status}\n\nCommands:\n/balance\n/price\n/buy 5 usdt\n/sell\n/status")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trade_info['active']:
        await update.message.reply_text("💤 No active trade. Use /buy 5 usdt")
        return
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        curr = ticker['last']
        entry = trade_info['entry_price']
        pnl = (curr - entry) / entry * 100
        await update.message.reply_text(f"📊 Active Trade:\nEntry: ${entry:.2f}\nNow: ${curr:.2f}\nPnL: {pnl:+.2f}%\nAmount: {trade_info['btc_amount']:.8f} BTC\n\nTP: +{TP_PERCENT}% | SL: -{SL_PERCENT}%")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt = bal.get('USDT', {}).get('free', 0)
        btc = bal.get('BTC', {}).get('free', 0)
        await update.message.reply_text(f"💰 Balance:\nUSDT: ${usdt:.2f}\nBTC: {btc:.8f}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        await update.message.reply_text(f"📈 {SYMBOL}: ${ticker['last']:.2f}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Use: /buy 5 usdt  or  /buy 23 usdt")
            return
        text = " ".join(context.args).lower().replace("usdt","").strip()
        usd_amount = float(text)
        await update.message.reply_text(f"⏳ Buying ${usd_amount} of {SYMBOL}...")

        ticker = exchange.fetch_ticker(SYMBOL)
        price = ticker['last']
        amount = usd_amount / price
        # Round amount to avoid precision error
        amount = float(exchange.amount_to_precision(SYMBOL, amount))

        order = exchange.create_market_buy_order(SYMBOL, amount)
        
        # Save trade
        trade_info["entry_price"] = price
        trade_info["btc_amount"] = amount
        trade_info["active"] = True

        await update.message.reply_text(f"✅ Bought {amount:.8f} BTC @ ${price:.2f}\nOrder: {order['id']}\n\n🤖 Auto Sell Armed:\nTP: +{TP_PERCENT}% = ${price*(1+TP_PERCENT/100):.2f}\nSL: -{SL_PERCENT}% = ${price*(1-SL_PERCENT/100):.2f}")
    except Exception as e:
        await update.message.reply_text(f"❌ Buy failed: {e}")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        btc_free = bal.get('BTC', {}).get('free', 0)
        if btc_free < 0.000001:
            await update.message.reply_text("❌ No BTC to sell")
            trade_info["active"] = False
            return
        btc_free = float(exchange.amount_to_precision(SYMBOL, btc_free))
        await update.message.reply_text(f"⏳ Selling {btc_free:.8f} BTC...")
        order = exchange.create_market_sell_order(SYMBOL, btc_free)
        trade_info["active"] = False
        trade_info["entry_price"] = None
        trade_info["btc_amount"] = 0
        await update.message.reply_text(f"✅ Sold! Order: {order['id']}\nAuto TP/SL disarmed.")
    except Exception as e:
        await update.message.reply_text(f"❌ Sell failed: {e}")

# AUTO TP/SL LOOP
async def auto_monitor(app_instance):
    await asyncio.sleep(10)
    print("Auto TP/SL monitor started")
    while True:
        try:
            if trade_info["active"] and trade_info["entry_price"]:
                ticker = exchange.fetch_ticker(SYMBOL)
                curr_price = ticker['last']
                entry = trade_info["entry_price"]
                pnl = (curr_price - entry) / entry * 100
                
                print(f"Monitor: Entry ${entry:.2f} Now ${curr_price:.2f} PnL {pnl:.2f}%")

                if pnl >= TP_PERCENT or pnl <= -SL_PERCENT:
                    # TP or SL Hit!
                    bal = exchange.fetch_balance()
                    btc_free = bal.get('BTC', {}).get('free', 0)
                    if btc_free > 0.000001:
                        btc_free = float(exchange.amount_to_precision(SYMBOL, btc_free))
                        order = exchange.create_market_sell_order(SYMBOL, btc_free)
                        
                        reason = "TAKE PROFIT 🎯" if pnl >= TP_PERCENT else "STOP LOSS 🛑"
                        msg = f"🤖 {reason} HIT!\n\nEntry: ${entry:.2f}\nExit: ${curr_price:.2f}\nPnL: {pnl:+.2f}%\nSold {btc_free:.8f} BTC\nOrder: {order['id']}"
                        
                        # Send to all? For now we try to send via bot to owner - you need to store chat_id
                        # Simplest: log and disarm. User can check /status
                        print(msg)
                        # If you want telegram alert, we need chat_id - we'll broadcast via bot if possible
                        try:
                            # This will send to last chat - we need to save chat_id in trade_info
                            if trade_info.get("chat_id"):
                                await app_instance.bot.send_message(chat_id=trade_info["chat_id"], text=msg)
                        except:
                            pass

                        trade_info["active"] = False
                        trade_info["entry_price"] = None
                        trade_info["btc_amount"] = 0
            await asyncio.sleep(30)
        except Exception as e:
            print(f"Monitor error: {e}")
            await asyncio.sleep(30)

async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("price", price_cmd))
    application.add_handler(CommandHandler("buy", buy_cmd))
    application.add_handler(CommandHandler("sell", sell_cmd))

    # Save chat_id on buy for auto alerts
    original_buy = buy_cmd
    async def buy_wrapper(update, context):
        if update.effective_chat:
            trade_info["chat_id"] = update.effective_chat.id
        await original_buy(update, context)
    application.add_handler(CommandHandler("buy", buy_wrapper))

    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    # Start auto monitor
    asyncio.create_task(auto_monitor(application))
    
    print("Bot Live with Auto TP/SL")
    await asyncio.Event().wait()

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
