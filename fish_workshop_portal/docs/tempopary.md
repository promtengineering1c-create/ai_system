--- a/migration.md
+++ b/migration.md
@@
 **Вариант А (true)**
 
 **Место выполнения:** целевой сервер, Bash.
 
 ```bash
-cd ⚠️**<target.project_dir>**
+TARGET_PROJECT_DIR=⚠️**<target.project_dir>**
+cd "$TARGET_PROJECT_DIR"
 docker compose up -d
 ```
@@
 **Вариант Б (false)**
 
 **Место выполнения:** целевой сервер, Bash.
 
 ```bash
-cd ⚠️**<target.project_dir>**
+TARGET_PROJECT_DIR=⚠️**<target.project_dir>**
+APP_SERVICE=⚠️**<application.service>**
+cd "$TARGET_PROJECT_DIR"
 # Ручное применение миграций до запуска основного пула
-docker compose run -T --rm ⚠️**<application.service>** python manage.py migrate
+docker compose run -T --rm "$APP_SERVICE" python manage.py migrate
 
 # Запуск всех контейнеров проекта
 docker compose up -d
 ```
@@
 **Место выполнения:** целевой сервер, Bash.
 
 ```bash
-cd ⚠️**<target.project_dir>**
+TARGET_PROJECT_DIR=⚠️**<target.project_dir>**
+APP_SERVICE=⚠️**<application.service>**
+cd "$TARGET_PROJECT_DIR"
 
 # Проверка, что все контейнеры находятся в статусе "Up" и не перезагружаются
 docker compose ps
 
 # Проверка отсутствия критических ошибок (Traceback, FATAL) при старте веб-сервера
-docker compose logs --tail=100 ⚠️**<application.service>**
+docker compose logs --tail=100 "$APP_SERVICE"
 ```
@@
 **Вариант А (`mode=host`, HTTP-порт опубликован на loopback хоста через `ports:`):**
 
 ```bash
 (
 set -Eeuo pipefail
-cd -- '⚠️**<target.project_dir>**'
+TARGET_PROJECT_DIR=⚠️**<target.project_dir>**
+APP_HOST=⚠️**<application.host>**
+HC_PUBLISHED_PORT=⚠️**<application.healthcheck.published_port>**
+HC_PATH=⚠️**<application.healthcheck.path>**
+cd -- "$TARGET_PROJECT_DIR"
 
 if ! STATUS="$(curl --silent --show-error --noproxy '*' \
     --connect-timeout 5 --max-time 10 \
-    -H 'Host: ⚠️**<application.host>**' \
+    -H "Host: $APP_HOST" \
     --output /dev/null --write-out '%{http_code}' \
-    'http://127.0.0.1:⚠️**<application.healthcheck.published_port>**⚠️**<application.healthcheck.path>**')"; then
+    "http://127.0.0.1:$HC_PUBLISHED_PORT$HC_PATH")"; then
     echo 'STOP: транспортная ошибка HTTP-проверки с хоста' >&2
     exit 70
 fi
@@
 **Вариант Б (`mode=container`, проверка внутри контейнера приложения):**
 
 `curl` внутри образа не требуется. Используется `python`, который уже применяется в командах приложения этого runbook. HTTP-процесс должен принимать подключения на `127.0.0.1:<container_port>` внутри контейнера; обычно он слушает `0.0.0.0:<container_port>`. Объявления `expose:` и `ports:` для этой проверки не требуются.
 
 ```bash
 (
 set -Eeuo pipefail
-cd -- '⚠️**<target.project_dir>**'
+TARGET_PROJECT_DIR=⚠️**<target.project_dir>**
+APP_SERVICE=⚠️**<application.service>**
+APP_HOST=⚠️**<application.host>**
+HC_CONTAINER_PORT=⚠️**<application.healthcheck.container_port>**
+HC_PATH=⚠️**<application.healthcheck.path>**
+cd -- "$TARGET_PROJECT_DIR"
 
-docker compose exec -T '⚠️**<application.service>**' python - \
-    'http://127.0.0.1:⚠️**<application.healthcheck.container_port>**⚠️**<application.healthcheck.path>**' \
-    '⚠️**<application.host>**' <<'PY'
+docker compose exec -T "$APP_SERVICE" python - \
+    "http://127.0.0.1:$HC_CONTAINER_PORT$HC_PATH" \
+    "$APP_HOST" <<'PY'
 import sys
 import urllib.error
 import urllib.request
@@
 3. **Очистка транзитных артефактов:** Если на шаге 5.3.1 переносился дамп БД, удалите его после подтверждения работоспособности приложения:
 ```bash
-DUMP_FILE=$(cat ⚠️**<journal.rollback_dir>**/migration_source_dump.name 2>/dev/null || true)
-+[[ -n "$DUMP_FILE" ]] && rm -f -- "⚠️**<journal.rollback_dir>**/$DUMP_FILE" ⚠️**<journal.rollback_dir>**/migration_source_dump.name
+ROLLBACK_DIR=⚠️**<journal.rollback_dir>**
+DUMP_FILE=$(cat "$ROLLBACK_DIR"/migration_source_dump.name 2>/dev/null || true)
++[[ -n "$DUMP_FILE" ]] && rm -f -- "$ROLLBACK_DIR/$DUMP_FILE" "$ROLLBACK_DIR"/migration_source_dump.name
 ```