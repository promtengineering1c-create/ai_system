--- a/migration.md  (после предложенного фикса)
+++ b/migration.md  (с поправкой)
@@ ~6.2 Вариант В (keep)
 if [[ -f "⚠️**<journal.rollback_dir>**/rollback_point.env" ]]; then
     . "⚠️**<journal.rollback_dir>**/rollback_point.env"
-    DST_PG="$(docker compose run -T --rm --no-deps --entrypoint postgres ⚠️**<database.service>** --version | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
+    # -T: без TTY (иначе CRLF в выводе и TTY-ошибка в неинтерактивной среде).
+    # tr -d '\r': страховка от trailing CR, если -T будет потерян при правке.
+    DST_PG="$(docker compose run -T --rm --no-deps --entrypoint postgres ⚠️**<database.service>** --version \
+        | tr -d '\r' | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
     [[ -z "${PG_MAJOR:-}" || "$DST_PG" == "$PG_MAJOR" ]] \
         || { echo "STOP: при database.mode=keep смена мажорной версии PG ($PG_MAJOR -> $DST_PG) запрещена (несовместимость PGDATA)" >&2; exit 1; }
 fi
@@ ~8.3
 # ── 4. запрет downgrade (проверка по образу ДО монтирования PGDATA) ──
-DST_PG="$(docker compose run -T --rm --no-deps --entrypoint postgres "$DB_SERVICE" --version | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
+DST_PG="$(docker compose run -T --rm --no-deps --entrypoint postgres "$DB_SERVICE" --version \
+    | tr -d '\r' | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
 if [[ -n "$SRC_PG" && "$DST_PG" -lt "$SRC_PG" ]]; then
     echo "STOP: target PG $DST_PG < source PG $SRC_PG — дамп несовместим" >&2; exit 73
 fi
@@ ~6.3 Вариант Б (false), ручные миграции
 # Ручное применение миграций до запуска основного пула
-docker compose run --rm ⚠️**<application.service>** python manage.py migrate
+docker compose run -T --rm ⚠️**<application.service>** python manage.py migrate