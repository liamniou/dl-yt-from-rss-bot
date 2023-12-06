import dbm
import os
import feedparser
import telebot

from datetime import datetime
from telebot import types
from yt_dlp import YoutubeDL


RSS_FEED = os.getenv("RSS_FEED", "http://192.168.0.237:1200/youtube/subscriptions")
d = feedparser.parse(RSS_FEED)

bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def n_days_old(date, n):
    return (datetime.now() - date).days < n


def string_to_date(date_string):
    # Tue, 05 Dec 2023 17:44:50 GMT
    return datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %Z")


def get_video_info_from_yt_url(ytdl_opts, url):
    with YoutubeDL(ytdl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def check_new_videos():
    new_videos = None
    with dbm.open("db/rss-bot", "c") as db:
        for i in d.entries:
            if n_days_old(string_to_date(i.published), 1) and i.link not in db:
                info = get_video_info_from_yt_url({}, i.link)
                if info["duration"] > 60:
                    print(f"Processing {i.author}: {i.title} ({i.link})")
                    db[i.link] = "New"
                    new_videos = True
                else:
                    print(f"{i.author}: {i.title} is shorter than 1 minute")
                    db[i.link] = "Skip (short)"
    return new_videos


def if_any_dbm_item_is_new():
    with dbm.open("db/rss-bot", "c") as db:
        values = [db[key] for key in db.keys()]
        return any(elem.decode("ascii") == "New" for elem in values)


def main():
    if check_new_videos() or if_any_dbm_item_is_new():
        print("New videos found")
        markup = types.ReplyKeyboardMarkup()
        markup.add(
            types.KeyboardButton("Process"),
            types.KeyboardButton("Skip"),
        )

        bot.send_message(
            CHAT_ID, "Do you want to process new videos?", reply_markup=markup
        )


if __name__ == "__main__":
    main()
