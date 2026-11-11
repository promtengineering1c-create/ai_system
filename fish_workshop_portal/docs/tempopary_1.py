diff
--- a/migration.md  (после предложенного фикса)
+++ b/migration.md  (с поправкой)
@@ ~4.2.В, блок PRUNES/FIND_ARGS/chown/rsync
-PRUNES=()
+# Защитный chown корня: find -mindepth 1 не трогает '.',
+# а non-sudo rsync --delete требует запись в '.'
+sudo chown "$(id -un):$(id -gn)" .
+
+PRUNES=()
 if [[ "$PG_KIND" == "bind" && "$PG_SRC" != /* ]]; then
     PRUNES+=("$(norm "$PG_SRC")")
 fi
@@ ~4.2.В, блок rsync
 rsync -avz --delete \
-    -e "ssh -T -p ⚠️**<source.ssh.port>** -o BatchMode=yes" \
+    -e "ssh -T -p ⚠️**<source.ssh.port>** -o BatchMode=yes -o ConnectTimeout=5" \
     --rsync-path="sudo -k -n rsync" \
     --exclude='.git' \
     --exclude='.venv' \
Пункты 2, 4, 6 — вне scope этого фикса, но их стоит зафиксировать отдельным тикетом на унификацию -e "ssh ..." по всем rsync-вызовам runbook'а.

Diff (принят без изменений):

diff
--- a/migration.md
+++ b/migration.md
@@ -348,7 +348,8 @@
     sudo -n true 2>/dev/null || { echo "STOP: passwordless sudo недоступен (2.10)" >&2; exit 1; }
     DU_EXCLUDES=()
     if [[ "$PG_KIND" == "bind" && "$PG_SRC" != /* ]]; then
-        DU_EXCLUDES=("--exclude=${TARGET_DIR%/}/${PG_SRC#./}")
+        PG_REL="${PG_SRC#./}"; PG_REL="${PG_REL%/}"
+        DU_EXCLUDES=("--exclude=${TARGET_DIR%/}/${PG_REL}")
     fi
     sudo du -sh "${DU_EXCLUDES[@]}" -- "$TARGET_DIR"
 )
@@ -457,7 +458,8 @@
 
 DU_EXCLUDES=()
 if [[ "$PG_KIND" == "bind" && "$PG_SRC" != /* ]]; then
-    DU_EXCLUDES=("--exclude=${TARGET_DIR}/${PG_SRC#./}")
+    PG_REL="${PG_SRC#./}"; PG_REL="${PG_REL%/}"
+    DU_EXCLUDES=("--exclude=${TARGET_DIR}/${PG_REL}")
 fi
 SRC_KB="$(du -sk "${DU_EXCLUDES[@]}" -- "$TARGET_DIR" | awk '{print $1}')"
 
@@ -476,7 +478,7 @@
 RSYNC_EXCLUDES=()
 if [[ "$PG_KIND" == "bind" && "$PG_SRC" != /* ]]; then
     # Исключаем относительный путь PGDATA (относительно корня $TARGET_DIR)
-    RSYNC_EXCLUDES=("--exclude=/${PG_SRC#./}")
+    RSYNC_EXCLUDES=("--exclude=/${PG_REL}")
 fi
 
 rsync -aHAX --numeric-ids --delete "${RSYNC_EXCLUDES[@]}" -- "$TARGET_DIR/" "$BACKUP_DIR/" \
@@ -1188,7 +1190,8 @@
 # ── 5. формирование исключений и восстановление ──
 RSYNC_EXCLUDES=()
 if [[ "$PG_KIND" == "bind" && "$PG_SRC" != /* ]]; then
-    RSYNC_EXCLUDES=("--exclude=/${PG_SRC#./}")
+    PG_REL="${PG_SRC#./}"; PG_REL="${PG_REL%/}"
+    RSYNC_EXCLUDES=("--exclude=/${PG_REL}")
 fi
 
 sudo rsync -aHAX --numeric-ids --delete "${RSYNC_EXCLUDES[@]}" -- "$BACKUP/" "$TARGET_PROJECT_DIR/" \
Вне scope: аналогичная проверка trailing slash отсутствует для secrets.target_relative_path и storage.items[*].target_relative_path в 4.2.В, 5.3.2, 6.1. Если эти пути могут содержать завершающий /, исключения/chown/rsync будут работать некорректно. Унификация через общий norm() в этих шагах — отдельный тикет.

