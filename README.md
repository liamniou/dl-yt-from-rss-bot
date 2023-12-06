# Populate DB with video links
```
$ docker-compose up checker
```

# Add cronjob to populate the DB every 6 hours
```
$ { crontab -l; echo "0 */6 * * * cd /rss-bot && docker-compose up checker"; } | crontab -
```

# Run TG bot
```
echo "RSS_FEED=..." > .env
echo "TELEGRAM_BOT_TOKEN=..." >> .env
echo "TARGET_DIR=..." >> .env
echo "TELEGRAM_CHAT_ID=..." >> .env

docker-compose up bot -d
```
