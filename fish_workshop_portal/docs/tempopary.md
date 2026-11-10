--- a/migration.md
+++ b/migration.md
@@ -1472,2 +1472,4 @@
 
+**Предусловие очистки:** используется локальный Docker daemon; проверенный дамп доступен вне очищаемого хранилища. Mount PGDATA выделен только под этот кластер, не используется другими контейнерами и не содержит вложенных монтирований. Поддерживается только mount точно на PGDATA; вложенный PGDATA требует ручной процедуры. До подтверждения этих условий очистка запрещена.
+
 ```bash
@@ -1477,21 +1479,61 @@
 
-echo "Удаление контейнера и связанных томов СУБД..."
-CID="$(docker compose ps -aq ⚠️**<database.service>** 2>/dev/null || true)"
-PG_MNT_TYPE=""
-PG_MNT_SRC=""
-if [[ -n "$CID" ]]; then
-    PG_DEST="$(docker inspect -f '{{json .Config.Env}}' "$CID" 2>/dev/null | grep -o '"PGDATA=[^"]*"' | cut -d= -f2- | tr -d '"' | head -1 || true)"
-    PG_DEST="${PG_DEST:-/var/lib/postgresql/data}"
-    PG_MNT_TYPE="$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$PG_DEST\"}}{{.Type}}{{end}}{{end}}" "$CID" 2>/dev/null || true)"
-    PG_MNT_SRC="$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$PG_DEST\"}}{{if eq .Type \"volume\"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}" "$CID" 2>/dev/null || true)"
-fi
\-
-docker compose rm -f -s -v ⚠️**<database.service>**
\-
-if [[ "$PG_MNT_TYPE" == "volume" && -n "$PG_MNT_SRC" ]]; then
-    docker volume rm -f "$PG_MNT_SRC" >/dev/null || true
-    echo "Удален том: $PG_MNT_SRC"
-elif [[ "$PG_MNT_TYPE" == "bind" && -n "$PG_MNT_SRC" && "$PG_MNT_SRC" == /* ]]; then
-    sudo rm -rf -- "${PG_MNT_SRC:?}"/*
-    echo "Очищена bind-директория: $PG_MNT_SRC"
+DB_SERVICE='⚠️**<database.service>**'
+ROLLBACK_DIR='⚠️**<journal.rollback_dir>**'
+JOURNAL='⚠️**<journal.path>**'
+CLEANUP_RC=1
+# Поддерживается только выделенный mount, Destination которого равен PGDATA.
+# Вложенный PGDATA, общие хранилища и вложенные mount требуют ручной процедуры.
+CID="$(docker compose ps -aq "$DB_SERVICE")" || exit "$CLEANUP_RC"
+[[ -n "$CID" && "$CID" != *$'\n'* ]] \\
+    || { echo "STOP: контейнер БД не определён однозначно" >&2; exit "$CLEANUP_RC"; }
+PG_DEST="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CID" | sed -n 's/^PGDATA=//p')" \\
+    || exit "$CLEANUP_RC"
+[[ "$PG_DEST" == /* && "$PG_DEST" != / && "$PG_DEST" != *$'\n'* && "$PG_DEST" != *'|'* ]] \\
+    || { echo "STOP: PGDATA не задан или неоднозначен" >&2; exit "$CLEANUP_RC"; }
+PG_MOUNT="$(docker inspect -f '{{range .Mounts}}{{printf "%s|%s|%s|%s\n" .Type .Name .Source .Destination}}{{end}}' "$CID" \\
+    | awk -F'[|]' -v dest="$PG_DEST" '$4==dest {print $1 "|" ($1=="volume" ? $2 : $3)}')" \\
+    || exit "$CLEANUP_RC"
+[[ -n "$PG_MOUNT" && "$PG_MOUNT" != *$'\n'* ]] \\
+    || { echo "STOP: нужен один mount точно на PGDATA; автоматическая очистка запрещена" >&2; exit "$CLEANUP_RC"; }
+IFS='|' read -r PG_MNT_TYPE PG_MNT_SRC <<< "$PG_MOUNT"
+case "$PG_MNT_TYPE" in
+    volume)
+        [[ -n "$PG_MNT_SRC" ]] || exit "$CLEANUP_RC"
+        ;;
+    bind)
+        PG_MNT_SRC="$(sudo realpath -e -- "$PG_MNT_SRC")" || exit "$CLEANUP_RC"
+        [[ "$PG_MNT_SRC" == /* && "$PG_MNT_SRC" != / ]] || exit "$CLEANUP_RC"
+        sudo test -d "$PG_MNT_SRC" || exit "$CLEANUP_RC"
+        SAFE_ROLLBACK="$(sudo realpath -e -- "$ROLLBACK_DIR")" || exit "$CLEANUP_RC"
+        case "$PG_MNT_SRC" in
+            "$SAFE_ROLLBACK"|"$SAFE_ROLLBACK"/*)
+                echo "STOP: PGDATA находится в каталоге бэкапов" >&2; exit "$CLEANUP_RC" ;;
+        esac
+        # Не удалять проект/бэкапы/журнал или их родительские каталоги.
+        # Подкаталог проекта, выделенный исключительно под PGDATA, допустим.
+        for protected in "$PWD" "$ROLLBACK_DIR" "$JOURNAL"; do
+            protected="$(sudo realpath -m -- "$protected")" || exit "$CLEANUP_RC"
+            case "$protected" in
+                "$PG_MNT_SRC"|"$PG_MNT_SRC"/*)
+                    echo "STOP: очистка затронет защищённый путь: $protected" >&2
+                    exit "$CLEANUP_RC"
+                    ;;
+            esac
+        done
+        ;;
+    *) echo "STOP: неподдерживаемый тип mount: $PG_MNT_TYPE" >&2; exit "$CLEANUP_RC" ;;
+esac
+printf 'Будет очищено хранилище PGDATA: %s %s\n' "$PG_MNT_TYPE" "$PG_MNT_SRC"
+read -r -p 'Для подтверждения введите точное имя volume или полный bind-путь: ' CONFIRM \\
+    || exit "$CLEANUP_RC"
+[[ "$CONFIRM" == "$PG_MNT_SRC" ]] \\
+    || { echo "STOP: очистка не подтверждена" >&2; exit "$CLEANUP_RC"; }
+# Без -v: посторонние анонимные volumes контейнера не удалять.
+docker compose rm -f -s "$DB_SERVICE" || exit "$CLEANUP_RC"
+if [[ "$PG_MNT_TYPE" == volume ]]; then
+    docker volume rm "$PG_MNT_SRC" || exit "$CLEANUP_RC"
+else
+    # Включая скрытые файлы; сам каталог и его права сохранить.
+    sudo find "$PG_MNT_SRC" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + \\
+        || exit "$CLEANUP_RC"
 fi
@@ -1934,2 +1976,4 @@
 **Место выполнения:** целевой сервер, Bash.
+
+**Предусловие очистки:** используется локальный Docker daemon; проверенный дамп доступен вне очищаемого хранилища. Mount PGDATA выделен только под этот кластер, не используется другими контейнерами и не содержит вложенных монтирований. Поддерживается только mount точно на PGDATA; вложенный PGDATA требует ручной процедуры. До подтверждения этих условий очистка запрещена.
 
@@ -2034,7 +2078,59 @@
     echo "WARN: Подтверждён конфликт версий PGDATA. Пересоздание тома БД под восстановление из проверенного дампа..." >&2
-    CID="$(docker compose ps -aq "$DB_SERVICE" 2>/dev/null || true)"
-    PG_VOLS=""
-    [[ -n "$CID" ]] && PG_VOLS="$(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' "$CID" 2>/dev/null || true)"
-    docker compose rm -f -s -v "$DB_SERVICE"
-    for vol in $PG_VOLS; do docker volume rm -f "$vol" >/dev/null; done
+    CLEANUP_RC=74
+    # Поддерживается только выделенный mount, Destination которого равен PGDATA.
+    # Вложенный PGDATA, общие хранилища и вложенные mount требуют ручной процедуры.
+    CID="$(docker compose ps -aq "$DB_SERVICE")" || exit "$CLEANUP_RC"
+    [[ -n "$CID" && "$CID" != *$'\n'* ]] \\
+        || { echo "STOP: контейнер БД не определён однозначно" >&2; exit "$CLEANUP_RC"; }
+    PG_DEST="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CID" | sed -n 's/^PGDATA=//p')" \\
+        || exit "$CLEANUP_RC"
+    [[ "$PG_DEST" == /* && "$PG_DEST" != / && "$PG_DEST" != *$'\n'* && "$PG_DEST" != *'|'* ]] \\
+        || { echo "STOP: PGDATA не задан или неоднозначен" >&2; exit "$CLEANUP_RC"; }
+    PG_MOUNT="$(docker inspect -f '{{range .Mounts}}{{printf "%s|%s|%s|%s\n" .Type .Name .Source .Destination}}{{end}}' "$CID" \\
+        | awk -F'[|]' -v dest="$PG_DEST" '$4==dest {print $1 "|" ($1=="volume" ? $2 : $3)}')" \\
+        || exit "$CLEANUP_RC"
+    [[ -n "$PG_MOUNT" && "$PG_MOUNT" != *$'\n'* ]] \\
+        || { echo "STOP: нужен один mount точно на PGDATA; автоматическая очистка запрещена" >&2; exit "$CLEANUP_RC"; }
+    IFS='|' read -r PG_MNT_TYPE PG_MNT_SRC <<< "$PG_MOUNT"
+    case "$PG_MNT_TYPE" in
+        volume)
+            [[ -n "$PG_MNT_SRC" ]] || exit "$CLEANUP_RC"
+            ;;
+        bind)
+            PG_MNT_SRC="$(sudo realpath -e -- "$PG_MNT_SRC")" || exit "$CLEANUP_RC"
+            [[ "$PG_MNT_SRC" == /* && "$PG_MNT_SRC" != / ]] || exit "$CLEANUP_RC"
+            sudo test -d "$PG_MNT_SRC" || exit "$CLEANUP_RC"
+            SAFE_ROLLBACK="$(sudo realpath -e -- "$ROLLBACK_DIR")" || exit "$CLEANUP_RC"
+            case "$PG_MNT_SRC" in
+                "$SAFE_ROLLBACK"|"$SAFE_ROLLBACK"/*)
+                    echo "STOP: PGDATA находится в каталоге бэкапов" >&2; exit "$CLEANUP_RC" ;;
+            esac
+            # Не удалять проект/бэкапы/журнал или их родительские каталоги.
+            # Подкаталог проекта, выделенный исключительно под PGDATA, допустим.
+            for protected in "$PWD" "$ROLLBACK_DIR" "$JOURNAL"; do
+                protected="$(sudo realpath -m -- "$protected")" || exit "$CLEANUP_RC"
+                case "$protected" in
+                    "$PG_MNT_SRC"|"$PG_MNT_SRC"/*)
+                        echo "STOP: очистка затронет защищённый путь: $protected" >&2
+                        exit "$CLEANUP_RC"
+                        ;;
+                esac
+            done
+            ;;
+        *) echo "STOP: неподдерживаемый тип mount: $PG_MNT_TYPE" >&2; exit "$CLEANUP_RC" ;;
+    esac
+    printf 'Будет очищено хранилище PGDATA: %s %s\n' "$PG_MNT_TYPE" "$PG_MNT_SRC"
+    read -r -p 'Для подтверждения введите точное имя volume или полный bind-путь: ' CONFIRM \\
+        || exit "$CLEANUP_RC"
+    [[ "$CONFIRM" == "$PG_MNT_SRC" ]] \\
+        || { echo "STOP: очистка не подтверждена" >&2; exit "$CLEANUP_RC"; }
+    # Без -v: посторонние анонимные volumes контейнера не удалять.
+    docker compose rm -f -s "$DB_SERVICE" || exit "$CLEANUP_RC"
+    if [[ "$PG_MNT_TYPE" == volume ]]; then
+        docker volume rm "$PG_MNT_SRC" || exit "$CLEANUP_RC"
+    else
+        # Включая скрытые файлы; сам каталог и его права сохранить.
+        sudo find "$PG_MNT_SRC" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + \\
+            || exit "$CLEANUP_RC"
+    fi
     docker compose up -d "$DB_SERVICE" || { echo "STOP: не удалось поднять $DB_SERVICE после очистки тома" >&2; exit 74; }