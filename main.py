import dbm
import json
import os
import re
import threading

import httpx
import telebot
from telebot.apihelper import ApiTelegramException
from telebot import types


METUBE_URL = os.getenv("METUBE_URL", "http://localhost:8085")


class _ExHandler(telebot.ExceptionHandler):
    def handle(self, exc):
        import traceback
        traceback.print_exc()
        return True


bot = telebot.TeleBot(
    os.getenv("TELEGRAM_BOT_TOKEN"),
    exception_handler=_ExHandler(),
)
_db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# DB helpers (JSON values with backward-compat for plain-string entries)
# ---------------------------------------------------------------------------

def read_entry(db, key):
    """Read a db entry, handling both old (plain string) and new (JSON) formats."""
    raw = db[key].decode("utf-8")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"status": raw}


def write_entry(db, key, data):
    """Write a JSON entry to the db."""
    if isinstance(key, bytes):
        key = key.decode("utf-8")
    db[key] = json.dumps(data)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _escape_html(text):
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_duration(seconds):
    """Format seconds into a human-readable duration string."""
    if not seconds:
        return ""
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


_YT_ID_RE = re.compile(r'(?:v=|youtu\.be/)([\w-]{11})')


def _video_id(url):
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def _thumbnail_url(url):
    vid = _video_id(url)
    if vid:
        return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    return None


def build_caption(url, entry):
    """Build caption text for a photo message. Returns (text, parse_mode)."""
    title = entry.get("title")
    channel = entry.get("channel")

    if entry.get("prefetched"):
        parts = [
            f"📺 <b>{_escape_html(channel or 'Unknown')}</b>",
            f"<b>{_escape_html(title or 'Unknown')}</b>",
        ]
        duration = _format_duration(entry.get("duration"))
        if duration:
            parts.append(f"⏱ {duration}")
        parts.append(f"\n{url}")
        return "\n".join(parts), "HTML"

    if title and channel:
        text = (
            f"📺 <b>{_escape_html(channel)}</b>\n"
            f"<b>{_escape_html(title)}</b>\n\n{url}"
        )
        return text, "HTML"

    return url, None


def _video_markup(url):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("🎵 Audio", callback_data=f"dl_audio|{url}"),
        types.InlineKeyboardButton("🎬 Video", callback_data=f"dl_video|{url}"),
        types.InlineKeyboardButton("⏭️ Skip", callback_data=f"skip|{url}"),
    )
    return markup


# ---------------------------------------------------------------------------
# MeTube integration
# ---------------------------------------------------------------------------

