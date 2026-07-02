<p align="center">
  <a href="README.MD">[EN]</a> · [RU]
</p>

<h1 align="center">downloader-bot (используется <a href="https://github.com/imputnet/cobalt/tree/main/api">cobaltAPI</a> и <a href="https://github.com/yt-dlp/yt-dlp">yt-dl</a>)</h1>

---

## что необходимо для работы?

1. что-то похожее на компьютер, желательно на **уебунте**
2. установленный `python` и установленный `docker`

## cама установка бота:
1. cтавим одни из самых важных компонентов:
    - **cobaltAPI** - берет видео с тикитоков/рилсов/иксов
        1. создать папку где-нить в уютном теплом месте, где будет лежать `docker-compose.yml`
        2. в `docker-compose.yml` написать:

            ```yaml
            services:
              cobalt-api:
                image: ghcr.io/imputnet/cobalt:latest
                container_name: cobalt-api
                restart: always # будет запускаться вместе с системой, по идее
                init: true
                ports:
                  # можете удалить `127.0.0.1:`, если хостите у себя дома, и не покупали у провайдера белый айпи
                  - "127.0.0.1:9000:9000"
                environment:
                  - API_URL=http://127.0.0.1:9000/
                  - API_PORT=9000
            ```
            и соответственно сохранить
        3. пропишите в консольку, находясь в папке с `docker-compose.yml`
        ```bash
        docker compose up -d
        ```
        4. вы молодец!!!


    - **yt-dl** - соотвественно, берет видео с ютуба
        1. сама установка:
            ```bash
            curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ~/.local/bin/yt-dlp
            chmod a+rx ~/.local/bin/yt-dlp
            ```
        2. для обновления:
            ```bash
            yt-dlp -U
            ```
        3. вы также молодец!!!

> [!NOTE]
> отредактируйте пути как вам надо, команда взята с [оф. вики **yt-dl**](https://github.com/yt-dlp/yt-dlp/wiki/Installation)
2. теперь установим лицо для монстров выше:
    1. установим бота:
        ```bash
        git clone https://github.com/tecxz5/downloader.git
        ```
    2. поднимите локальное botAPI следующей командой (оно необходимо для видео с ютуба):
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
        взять `api_id` и `api_hash` можно на https://my.telegram.org/
    3. настрой `.env`:
        ```bash
        cp .env.example .env
        ```
        потом открой `.env` и заполни:

        | переменная | что писать |
        |------------|-----------|
        | `BOT_TOKEN` | токен бота от [@BotFather](https://t.me/BotFather) |
        | `ALLOWED_USERS` | id телеграм-пользователей через запятую |
        | `COBALT_INSTANCE` | url cobalt api (по умолч. `http://127.0.0.1:9000/`) |
        | `LOCAL_TG_API` | url локального botapi (по умолч. `http://127.0.0.1:8081`) |
    4. теперь к запуску бота:
        ```bash
        uv run bot.py
        ```
> [!TIP]
> узнать свой id можно у [@userinfobot](https://t.me/userinfobot). 
# поздравления, он запущен !!!
