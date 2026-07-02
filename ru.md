<p align="center">
  <a href="README.MD">[EN]</a> · [RU]
</p>

<h1 align="center">downloader-module (используется <a href="https://github.com/imputnet/cobalt/tree/main/api">cobaltAPI</a> и <a href="https://github.com/yt-dlp/yt-dlp">yt-dl</a>)</h1>

---

## что это?

модуль для [friendly telegram](https://friendly-telegram.gitbook.io/) (FTG) / [hikka](https://github.com/hikariatama/Hikka) юзерботов, который скачивает видео с тиктока, рилсов, икса, ютуба и других площадок.

## что нужно?

1. работающий ftg / hikka юзербот на **vds/vps**

## установка

1. ставим компоненты:

    - **cobaltAPI** — берёт видео с тиктока/рилсов/икса
        1. создай папку где-нить в уютном тёплом месте для `docker-compose.yml`
        2. напиши в `docker-compose.yml`:

            ```yaml
            services:
              cobalt-api:
                image: ghcr.io/imputnet/cobalt:latest
                container_name: cobalt-api
                restart: always # стартует вместе с системой, по идее
                init: true
                ports:
                  # удали `127.0.0.1:`, если хостишь у себя дома без белого айпи
                  - "127.0.0.1:9000:9000"
                environment:
                  - API_URL=http://127.0.0.1:9000/
                  - API_PORT=9000
            ```
            ...и сохрани.
        3. запусти в терминале из папки с `docker-compose.yml`:
            ```bash
            docker compose up -d
            ```
        4. ты молодец!!!

    - **yt-dl** — берёт видео с ютуба
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
        .addmod https://raw.githubusercontent.com/tecxz5/downloader/module/module.py
        ```
    2. или скинь файл вручную в `modules/` и перезапусти
    3. настрой `COBALT_INSTANCE` в конфиге модуля если надо

### использование

отправь `.dl <ссылка>` или ответь `.dl` на сообщение со ссылкой.

# поздравления, он запущен !!!