# © 2025 Kaustav Ray. All rights reserved.
# Licensed under the MIT License.

"""
Telegram File Stream Bot + Netflix-like Flask Web App
-----------------------------------------------------
This script handles:
 - Telegram Bot: Uploads, logging, MongoDB storage
 - Flask Web App: Netflix-style interface, streaming
 - No external config (all credentials hardcoded)
"""

import os
import logging
import mimetypes
from flask import Flask, render_template_string, send_file, abort
from pymongo import MongoClient
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ------------------------------------------------
# CONFIGURATION (Hardcoded)
# ------------------------------------------------
BOT_TOKEN = "7304402114:AAG0rsovCc5s2i3_hTcUqnOa5PzUlLPULN8"
ADMIN_ID = 6705618257
DB_CHANNEL_ID = -1003197276754
LOG_CHANNEL_ID = -1003134132996

# Multiple MongoDB URIs (future extensibility)
MONGODB_URIS = [
    "mongodb+srv://l6yml41j_db_user:2m5HFR6CTdSb46ck@cluster0.nztdqdr.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
]

# Connect to the first MongoDB (extendable for load-balancing)
client = MongoClient(MONGODB_URIS[0])
db = client["filestream_db"]
collection = db["movies"]

# ------------------------------------------------
# LOGGER
# ------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------------------------------
# FLASK APP
# ------------------------------------------------
app = Flask(__name__)

# HTML Template (Netflix-style UI)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>KRStream – Watch Movies</title>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
  <style>
    body { background: #141414; color: white; font-family: 'Poppins', sans-serif; margin: 0; }
    h1 { text-align: center; padding: 1rem; font-size: 2rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1.5rem; padding: 2rem; }
    .movie { background: #1f1f1f; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 8px rgba(0,0,0,0.3); transition: 0.3s; }
    .movie:hover { transform: scale(1.05); }
    .movie img { width: 100%; height: 300px; object-fit: cover; }
    .movie h2 { font-size: 1rem; padding: 0.5rem; text-align: center; color: #fff; }
  </style>
</head>
<body>
  <h1>🎬 KRStream – Watch Instantly</h1>
  <div class="grid">
    {% for movie in movies %}
      <div class="movie">
        <a href="/watch/{{ movie['_id'] }}">
          <img src="{{ movie['thumbnail'] }}" alt="thumbnail">
          <h2>{{ movie['filename'] }} ({{ movie['filesize'] }})</h2>
        </a>
      </div>
    {% endfor %}
  </div>
</body>
</html>
"""

WATCH_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{{ movie['filename'] }}</title>
  <style>
    body { background: black; color: white; text-align: center; }
    video { width: 80%; height: auto; margin-top: 50px; border-radius: 10px; }
  </style>
</head>
<body>
  <h1>{{ movie['filename'] }}</h1>
  <video controls autoplay>
    <source src="/stream/{{ movie['_id'] }}" type="video/mp4">
  </video>
</body>
</html>
"""

@app.route("/")
def home():
    movies = list(collection.find())
    return render_template_string(HTML_TEMPLATE, movies=movies)

@app.route("/watch/<movie_id>")
def watch(movie_id):
    movie = collection.find_one({"_id": movie_id})
    if not movie:
        abort(404)
    return render_template_string(WATCH_TEMPLATE, movie=movie)

@app.route("/stream/<movie_id>")
def stream(movie_id):
    movie = collection.find_one({"_id": movie_id})
    if not movie or "file_path" not in movie:
        abort(404)
    return send_file(movie["file_path"], as_attachment=False)

# ------------------------------------------------
# TELEGRAM BOT HANDLERS
# ------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command: only for admin"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Access Denied.")
        return
    await update.message.reply_text("👋 Send me a movie file to upload and stream.")

async def handle_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any document/video from admin"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Only admin can upload files.")
        return

    file = update.message.document or update.message.video
    if not file:
        await update.message.reply_text("❌ Please send a valid video or document file.")
        return

    # Download file
    new_file = await context.bot.get_file(file.file_id)
    file_path = f"downloads/{file.file_name}"
    os.makedirs("downloads", exist_ok=True)
    await new_file.download_to_drive(file_path)

    # Simulate thumbnail (could extend to use telegram photo)
    thumbnail_url = "https://i.ibb.co/zs2tZ8L/netflix-poster.jpg"

    # Store in MongoDB
    movie_data = {
        "_id": str(file.file_unique_id),
        "filename": file.file_name,
        "filesize": f"{round(file.file_size / (1024*1024), 2)} MB",
        "thumbnail": thumbnail_url,
        "file_path": file_path
    }
    collection.insert_one(movie_data)

    # Send to DB channel
    await context.bot.send_document(
        chat_id=DB_CHANNEL_ID,
        document=InputFile(file_path),
        caption=f"🎬 {file.file_name} uploaded successfully!"
    )

    await update.message.reply_text(f"✅ Uploaded and saved: {file.file_name}")
    await context.bot.send_message(LOG_CHANNEL_ID, f"🆕 New movie uploaded: {file.file_name}")

# ------------------------------------------------
# MAIN
# ------------------------------------------------
def main():
    app_telegram = Application.builder().token(BOT_TOKEN).build()
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_movie))

    # Run Flask in background thread
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8000)).start()

    logger.info("Bot and Flask app running...")
    app_telegram.run_polling()

if __name__ == "__main__":
    main()