def download_via_metube(url: str, audio_only: bool = False) -> bool:
    """Trigger download via MeTube API."""
    payload = {
        "url": url,
        "quality": "audio" if audio_only else "best",
        "format": "mp3" if audio_only else "any",
    }

    try:
        response = httpx.post(
            f"{METUBE_URL}/add",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        print(f"MeTube response: {response.status_code} - {response.text[:200]}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error calling MeTube API: {e}")
        return False


# ---------------------------------------------------------------------------
# Video queue
# ---------------------------------------------------------------------------

def _find_next_new():
    """Find the next 'New' entry in the DB. Returns (url, entry) or (None, None)."""
    with dbm.open("db/rss-bot", "r") as db:
        for key in db.keys():
            entry = read_entry(db, key)
            if entry.get("status") == "New":
                url = key.decode("utf-8") if isinstance(key, bytes) else key
                return url, entry
    return None, None


def _mark_entry(url, status):
    """Update an entry's status in the DB."""
    with dbm.open("db/rss-bot", "c") as db:
        entry = read_entry(db, url)
        entry["status"] = status
        write_entry(db, url, entry)


def _send_video_photo(chat_id, url, entry, markup):
    """Send a new photo message with video thumbnail and caption."""
    caption, parse_mode = build_caption(url, entry)
    thumb = _thumbnail_url(url)

    if thumb:
        bot.send_photo(
            chat_id,
            photo=thumb,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=markup,
        )
    else:
        bot.send_message(
            chat_id,
            caption,
            reply_markup=markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )


def _edit_video_photo(chat_id, message_id, url, entry, markup):
    """Edit an existing photo message to show a different video."""
    caption, parse_mode = build_caption(url, entry)
    thumb = _thumbnail_url(url)

    if thumb:
        media = types.InputMediaPhoto(
            media=thumb,
            caption=caption,
            parse_mode=parse_mode,
        )
        bot.edit_message_media(media, chat_id, message_id, reply_markup=markup)
    else:
        bot.edit_message_caption(
            caption=caption,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
            reply_markup=markup,
        )


def show_next_video(chat_id, edit_message_id=None):
    """
    Show the next video in queue.
    If edit_message_id is given, edits that photo message in-place.
    Otherwise sends a new photo message.
    """
    with _db_lock:
        url, entry = _find_next_new()

    if url:
        print(f"{url} is New")
        markup = _video_markup(url)

        if edit_message_id:
            try:
                _edit_video_photo(chat_id, edit_message_id, url, entry, markup)
            except ApiTelegramException as e:
                # Thumbnail URL can return non-image (e.g. age-restricted, live) -> "wrong type of the web page content"
                err = str(e).lower()
                if "400" in err and "wrong type" in err:
                    bot.delete_message(chat_id, edit_message_id)
                    caption, parse_mode = build_caption(url, entry)
                    bot.send_message(
                        chat_id,
                        caption,
                        reply_markup=markup,
                        parse_mode=parse_mode,
                        disable_web_page_preview=True,
                    )
                else:
                    raise
        else:
            _send_video_photo(chat_id, url, entry, markup)
    else:
        done_text = "✨ That's it for now. See you later!"
        if edit_message_id:
            bot.delete_message(chat_id, edit_message_id)
            bot.send_message(chat_id, done_text)
        else:
            bot.send_message(chat_id, done_text)


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def handle_download_callback(call):
    """Handle download button callbacks."""
    data_parts = call.data.split("|", 1)
    if len(data_parts) != 2:
        bot.answer_callback_query(call.id, "Invalid callback data")
        return

    action, url = data_parts
    audio_only = action == "dl_audio"
    format_type = "audio" if audio_only else "video"

    bot.answer_callback_query(call.id, f"Starting {format_type} download...")

    success = download_via_metube(url, audio_only=audio_only)

    status = f"✅ {format_type.capitalize()} downloading..." if success else f"❌ Failed to start {format_type} download."
    bot.edit_message_caption(
        caption=status,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None,
    )

    with _db_lock:
        _mark_entry(url, "Processed")
    show_next_video(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("skip|"))
def handle_skip_callback(call):
    """Handle skip button — edit the same photo message to show next video."""
    url = call.data.split("|", 1)[1]

    bot.answer_callback_query(call.id)

    with _db_lock:
        _mark_entry(url, "Skipped")

    show_next_video(call.message.chat.id, edit_message_id=call.message.message_id)


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

@bot.message_handler(func=lambda m: m.text is not None and m.text == "Process")
def process_decision(m):
    """Start processing new items from the RSS feed database."""
    show_next_video(m.chat.id)


@bot.message_handler(func=lambda m: m.text and ("youtube.com/watch" in m.text or "youtu.be/" in m.text))
def handle_youtube_url(message):
    """Handle direct YouTube URL messages."""
    url = message.text.strip()

    match = re.search(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+)', url)
    if match:
        url = match.group(1)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎵 Audio", callback_data=f"dl_audio|{url}"),
        types.InlineKeyboardButton("🎬 Video", callback_data=f"dl_video|{url}"),
    )

    thumb = _thumbnail_url(url)
    if thumb:
        bot.send_photo(
            message.chat.id,
            photo=thumb,
            caption=url,
            reply_markup=markup,
        )
    else:
        bot.send_message(
            message.chat.id,
            url,
            reply_markup=markup,
            disable_web_page_preview=False,
        )


@bot.message_handler(commands=['start', 'help'])
def send_help(message):
    """Send help message."""
    help_text = (
        "🤖 <b>RSS YouTube Downloader Bot</b>\n\n"
        "This bot checks your YouTube subscriptions via RSS and lets you download videos.\n\n"
        "<b>Commands:</b>\n"
        "• Send <code>Process</code> to start processing new videos\n"
        "• Use the inline buttons to download audio/video or skip\n\n"
        "<b>Download options:</b>\n"
        "🎵 Audio — Downloads audio only (MP3)\n"
        "🎬 Video — Downloads full video (MP4)\n"
        "⏭️ Skip — Skip this video"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="HTML")


def main():
    print("Starting bot...")
    print(f"MeTube URL: {METUBE_URL}")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
