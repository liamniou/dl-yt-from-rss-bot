import dbm
import os
import telebot

from dataclasses import dataclass
from telebot import types
from yt_dlp import YoutubeDL


TARGET_DIR = os.getenv("TARGET_DIR")


bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))


@dataclass
class YtVideoInfo:
    channel: str
    title: str
    url: str


def string_to_path(string):
    return "".join(
        [c if c.isalnum() else "_" for c in string.replace(" ", "_").replace("-", "_")]
    )


def download_video_to_target_filename(ytdl_opts, url):
    with YoutubeDL(ytdl_opts) as ydl:
        ydl.download(url_list=[url])


def get_video_info_from_yt_url(ytdl_opts, url):
    with YoutubeDL(ytdl_opts) as ydl:
        yt_info = ydl.extract_info(url, download=False)
        return YtVideoInfo(
            channel=yt_info["channel"],
            title=yt_info["title"],
            url=url,
        )


def download_item(message, yt_info):
    if message.text == "Download":
        target_filename = os.path.join(
            TARGET_DIR,
            string_to_path(yt_info.channel),
            f"{string_to_path(yt_info.title)}.mp3",
        )
        ytdl_opts = {
            "outtmpl": target_filename,
            "format": "bestaudio",
        }
        bot.send_message(message.chat.id, f"Downloading...")
        download_video_to_target_filename(ytdl_opts, yt_info.url)
        remove_markup = types.ReplyKeyboardRemove(selective=False)
        bot.send_message(
            message.chat.id,
            f"Downloaded",
            reply_markup=remove_markup,
        )
    with dbm.open("db/rss-bot", "c") as db:
        db[yt_info.url] = "Processed"
    process_decision(message)


@bot.message_handler(func=lambda m: m.text is not None and m.text == "Process")
def process_decision(m):
    nothing_to_process = True
    with dbm.open("db/rss-bot", "c") as db:
        for key in db.keys():
            if db[key].decode("ascii") == "New":
                nothing_to_process = False
                print(f"{key} is New")
                i = get_video_info_from_yt_url({}, key.decode("ascii"))
                markup = types.ReplyKeyboardMarkup()
                markup.add(
                    types.KeyboardButton("Download"),
                    types.KeyboardButton("Skip"),
                )

                msg = bot.send_message(
                    m.chat.id,
                    f"'{i.channel} - {i.title}' ({i.url}) download it?",
                    reply_markup=markup,
                )
                bot.register_next_step_handler(msg, lambda m: download_item(m, i))
                break
            else:
                print(f"Skipping {db[key]} ({key})")
    if nothing_to_process:
        remove_markup = types.ReplyKeyboardRemove(selective=False)
        bot.send_message(
            m.chat.id, "That's it for now. See you later!", reply_markup=remove_markup
        )


def main():
    print("Starting bot")
    bot.polling()


if __name__ == "__main__":
    main()
