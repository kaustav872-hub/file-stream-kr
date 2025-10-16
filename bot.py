# © 2025 Kaustav Ray. All rights reserved.
# Licensed under the MIT License.

"""
KR Stream – Telegram Bot + Netflix-like Flask Web App
-----------------------------------------------------
Features:
- Admin uploads movies via Telegram
- Auto-saves to DB channel + MongoDB
- Flask website displays thumbnails Netflix-style
- Clicking movie streams directly from local files
"""

import os
import logging
import threading
import asyncio # Not strictly needed anymore for run_polling, but kept for context
from flask import Flask, render_template_string, abort, send_file, request
from pymongo import MongoClient
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ---------------- CONFIG ----------------
# NOTE: In a real deployment, move these to environment variables (os.environ)
BOT_TOKEN = "7304402114:AAG0rsovCc5s2i3_hTcUqnOa5PzUlLPULN8"
ADMIN_ID = 6705618257
DB_CHANNEL_ID = -1003197276754
LOG_CHANNEL_ID = -1003134132996
MONGODB_URI = "mongodb+srv://l6yml41j_db_user:2m5HFR6CTdSb46ck@cluster0.nztdqdr.mongodb.net/?retryWrites=true&w=majority"

# ---------------- MONGODB ----------------
try:
    client = MongoClient(MONGODB_URI)
    db = client["filestream_db"]
    collection = db["movies"]
    # Check connection
    client.admin.command('ping')
    logging.info("MongoDB connection successful.")
except Exception as e:
    logging.error(f"MongoDB connection failed: {e}")
    # Exit if DB connection fails
    exit(1)


# ---------------- LOGGING ----------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- FLASK ----------------
app = Flask(__name__)

# --- Templates ---

HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KR Stream</title>
<style>
body { background:#141414; color:white; font-family:Arial,sans-serif; margin:0; }
h1 { text-align:center; padding:1rem; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:1rem; padding:1rem; }
.card { background:#1f1f1f; border-radius:12px; overflow:hidden; transition:0.3s; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
.card:hover { transform:scale(1.03); box-shadow: 0 8px 16px rgba(0,0,0,0.7); }
.card img { width:100%; height:300px; object-fit:cover; }
.card h2 { text-align:center; font-size:0.9rem; padding:0.5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
a { text-decoration:none; color:white; }
</style>
</head>
<body>
<h1>🎬 KR Stream</h1>
<div class="grid">
{% for movie in movies %}
<div class="card">
<a href="/watch/{{ movie['_id'] }}">
<img src="{{ movie['thumbnail'] }}" alt="thumbnail">
<h2>{{ movie['filename'] }} ({{ movie['filesize'] }})</h2>
</a>
</div>
{% endfor %}
</div>
{% if not movies %}
    <p style="text-align: center; margin-top: 50px;">No movies uploaded yet. Please use the Telegram bot to upload files.</p>
{% endif %}
</body>
</html>
"""

WATCH_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ movie['filename'] }}</title>
<style>
body { background:black; color:white; text-align:center; margin: 0; padding-top: 20px; }
h1 { font-size: 1.5rem; margin-bottom: 20px; }
video { max-width:90%; height:auto; border-radius:10px; box-shadow: 0 0 20px rgba(0,0,0,0.9); }
</style>
</head>
<body>
<h1>{{ movie['filename'] }}</h1>
<video controls autoplay>
<source src="/stream/{{ movie['_id'] }}" type="video/mp4">
Your browser does not support the video tag.
</video>
</body>
</html>
"""

# --- Routes ---

@app.route("/")
def home():
    movies = list(collection.find().sort("filename", 1))
    return render_template_string(HOME_TEMPLATE, movies=movies)

@app.route("/watch/<movie_id>")
def watch(movie_id):
    movie = collection.find_one({"_id": movie_id})
    if not movie:
        abort(404)
    return render_template_string(WATCH_TEMPLATE, movie=movie)

# This uses Flask's send_file for streaming, which handles partial content/range requests
@app.route("/stream/<movie_id>")
def stream(movie_id):
    movie = collection.find_one({"_id": movie_id})
    if not movie or "file_path" not in movie:
        abort(404, description="Movie file not found in database.")
    
    file_path = movie["file_path"]
    if not os.path.exists(file_path):
        abort(404, description="Local movie file is missing.")
        
    # The 'range' argument in send_file enables streaming (partial content)
    range_header = request.headers.get('Range', None)
    
    # Use Flask's built-in streaming capability with conditional send
    return send_file(
        file_path, 
        mimetype='video/mp4', 
        as_attachment=False,
        # This parameter enables streaming for large files
        conditional=True
    )

# ---------------- TELEGRAM BOT HANDLERS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Access Denied")
        return
    await update.message.reply_text("👋 Send a movie file to upload.")

async def handle_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check for admin
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Only admin can upload files.")
        return

    # Check for video or document
    file = update.message.video or update.message.document
    if not file:
        await update.message.reply_text("❌ Send a valid video or document file.")
        return

    # Prepare file download
    await update.message.reply_text("⏳ Downloading file...")
    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", file.file_name or f"file_{file.file_unique_id}")
    
    try:
        file_obj = await context.bot.get_file(file.file_id)
        await file_obj.download_to_drive(file_path)

        # Default thumbnail (placeholder)
        thumbnail_url = "https://i.ibb.co/zs2tZ8L/netflix-poster.jpg"
        
        # Prepare movie document
        movie_doc = {
            "_id": str(file.file_unique_id),
            "filename": file.file_name or "Untitled Video",
            "filesize": f"{round(file.file_size / (1024*1024), 2)} MB",
            "thumbnail": thumbnail_url,
            "file_path": file_path # Local path for streaming
        }
        
        # Save to MongoDB
        collection.insert_one(movie_doc)

        # Send file to DB channel (optional but useful for backup)
        try:
            await context.bot.send_document(DB_CHANNEL_ID, InputFile(file_path), caption=f"🎬 {file.file_name}")
        except Exception as e:
            logger.warning(f"Could not send file to DB Channel: {e}")

        # Log upload
        await context.bot.send_message(LOG_CHANNEL_ID, f"🆕 New movie uploaded: {file.file_name}")
        await update.message.reply_text(f"✅ Uploaded successfully! Streamable at: /watch/{file.file_unique_id}")

    except Exception as e:
        logger.error(f"Error handling file upload: {e}")
        await update.message.reply_text(f"❌ An error occurred during processing: {e}")

# ---------------- RUN BOTH (FIXED) ----------------

def run_flask():
    """Starts the Flask web server."""
    port = int(os.environ.get("PORT", 8000))
    # NOTE: For production like Render, replace app.run() with a WSGI server (e.g., Gunicorn)
    # The command on Render would typically be: gunicorn --bind 0.0.0.0:$PORT bot:app
    logger.info(f"Flask server starting on port {port}...")
    app.run(host="0.0.0.0", port=port)

def start_bot_polling():
    """
    Sets up and runs the Telegram bot polling.
    FIXED: We now call application.run_polling() directly, 
    which manages its own asyncio loop, solving the AttributeError.
    """
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_movie))
    logger.info("Bot polling started...")
    
    # This is a blocking call and handles the event loop.
    application.run_polling(poll_interval=3, drop_pending_updates=True)

if __name__ == "__main__":
    
    # 1. Run Flask in a separate thread (for this hybrid setup)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # 2. Run bot in the main thread (blocking call)
    start_bot_polling()
