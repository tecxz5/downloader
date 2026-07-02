<p align="center">
  [EN] · <a href="ru.md">[RU]</a>
</p>

<h1 align="center">downloader-bot (using <a href="https://github.com/imputnet/cobalt/tree/main/api">cobaltAPI</a> and <a href="https://github.com/yt-dlp/yt-dlp">yt-dl</a>)</h1>

---

## prerequisites

1. something resembling a computer, preferably on **'buntu**
2. `python` and `docker` installed

## bot installation

1. install the key components:

    - **cobaltAPI** — grabs videos from tiktok/reels/x
        1. create a cozy folder somewhere to store your `docker-compose.yml`
        2. write the following into `docker-compose.yml`:

            ```yaml
            services:
              cobalt-api:
                image: ghcr.io/imputnet/cobalt:10
                container_name: cobalt-api
                restart: always # starts on boot, probably
                init: true
                ports:
                  # remove `127.0.0.1:` if hosting at home without a static ip
                  - "127.0.0.1:9000:9000"
                environment:
                  - API_URL=http://127.0.0.1:9000/
                  - API_PORT=9000
            ```
            ...and save it.
        3. run this in the terminal from the folder with `docker-compose.yml`:
            ```bash
            docker compose up -d
            ```
        4. you're awesome!

    - **yt-dl** — grabs videos from youtube
        1. installation:
            ```bash
            curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ~/.local/bin/yt-dlp
            chmod a+rx ~/.local/bin/yt-dlp
            ```
> [!NOTE]
> adjust the paths as needed. the command is from the [official yt-dl wiki](https://github.com/yt-dlp/yt-dlp/wiki/Installation).
        2. to update:
            ```bash
            yt-dlp -U
            ```
        3. you're also awesome!

2. now set up the face for the monsters above:
    1. clone the bot:
        ```bash
        git clone https://github.com/tecxz5/downloader.git
        ```
    2. start a local botAPI (required for youtube videos):
        ```bash
        docker run -d \
        -p 8081:8081 \
        --name tg-bot-api \
        --restart=always \
        -v /root/downloader:/data \
        -e TELEGRAM_API_ID="API_ID" \
        -e TELEGRAM_API_HASH="API_HASH" \
        aiogram/telegram-bot-api:latest \
        --local
        ```
        get `api_id` and `api_hash` at https://my.telegram.org/
    3. todo: write about `.env`
    4. run the bot:
        ```bash
        uv run bot.py
        ```

# congrats, it's running !!!