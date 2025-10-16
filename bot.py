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
import asyncio
from flask import Flask, render_template_string, abort, send_file
from pymongo import MongoClient
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ---------------- CONFIG ----------------
BOT_TOKEN = "7304402114:AAG0rsovCc5s2i3_hTcUqnOa5PzUlLPULN8"
ADMIN_ID = 6705618257
DB_CHANNEL_ID = -1003197276754
LOG_CHANNEL_ID = -1003134132996
MONGODB_URI = "mongodb+srv://l6yml41j_db_user:2m5HFR6CTdSb46ck@cluster0.nztdqdr.mongodb.net/?retryWrites=true&w=majority"

# ---------------- MONGODB ----------------
client = MongoClient(MONGODB_URI)
db = client["filestream_db"]
collection = db["movies"]

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- FLASK ----------------
app = Flask(__name__)

HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>KR Stream</title>
<style>
body { background:#141414; color:white; font-family:Arial,sans-serif; margin:0; }
h1 { text-align:center; padding:1rem; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:1rem; padding:1rem; }
.card { background:#1f1f1f; border-radius:12px; overflow:hidden; transition:0.3s; }
.card:hover { transform:scale(1.05); }
.card img { width:100%; height:300px; object-fit:cover; }
.card h2 { text-align:center; font-size:0.9rem; padding:0.3rem; }
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
body { background:black; color:white; text-align:center; }
video { width:80%; height:auto; margin-top:50px; border-radius:10px; }
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
    return render_template_string(HOME_TEMPLATE, movies=movies)

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

# ---------------- TELEGRAM BOT ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Access Denied")
        return
    await update.message.reply_text("👋 Send a movie file to upload.")

async def handle_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Only admin can upload files.")
        return

    file = update.message.video or update.message.document
    if not file:
        await update.message.reply_text("❌ Send a valid video or document")
        return

    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{file.file_name}"
    file_obj = await context.bot.get_file(file.file_id)
    await file_obj.download_to_drive(file_path)

    # Default thumbnail (placeholder)
    thumbnail_url = "https://i.ibb.co/zs2tZ8L/netflix-poster.jpg"

    movie_doc = {
        "_id": str(file.file_unique_id),
        "filename": file.file_name,
        "filesize": f"{round(file.file_size / (1024*1024), 2)} MB",
        "thumbnail": thumbnail_url,
        "file_path": file_path
    }
    collection.insert_one(movie_doc)

    await context.bot.send_document(DB_CHANNEL_ID, InputFile(file_path), caption=f"🎬 {file.file_name}")
    await context.bot.send_message(LOG_CHANNEL_ID, f"🆕 New movie uploaded: {file.file_name}")
    await update.message.reply_text("✅ Uploaded successfully!")

# ---------------- RUN BOTH ----------------
def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

def run_bot_sync():
    """Run the bot in a synchronous way"""
    async def run_async():
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_movie))
        logger.info("Bot started...")
        await application.run_polling()
    
    asyncio.run(run_async())

if __name__ == "__main__":
    # Run Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run bot in main thread
    run_bot_sync()
