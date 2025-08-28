import logging
import io
import requests

from telegram import Update, InputFile, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = "7996065957:AAGsFuTi0hkGxOa-IEbVsTLzaQ9R92s28xY"
REMOVE_BG_API_KEY = "gvoeRyGciuGqfAY6i8Hm5SLc" # Your remove.bg API Key
REMOVE_BG_API_URL = "https://api.remove.bg/v1.0/removebg"

# --- Constants for Reply Keyboard ---
BTN_REMOVE_BACKGROUND = "🖼️ Remove Background"
# --- State Management Key ---
STATE_WAITING_FOR_IMAGE = 'waiting_for_image'


# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_main_keyboard():
    keyboard = [[KeyboardButton(BTN_REMOVE_BACKGROUND)]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# --- Bot Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(STATE_WAITING_FOR_IMAGE, None) # Clear state on start
    await update.message.reply_text(
        "Hello! I'm your Background Remover Bot.\n"
        f"Tap the '{BTN_REMOVE_BACKGROUND}' button to begin.",
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(STATE_WAITING_FOR_IMAGE, None) # Clear state on help
    await update.message.reply_text(
        "How to use me:\n"
        f"1. Tap the '{BTN_REMOVE_BACKGROUND}' button below.\n"
        "2. Then, send me the image you want to process.\n"
        "3. I will send back the version with the background removed as a PNG.\n\n"
        "Powered by remove.bg",
        reply_markup=get_main_keyboard()
    )

async def handle_remove_bg_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[STATE_WAITING_FOR_IMAGE] = True
    logger.info(f"User {update.effective_user.id} pressed '{BTN_REMOVE_BACKGROUND}'. State set to WAITING_FOR_IMAGE.")
    await update.message.reply_text(
        "Okay, please send me the image you want to process now.",
        reply_markup=get_main_keyboard()
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = update.effective_user.id

    if context.user_data.get(STATE_WAITING_FOR_IMAGE) is True:
        logger.info(f"User {user_id} sent a photo while in WAITING_FOR_IMAGE state. Processing...")
        await message.reply_text("Processing your image, please wait...", reply_markup=get_main_keyboard())
        
        photo_file_id = message.photo[-1].file_id # Get the largest available photo from Telegram
        
        try:
            photo_file_obj = await context.bot.get_file(photo_file_id)
        except Exception as e:
            logger.error(f"Error getting file object from Telegram for file_id {photo_file_id}: {e}")
            await message.reply_text("Sorry, I couldn't download the image details. Please try again.", reply_markup=get_main_keyboard())
            context.user_data[STATE_WAITING_FOR_IMAGE] = False
            return

        image_byte_array = await photo_file_obj.download_as_bytearray()
        image_bytes_io = io.BytesIO(image_byte_array)
        # Give it a name; helps some APIs, though remove.bg autodetects format.
        # The extension doesn't force input type, just a good practice for multipart forms.
        original_filename = photo_file_obj.file_path.split('/')[-1] if photo_file_obj.file_path else 'input_image.jpg'
        image_bytes_io.name = original_filename

        logger.info(f"Downloaded image for processing: {original_filename}, size: {len(image_byte_array)} bytes.")

        headers = {'X-Api-Key': REMOVE_BG_API_KEY}
        # 'size': 'auto' - Tries to deliver the best quality for the account type.
        # For free accounts, this is typically a preview image (around 0.25 megapixels).
        # 'format': 'png' - For transparent background.
        # Other options for 'size' (mostly for paid plans): 'full', 'hd', '4k', or specific dimensions like '800x600'.
        # Using 'full' on a free plan will likely result in an error or still give a preview.
        data_payload = {
            'format': 'png',
            'size': 'auto', # This is usually the best for free tier to get largest preview
            # 'crop': 'true' # Example: if you want to crop away empty transparent space
            # 'add_shadow': 'true' # Example: if you wanted a shadow effect (paid feature often)
        }
        files_payload = {'image_file': image_bytes_io}
        
        try:
            logger.info(f"Sending image to remove.bg API with payload: {data_payload}")
            response = requests.post(REMOVE_BG_API_URL, headers=headers, files=files_payload, data=data_payload, timeout=45) # Increased timeout slightly
            response.raise_for_status()
            processed_image_bytes = response.content
            
            output_filename = 'bg_removed.png'
            content_type_header = response.headers.get('Content-Type', '').lower()

            if 'image/png' not in content_type_header:
                logger.warning(f"remove.bg did NOT return a PNG as expected. Content-Type: {content_type_header}. This might be an error image or wrong format.")
                # If it's an error image, it might be HTML or JSON.
                # Let's try to see if it's an image at all, otherwise, don't send as document.
                if "image/" in content_type_header:
                    extension = content_type_header.split('/')[-1]
                    output_filename = f'bg_removed_output.{extension}'
                else: # Not an image, likely an error message from API
                    error_text_from_api = processed_image_bytes.decode('utf-8', errors='ignore')[:500]
                    logger.error(f"remove.bg returned non-image content: {error_text_from_api}")
                    await message.reply_text(f"Sorry, remove.bg returned an unexpected response. It might be an error: {error_text_from_api}", reply_markup=get_main_keyboard())
                    context.user_data[STATE_WAITING_FOR_IMAGE] = False
                    return


            logger.info(f"Received processed image from remove.bg, size: {len(processed_image_bytes)} bytes. Content-Type: {content_type_header}")

            await context.bot.send_document(
                chat_id=message.chat_id,
                document=InputFile(io.BytesIO(processed_image_bytes), filename=output_filename),
                caption="Here's your image with the background removed (PNG format)!",
                reply_markup=get_main_keyboard()
            )

        except requests.exceptions.HTTPError as e:
            error_message = f"API Error ({e.response.status_code}): "
            try:
                # Try to parse remove.bg's JSON error response
                error_details_json = e.response.json()
                errors = error_details_json.get('errors', [])
                if errors and isinstance(errors, list) and len(errors) > 0 and 'title' in errors[0]:
                    error_message += errors[0]['title']
                    if 'detail' in errors[0]: error_message += f" - {errors[0]['detail']}"
                else:
                    error_message += e.response.text[:200] # Show part of the raw text if no title
            except ValueError: # If response is not JSON
                error_message += e.response.text[:200]
            logger.error(f"HTTP error from remove.bg: {error_message} | Full response text: {e.response.text}")
            await message.reply_text(error_message, reply_markup=get_main_keyboard())

        except requests.exceptions.Timeout:
            logger.error("Request to remove.bg API timed out.")
            await message.reply_text("The request to the background removal service timed out. Please try again.", reply_markup=get_main_keyboard())
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error connecting to remove.bg: {e}")
            await message.reply_text("Could not connect to the background removal service. Please check your internet or try again later.", reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error(f"An unexpected error occurred during image processing: {e}", exc_info=True)
            await message.reply_text("An unexpected error occurred while processing your image.", reply_markup=get_main_keyboard())
        finally:
            context.user_data[STATE_WAITING_FOR_IMAGE] = False 
            logger.info(f"User {user_id} state reset from WAITING_FOR_IMAGE.")
    else:
        logger.info(f"User {user_id} sent a photo but was NOT in WAITING_FOR_IMAGE state.")
        await message.reply_text(
            f"Please tap the '{BTN_REMOVE_BACKGROUND}' button first before sending an image.",
            reply_markup=get_main_keyboard()
        )

async def handle_other_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get(STATE_WAITING_FOR_IMAGE) is True:
        logger.info(f"User {user_id} sent non-photo while in WAITING_FOR_IMAGE state: {update.message.text or 'Non-text message'}")
        await update.message.reply_text(
            "I'm waiting for an image. Please send a photo to proceed, or send /start to reset.",
            reply_markup=get_main_keyboard()
        )
    else:
        logger.info(f"User {user_id} sent unhandled message: {update.message.text or 'Non-text message'}")
        await update.message.reply_text(
            f"I'm a background removal bot. Please tap '{BTN_REMOVE_BACKGROUND}' to start or send /help.",
            reply_markup=get_main_keyboard()
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    if update and hasattr(update, 'effective_user') and update.effective_user:
        context.user_data.pop(STATE_WAITING_FOR_IMAGE, None)
        logger.info(f"Cleared WAITING_FOR_IMAGE state for user {update.effective_user.id if hasattr(update.effective_user, 'id') else 'UnknownUser'} due to error.")
    
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text("Oops! Something went wrong. My circuits are a bit tangled. Please try /start again.", reply_markup=get_main_keyboard())
        except Exception as e_reply:
            logger.error(f"Failed to send error message to user: {e_reply}")

# --- Main Bot Logic --- (No changes needed in main() for this specific quality issue)
def main():
    logger.info("Starting bot application...")
    try:
        import pytz # Check for pytz, good for dependency awareness
        logger.info(f"Successfully imported pytz version: {pytz.__version__}")
    except ImportError:
        logger.warning("pytz library not found. This might cause issues if used by dependencies.")
    except Exception as e:
        logger.error(f"Could not import or check pytz version: {e}")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(f'^{BTN_REMOVE_BACKGROUND}$'), handle_remove_bg_button_press))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other_messages))
    application.add_handler(MessageHandler(~filters.TEXT & ~filters.PHOTO & ~filters.COMMAND, handle_other_messages))
    application.add_error_handler(error_handler)

    logger.info("Bot polling started...")
    application.run_polling()
    logger.info("Bot polling stopped.")

if __name__ == '__main__':
    main()
