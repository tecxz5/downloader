<p align="center">
  <a href="README.MD">[EN]</a> · [RU]
</p>

<h1 align="center">downloader-module (используется <a href="https://github.com/yt-dlp/yt-dlp">yt-dl</a>)</h1>

---

## что это?

модуль для [friendly telegram](https://friendly-telegram.gitbook.io/) (FTG) / [hikka](https://github.com/hikariatama/Hikka) юзерботов, который скачивает видео с тиктока, рилсов, икса, ютуба и других площадок.

## что нужно?

1. работающий ftg / hikka юзербот на **vds/vps**

## установка

1. ставим компоненты:

    - **yt-dl** — берёт видео с ютуба, тиктока, икса, рилсов и других площадок
        1. установка:
            ```bash
            curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ~/.local/bin/yt-dlp
            chmod a+rx ~/.local/bin/yt-dlp
            ```
        2. ты тоже молодец!!!

> [!NOTE]
> отредактируй пути как надо, команда с [оф. вики yt-dl](https://github.com/yt-dlp/yt-dlp/wiki/Installation).

2. загружаем модуль в юзербота:
    1. в чате с юзерботом напиши:
        ```
        .dlmod https://raw.githubusercontent.com/tecxz5/downloader/module/module.py
        ```
    2. или скинь файл вручную в `modules/` и перезапусти

### использование

отправь `.dl <ссылка>` или ответь `.dl` на сообщение со ссылкой.

# поздравления, он запущен !!!