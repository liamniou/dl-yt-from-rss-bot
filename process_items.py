import dbm
import json
import os
import feedparser
import telebot

from datetime import datetime
from telebot import types


RSS_FEED = os.getenv("RSS_FEED", "http://192.168.0.237:1200/youtube/subscriptions")
MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "2"))

bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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


def n_days_old(date, n):
    """Check if a date is within n days of now."""
    return (datetime.now() - date).days < n


def string_to_date(date_string):
    """Parse RSS date format: Tue, 05 Dec 2023 17:44:50 GMT"""
    return datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %Z")


def check_new_videos():
    """Check RSS feed for new videos and add to database."""
    print(f"Fetching RSS feed: {RSS_FEED}")
    d = feedparser.parse(RSS_FEED)
    new_videos = False

    print(f"Found {len(d.entries)} entries in feed")

    with dbm.open("db/rss-bot", "c") as db:
        for entry in d.entries:
            try:
                pub_date = string_to_date(entry.published)
            except (ValueError, AttributeError) as e:
                print(f"Could not parse date for {entry.link}: {e}")
                continue

            if not n_days_old(pub_date, MAX_AGE_DAYS):
                continue

            if entry.link in db:
                continue

            title = getattr(entry, 'title', 'Unknown')
            author = getattr(entry, 'author', 'Unknown')

            print(f"✅ New: {author}: {title} ({entry.link})")
            write_entry(db, entry.link, {
                "status": "New",
                "title": title,
                "channel": author,
                "prefetched": False,
            })
            new_videos = True

    return new_videos


def if_any_dbm_item_is_new():
    """Check if any item in the database is marked as New."""
    with dbm.open("db/rss-bot", "c") as db:
        for key in db.keys():
            entry = read_entry(db, key)
            if entry.get("status") == "New":
                return True
    return False


def count_new_items():
    """Count items marked as New."""
    count = 0
    with dbm.open("db/rss-bot", "c") as db:
        for key in db.keys():
            entry = read_entry(db, key)
            if entry.get("status") == "New":
                count += 1
    return count


def main():
    print("Checking for new videos...")

    has_new = check_new_videos()
    any_pending = if_any_dbm_item_is_new()

    if has_new or any_pending:
        new_count = count_new_items()
        print(f"Found {new_count} new video(s) to process")

        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
        markup.add(types.KeyboardButton("Process"))

        bot.send_message(
            CHAT_ID,
            f"🎬 *{new_count} new video(s)* ready to process!\n\nTap Process to start.",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    else:
        print("No new videos found")


if __name__ == "__main__":
    main()
