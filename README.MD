<p align="center">
  [EN] · <a href="ru.md">[RU]</a>
</p>

<h1 align="center">downloader-module (using <a href="https://github.com/imputnet/cobalt/tree/main/api">cobaltAPI</a> and <a href="https://github.com/yt-dlp/yt-dlp">yt-dl</a>)</h1>

---

## what is this?

a module for [friendly telegram](https://friendly-telegram.gitbook.io/) (FTG) / [hikka](https://github.com/hikariatama/Hikka) userbots that downloads videos from tiktok, reels, x, youtube and more.

## prerequisites

1. a working ftg/hikka userbot on **vds/vps**
2. `yt-dlp` installed on the server
3. **cobaltAPI** running somewhere

## installation

1. install the key components:

    - **cobaltAPI** — grabs videos from tiktok/reels/x
        1. create a cozy folder somewhere to store your `docker-compose.yml`
        2. write the following into `docker-compose.yml`:

            ```yaml
            services:
              cobalt-api:
                image: ghcr.io/imputnet/cobalt:latest
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
        2. you're also awesome!

> [!NOTE]
> adjust the paths as needed. the command is from the [official yt-dl wiki](https://github.com/yt-dlp/yt-dlp/wiki/Installation).

2. now load the module into your userbot:
    1. in your userbot chat run:
        ```
        .dlmod https://raw.githubusercontent.com/tecxz5/downloader/module/module.py
        ```
    2. or copy the file manually to `modules/` and restart
    3. configure `COBALT_INSTANCE` in the module settings if needed

### usage

send `.dl <link>` or reply to a message with a link using `.dl`.

# congrats, it's running !!!