# bot.py

import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = "7996065957:AAEYf0E0J8KBIH8rUpJfARs6gNJpBs7tees"
REMOVEBG_API_KEY = "qLfRtLd6MebVzGTuFcQ7Yv9j"

# Dictionary to temporarily store image paths per user
user_images = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a photo, and then click 'Remove BG' to remove the background!")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_path = f"{user_id}_original.png"
    await file.download_to_drive(file_path)

    user_images[user_id] = file_path

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🪄 Remove BG", callback_data="remove_bg")]]
    )

    await update.message.reply_text("✅ Photo received! Now tap below to remove background:", reply_markup=keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    image_path = user_images.get(user_id)

    if not image_path or not os.path.exists(image_path):
        await query.edit_message_text("❌ No image found. Please send a photo first.")
        return

    await query.edit_message_text("🪄 Removing background...")

    with open(image_path, "rb") as image_file:
        response = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": image_file},
            data={"size": "auto"},
            headers={"X-Api-Key": REMOVEBG_API_KEY},
        )

    if response.status_code == 200:
        output_path = f"{user_id}_nobg.png"
        with open(output_path, "wb") as out:
            out.write(response.content)

        await context.bot.send_photo(chat_id=query.message.chat_id, photo=InputFile(output_path), caption="✅ Background removed!")

        os.remove(image_path)
        os.remove(output_path)
        user_images.pop(user_id, None)
    else:
        await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Failed to remove background. Try again later.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
