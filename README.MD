<p align="center">
  [EN] · <a href="ru.md">[RU]</a>
</p>

<h1 align="center">downloader-module (using <a href="https://github.com/yt-dlp/yt-dlp">yt-dl</a>)</h1>

---

## what is this?

a module for [friendly telegram](https://friendly-telegram.gitbook.io/) (FTG) / [hikka](https://github.com/hikariatama/Hikka) userbots that downloads videos from tiktok, reels, x, youtube and more.

## prerequisites

1. a working ftg/hikka userbot on **vds/vps**
2. `yt-dlp` installed on the server

## installation

1. install the key components:

    - **yt-dl** — grabs videos from youtube, tiktok, x, reels and more
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

### usage

send `.dl <link>` or reply to a message with a link using `.dl`.

# congrats, it's running !!!