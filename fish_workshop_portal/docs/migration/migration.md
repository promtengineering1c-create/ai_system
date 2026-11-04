# Перенос приложения на Ubuntu

## 1. Назначение, границы и правила выполнения

Инструкция описывает подготовку переноса и отката, развёртывание приложения на целевом сервере и проверку его готовности до переключения трафика.

В процедуру входят:
- проверка готовности исходного и целевого серверов;
- доставка и сборка заранее зафиксированной версии кода;
- подготовка отката и условий отмены переключения;
- согласованное резервирование PostgreSQL и файлов, проверка восстановления;
- перенос файла секретов, выбранных файловых хранилищ и, при необходимости, БД;
- подготовка проектных каталогов, томов и прав;
- восстановление данных, выполнение миграций БД и проверка приложения.

Вне процедуры:
- разработка, изменение кода и создание коммитов;
- установка и первоначальная настройка ОС, Docker, Compose, пользователей и сетевого доступа;
- определение состава и значений переменных файла секретов;
- переключение трафика и выполнение отката после переключения.

### Входные данные

`migration.config.yaml` в этой директории — единственный источник проектных параметров. Он должен быть заполнен до начала выполнения инструкции. Правила заполнения, определения полей и допустимые значения находятся внутри YAML.

YAML содержит входные параметры и заранее выбранные варианты действий. Результаты выполнения — время операций, фактические контрольные суммы и статусы проверок — фиксируются в отдельном журнале миграции, а не в YAML.

Секреты в YAML не записываются. Для файла секретов указываются только исходный и целевой пути; его содержимое не выводится в команды или журнал.

### Правила выполнения

- Каждая развилка ссылается на определяющий её ключ: например, `migration.config.yaml: code_delivery.method`.
- Каждый переносимый объект имеет стабильный `id`. Ссылка на файловый объект: `migration.config.yaml: storage.items[id=application_cache]`.
- Проектные параметры не задаются повторно в тексте инструкции или командах: значения берутся из YAML.
- YAML сам ничего не выполняет. Способ передачи его значений в команды указывается явно перед первым использованием.
- Для каждого действия указывается место выполнения: исходный сервер, целевой сервер или машина оператора.
- Для каждого шага определяются ожидаемый результат, способ проверки и условие остановки.
- При отсутствии необходимого значения или несоответствии предусловий выполнение останавливается. Исполнитель указывает конкретный ключ YAML или неуспешную проверку, не подставляя предположения.
- Заполненный YAML сам по себе не разрешает удаление или перезапись данных: такие действия допускаются только на предусмотренном инструкцией шаге.

## 2. Проверка готовности

### 2.1. Подключение к исходному серверу

**Место выполнения:** машина оператора, Bash.

Подключение к исходному серверу по параметрам `migration.config:source.ssh.*`.

```bash
ssh -p ⚠️**<source.ssh.port>** ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**
```

**Ожидаемый результат:** открыта сессия на исходном сервере.

### 2.2. Подтверждение исходного сервера

**Место выполнения:** исходный сервер, Bash.

Вывод имени хоста и пользователя сессии.

```bash
hostname
id -un
```

**Ожидаемый результат:** получен фактический вывод имени хоста; вывод `id -un` соответствует `source.ssh.user`.

### 2.3. Подключение к целевому серверу

**Место выполнения:** машина оператора, новый Bash-терминал.

Подключение к целевому серверу по параметрам `migration.config:target.ssh.*`.

```bash
ssh -p ⚠️**<target.ssh.port>** ⚠️**<target.ssh.user>**@⚠️**<target.ssh.host>**
```

**Ожидаемый результат:** открыта сессия на целевом сервере.

### 2.4. Подтверждение целевого сервера

**Место выполнения:** целевой сервер, Bash.

Вывод имени хоста и пользователя сессии.

```bash
hostname
id -un
```

**Ожидаемый результат:** получен фактический вывод имени хоста; вывод `id -un` соответствует `target.ssh.user`.

### 2.5. Проверка директории исходного проекта

**Место выполнения:** исходный сервер, Bash.

```bash
ls -la ⚠️**<source.project_dir>**/docker-compose.yml
```

**Ожидаемый результат:** Выведен атрибут файла `docker-compose.yml`. Директория существует и содержит конфигурацию.

### 2.6. Проверка базового ПО целевого сервера

**Место выполнения:** целевой сервер, Bash.

```bash
docker --version
docker compose version
```

**Ожидаемый результат:** Установлен Docker и плагин docker-compose. Выведены их версии.

**Дополнительно (только при `migration.config.yaml: migration.mode` — `update`):** проверить наличие текущей конфигурации и зафиксировать тег образа СУБД целевого сервера до обновления (проверка `pg_dump`-совместимости для отката выполняется в 3.2.3/8.3). При `mode = initial` блок пропускается (конфигурация ещё не доставлена).

```bash
test -f ⚠️**<target.project_dir>**/docker-compose.yml || { echo "STOP: нет docker-compose.yml при mode=update" >&2; exit 1; }
cd ⚠️**<target.project_dir>**
docker compose config --images | grep -i postgres
```

### 2.7. Подготовка целевой директории

**Место выполнения:** целевой сервер, Bash.

```bash
mkdir -p ⚠️**<target.project_dir>**
cd ⚠️**<target.project_dir>**
pwd
```

**Ожидаемый результат:** Директория создана (или существует), осуществлен переход в нее, вывод `pwd` совпадает с `target.project_dir`.

### 2.8. Обнаружение активных источников записи (writers)

**Место выполнения:** исходный сервер, Bash.

```bash
cd ⚠️**<source.project_dir>**
docker compose ps
crontab -l
systemctl list-timers --all --no-pager

# Активные соединения к СУБД — это и есть фактические writers
docker compose exec -T ⚠️**<database.service>** sh -c 'psql \
    -U "$⚠️**<database.environment_keys.user>**" -d "$⚠️**<database.environment_keys.name>**" \
    -c "select usename, client_addr, state, backend_type from pg_stat_activity \
        where pid <> pg_backend_pid() order by state, usename"'

# Долгие транзакции: снимок при них возможен, но WAL-хвост нельзя усечь
docker compose exec -T ⚠️**<database.service>** sh -c 'psql \
    -U "$⚠️**<database.environment_keys.user>**" -d "$⚠️**<database.environment_keys.name>**" \
    -c "select pid, state, now()-xact_start as age, left(query,60) \
        from pg_stat_activity where xact_start is not null and pid <> pg_backend_pid() \
        order by age desc limit 10"'
```

Ожидаемый результат: Выведены запущенные контейнеры, cron-задачи, systemd-таймеры и список соединений к СУБД. На этом этапе ничего не останавливается.

Критерий: зафиксировать перечень сервисов-писателей (application, worker, сторонние). Любой client_addr, отличный от внутренней сети compose, — дополнительный канал записи (внешняя интеграция, ручной клиент) и должен быть явно учтён при остановке в 5.1. Источник записи, не остановленный в 5.1, обесценивает консистентность снимка.

### 2.9. Проверка обратного доступа «целевой → исходный»

Место выполнения: целевой сервер, Bash.

Шаги 4.2 (вариант Б) и 5.3 тянут данные с исходного сервера по SSH. Ключевая аутентификация должна работать в обе стороны, запрос пароля недопустим: rsync в неинтерактивном режиме при отсутствии ключа зависнет или упадёт.

```bash
ssh -p ⚠️**<source.ssh.port>** -o BatchMode=yes -o ConnectTimeout=5 \
⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>** 'echo REVERSE_OK; id -un; command -v rsync' 
```
Ожидаемый результат: REVERSE_OK, имя пользователя совпадает с ⚠️**<source.ssh.user>, путь к rsync выведен.

Условия остановки: Permission denied, Host key verification failed, таймаут, отсутствие rsync на исходном сервере.

### 2.10. Проверка привилегий и групп

Место выполнения: целевой сервер, Bash.

```bash 
id -un 
id -nG 
sudo -n true && echo "SUDO_OK" || echo "SUDO_UNAVAILABLE" 
test -w /usr/local/bin && echo "LOCAL_BIN_WRITABLE" || echo "LOCAL_BIN_NOT_WRITABLE" 
docker info --format '{{.DockerRootDir}} {{.ServerVersion}}' 
```

Ожидаемый результат:
- пользователь сессии входит в группу docker (иначе все docker compose ... требуют sudo и несовместимы с командами файла);
- SUDO_OK — обязателен для 3.1 (запись в /usr/local/bin);
- DockerRootDir получен (используется в 2.12 и 3.2.3).

Условия остановки: отсутствие группы docker и SUDO_OK одновременно.

### 2.11. Проверка синхронизации времени

Место выполнения: исходный и целевой серверы, Bash.

Имена артефактов (TS, db_rollback_<TS>.dump), порядок записей в журнале и сравнение mtime при сверке бэкапов опираются на системные часы.

```bash 
timedatectl | sed -n '1,6p' 
date -u +'%s %FT%TZ' 
```

Ожидаемый результат: System clock synchronized: yes, NTP service: active. Расхождение выводов date -u %s между серверами — не более 2 с.

Условия остановки: расхождение более 2 с — устранить до выполнения шага 3 (сдвиг часов искажает порядок артефактов и делает журнал неупорядочиваемым).

### 2.12. Проверка свободного места и размера БД

Место выполнения: исходный сервер (оценка размера БД) и целевой сервер (свободное место).

Исходный сервер:

```bash
cd ⚠️**<source.project_dir>**
docker compose exec -T ⚠️**<database.service>** sh -c 'psql \
-U "$⚠️**<database.environment_keys.user>**" -d "$⚠️**<database.environment_keys.name>**" \
-tAc "select pg_size_pretty(pg_database_size(current_database())), \
            pg_database_size(current_database())"'
``` 
 
Целевой сервер: 
 
```bash
df -Ph "$(docker info --format '{{.DockerRootDir}}')" \
  ⚠️**<target.project_dir>** \
  ⚠️**<journal.rollback_dir>**
``` 
 
**Ожидаемый результат:** свободное место на ФС `DockerRootDir` — не менее 3× размера БД (данные + индексы + WAL + временные файлы при восстановлении); свободное место на ФС `journal.rollback_dir` — не менее 1× размера БД (сжатый дамп + файловый бэкап проекта). 
 
**Условия остановки:** любой из порогов не выполнен. Отдельно: `target.project_dir` и `journal.rollback_dir` должны находиться на разных ФС либо суммарный запас проверяется по каждой отдельно. 
 
### 2.13. Проверка инструментария и исходной версии СУБД

**Назначение:** Убедиться в наличии необходимых утилит для создания резервных копий и проверок ФС. Также требуется зафиксировать исходную версию СУБД, так как понижение мажорной версии (downgrade) при переносе дампа PostgreSQL не поддерживается.

**Место 1: целевой сервер, Bash.** Проверка локальных утилит.

```bash
for c in rsync sha256sum gzip tar curl awk sed grep find stat df; do
    command -v "$c" >/dev/null 2>&1 && echo "ok $c" || echo "MISSING $c"
done
rsync --version | head -1
```

**Место 2: исходный сервер, Bash.** Проверка совместимости `rsync` и фиксация образа БД.
 
 ```bash
rsync --version | head -1

 cd ⚠️**<source.project_dir>**
 docker compose config --images | grep -i postgres
 ```

**Ожидаемый результат:** Все перечисленные утилиты найдены на целевом сервере (отсутствует вывод `MISSING`). Обе стороны используют `rsync` версии 3.x (передача прав и UID/GID флагами `-aHAX --numeric-ids` между версиями 2.x и 3.x может отработать некорректно). Тег образа СУБД зафиксирован оператором.

**Условия остановки:** Ошибка `MISSING` для любой утилиты; версия `rsync` ниже 3. 

## 3. Подготовка отката

### 3.0. Заморозка состояния целевого сервера (остановка приложения)

**Место выполнения:** целевой сервер, Bash.

*(Выполняется только при `migration.config.yaml: migration.mode` — `update`. При `initial` шаг пропускается)*

Для гарантии консистентности между файлами и БД во время снятия точки отката, а также предотвращения изменения файлов «по живому» на шаге 4, пишущие сервисы должны быть остановлены до создания бэкапов.

```bash
cd ⚠️**<target.project_dir>**
docker compose stop ⚠️**<application.service>**
# Обязательно остановить все дополнительные сервисы (worker, cron и т.д.), если они есть.
# Контейнер БД (database.service) ОСТАВИТЬ РАБОТАТЬ — он нужен для дампа в 3.2.2.
```

**Ожидаемый результат:** Контейнеры приложения остановлены, изменения состояния БД и файловых хранилищ прекращены.

### 3.1. Создание локальной резервной копии (точка отката)

**Место выполнения:** целевой сервер, Bash.

Предусловия: выполнены шаги 2.9–2.13 (обратный SSH, привилегии, место, тулчейн). Каталог `<journal.rollback_dir>` существует, находится вне `<target.project_dir>` и доступен на запись. `<journal.path>` — абсолютный путь журнала, общий для всех шагов файла.

Роль артефакта: файловая точка отката (files_backup_*). Откат файлов проекта выполняется в 8.2. Точка отката БД (дамп) создаётся отдельно в 3.2. Артефакты 3.1 и 3.2 регистрируются в журнале независимо: 8.2 ищет файловую запись 3.1 ok, 8.3 — запись 3.2.3 ok.

Применимость по режиму: при migration.config: migration.mode = initial шаг не выполняется (откатывать нечего) — в журнал пишется 3.1 <ts> skipped mode=initial, переход к §4. При update — выполняется обязательно.

#### 3.1.1. Создать файл
```bush
nano /usr/local/bin/backup-project.sh
```
Запись в /usr/local/bin требует root — выполняется через sudo (проверено в 2.10). Альтернатива без root: каталог ⚠️**<journal.artifacts_dir>**/bin/backup-project.sh, если он на отдельной ФС от восстанавливаемых данных.

#### 3.1.2. Вставить код (весь скрипт целиком)
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
trap 'rc=$?; trap - EXIT; rm -f -- "${DIFF_FILE:-}"; if [[ $rc -ne 0 ]]; then echo "FAIL 3.1 rc=$rc line=$LINENO" >&2; fi; exit $rc' EXIT

# ============================================================================
# Exits codes:
#   0  - success (включая mode=initial: шаг пропущен)
#   20 - mode=update, но в TARGET_DIR нет docker-compose.yml
#   21 - сверка бэкапа не выполнена (rsync упал)
#   22 - бэкап не совпадает с источником
#   23 - guard: бэкап внутри цели или наоборот
#   24 - нет каталога / нет свободного места на ФС точки отката
#   25 - некорректный или неподставленный MIGRATION_MODE
#   26 - плейсхолдер не подставлен
# ============================================================================

# ============================================================================
# Конфигурация
# ============================================================================
TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
JOURNAL="⚠️**<journal.path>**"

# ============================================================================
# 0. Проверка подстановки (оба маркера, а не только один)
# ============================================================================
require_value() {
    local name="$1" val="$2" kind="${3:-plain}"

    [[ -n "$val" ]] || {
        echo "STOP: $name пуста" >&2
        return 26
    }

    case "$val" in
        *'⚠️'*|*'<'*|*'>'*|*'['*|*']'*)
            echo "STOP: $name не подставлена: '$val'" >&2
            return 26
            ;;
    esac

    case "$kind" in
        path)
            [[ "$val" == /* ]] || {
                echo "STOP: $name должна быть абсолютным путём: '$val'" >&2
                return 26
            }
            ;;
    esac

    return 0
}


require_value TARGET_DIR     "$TARGET_DIR"     path || exit 26
require_value ROLLBACK_DIR   "$ROLLBACK_DIR"   path || exit 26
require_value JOURNAL        "$JOURNAL"        path || exit 26
require_value MIGRATION_MODE "$MIGRATION_MODE" plain || exit 26

TARGET_DIR="${TARGET_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"

# ============================================================================
# Каталог журнала нужен обеим веткам (initial и update) до первого jlog
# ============================================================================
JOURNAL_DIR="$(dirname -- "$JOURNAL")"
mkdir -p -- "$JOURNAL_DIR" \
    || { echo "STOP: не создан каталог журнала: $JOURNAL_DIR" >&2; exit 24; }

jlog() { printf '%s\t%s\t%s\t%s\n' "$1" "$(date -u +%FT%TZ)" "$2" "$3" >> "$JOURNAL"; }

# ============================================================================
# 1. Гейт по режиму (единый источник истины — migration.mode, не наличие файлов)
# ============================================================================
case "$MIGRATION_MODE" in

update) : ;;
initial) 
    jlog "3.1" "skipped" "mode=initial"
    echo "3.1: mode=initial — точка отката по файлам не создаётся. Переход к §4."
    exit 0 ;;
*)
   echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'update' или 'initial'" >&2
   exit 25 
;; esac

# ============================================================================
# 2. Guard: артефакты не внутри цели или наоборот
# ============================================================================
[[ "$TARGET_DIR" != "$ROLLBACK_DIR" ]] \
    || { echo "STOP: target_dir и rollback_dir совпадают: $TARGET_DIR" >&2; exit 23; }

case "$ROLLBACK_DIR/" in

"$TARGET_DIR"/*) echo "STOP: rollback_dir внутри target_dir: $ROLLBACK_DIR" >&2; exit 23 
;; esac 
case "$TARGET_DIR/" in
"$ROLLBACK_DIR"/*) echo "STOP: target_dir внутри rollback_dir: $TARGET_DIR" >&2; exit 23 
;; esac

# ============================================================================
# 3. Предусловия ФС: цель существует и развёрнута, место есть
# ============================================================================
[[ -d "$TARGET_DIR" ]] \
    || { echo "STOP: нет каталога target_dir: $TARGET_DIR" >&2; exit 24; }

[[ -f "$TARGET_DIR/docker-compose.yml" ]] \
    || { echo "STOP: mode=update, но в $TARGET_DIR нет docker-compose.yml — откатывать нечего" >&2; exit 20; }

[[ -d "$ROLLBACK_DIR" && -w "$ROLLBACK_DIR" ]] \
    || { echo "STOP: rollback_dir недоступен на запись: $ROLLBACK_DIR" >&2; exit 24; }

SRC_KB="$(du -sk -- "$TARGET_DIR" | awk '{print $1}')"
AVAIL_KB="$(df -Pk -- "$ROLLBACK_DIR" | awk 'NR==2{print $4}')"

[[ -n "${SRC_KB:-}" && -n "${AVAIL_KB:-}" ]] \
    || { echo "STOP: не удалось определить размер target_dir или свободное место rollback_dir" >&2; exit 24; }

NEED_KB=$(( SRC_KB * 2 ))
[[ "$AVAIL_KB" -ge "$NEED_KB" ]] \
    || { echo "STOP: на ФС rollback_dir свободно ${AVAIL_KB}K, нужно ≈${NEED_KB}K (2× размер проекта ${SRC_KB}K)" >&2; exit 24; }

# ============================================================================
# 4. Создание бэкапа (rsync)
# ============================================================================
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${ROLLBACK_DIR}/files_backup_${TS}_$$"

mkdir -p -- "$BACKUP_DIR" \
    || { echo "STOP: не создан $BACKUP_DIR" >&2; exit 24; }

rsync -aHAX --numeric-ids --delete -- "$TARGET_DIR/" "$BACKUP_DIR/" \
    || { echo "STOP: rsync бэкапа упал" >&2; exit 21; }

# ============================================================================
# Сверка бэкапа с источником
# ============================================================================
DIFF_FILE="$(mktemp "${TMPDIR:-/tmp}/backup_diff.XXXXXX")"
rc=0
rsync -aHAXnc --numeric-ids --dry-run --out-format='%n' \
    "$TARGET_DIR/" "$BACKUP_DIR/" > "$DIFF_FILE" || rc=$?

if [[ $rc -ne 0 ]]; then
    echo "STOP: сверка бэкапа не выполнена (rc=$rc)" >&2
    exit 21
fi

if [[ -s "$DIFF_FILE" ]]; then
    echo "STOP: бэкап не совпадает с источником:" >&2
    head -20 "$DIFF_FILE" >&2
    exit 22
fi

# ============================================================================
# Манифест (SHA256 всех файлов)
# ============================================================================
( cd "$BACKUP_DIR" && find . -type f -exec sha256sum {} + > "$BACKUP_DIR.manifest.sha256" )

# ============================================================================
# 5. Регистрация точки отката в журнале (единственный источник для 8.2)
# ============================================================================
FILES_COUNT="$(wc -l < "$BACKUP_DIR.manifest.sha256" | tr -d ' ')"
jlog "3.1" "ok" "backup=${BACKUP_DIR}\tfiles=${FILES_COUNT}\tsrc_kb=${SRC_KB}"

echo "OK 3.1"
echo "  backup : $BACKUP_DIR"
echo "  files  : $FILES_COUNT"
echo "  mode   : $MIGRATION_MODE"
```

#### 3.1.3. Сделать исполняемым
sudo chmod 0750 /usr/local/bin/backup-project.sh

#### 3.1.4. Запускать
sudo /usr/local/bin/backup-project.sh

**Ожидаемый результат:**
- `mode=update`: в `⚠️**<journal.rollback_dir>**` создан каталог `files_backup_<TS>_<pid>` c полной копией `⚠️**<target.project_dir>**`; рядом — `files_backup_<TS>_<pid>.manifest.sha256`; в журнал добавлена строка `3.1 <ts> ok backup=... files=N`.
- `mode=initial`: выведено `3.1: mode=initial — точка отката по файлам не создаётся`, в журнал добавлена строка `3.1 <ts> skipped mode=initial`, код возврата 0.
- В `⚠️**<target.project_dir>**` не создано ни одного нового файла.

**Условия остановки:** код возврата ≠ 0; отсутствие строки `3.1 ... ok` в журнале при `mode=update`.

**Ожидаемый результат:** Если в целевой директории были файлы предыдущей версии, они скопированы в соседнюю директорию с меткой времени. Если директория пуста, выведено сообщение о том, что бэкап не требуется.

**Связь с другими шагами:** каталог из записи `3.1 ok` используется шагом 8.2 как источник восстановления файлов. Запись в журнале должен читать 8.2 (а не выбор по mtime) — при нескольких бэкапах порядок каталогов не гарантирован.

### 3.2. Резервирование целевой базы данных (для отката)

**Назначение:** снять согласованный снимок БД предыдущей версии до любых изменений файлов проекта, образа и схемы. Артефакт служит единственным источником восстановления данных для шага 8.3.

*(Выполняется, если на целевом сервере уже существует и работает предыдущая версия проекта)*

**Место выполнения:** целевой сервер, Bash.

**Предусловия:**
- - Шаг 3.2.1 обязателен для всех режимов. При `migration.mode = initial` шаги 3.2.2 и 3.2.3 не выполняются (осуществляется переход к 4).
- Каталог `journal.rollback_dir` существует, находится вне `target.project_dir` и доступен на запись.
- Утилиты `yq` и `sha256sum` установлены.

#### 3.2.1 Проверка предусловия (не пропускать)

Каталог отката не должен лежать внутри каталога проекта — иначе шаг 8.2 (`rsync --delete`) уничтожит дамп до того, как 8.3 его прочитает.

```bash
# Коды завершения:
#   0  — ок, продолжать 3.2.2;  либо mode=initial -> перейти к шагу 4 (см. сообщение)
#  22  — плейсхолдер не подставлен / недопустимый MIGRATION_MODE
#  23  — rollback_dir внутри project_dir (8.2 удалит артефакт)
#  24  — rollback_dir недоступен на запись
#  25  — нет docker-compose.yml в target.project_dir
#  26  — cd в target.project_dir не выполнен
#  прочее — FAIL <строка>, разбирать по выводу trap

set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 3.2.1 rc=$rc line=$LINENO" >&2' ERR

# ── заменить плейсхолдеры ──
TARGET_PROJECT_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
JOURNAL="⚠️**<journal.path>**"

# ── 1. проверка подстановки (только строки, ФС не трогаем) ──
for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'['* && "$val" != *'⚠️'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
[[ -n "$MIGRATION_MODE" && "$MIGRATION_MODE" != *'['* && "$MIGRATION_MODE" != *'⚠️'* ]] \
    || { echo "STOP: MIGRATION_MODE не подставлена: '$MIGRATION_MODE'" >&2; exit 22; }

# ── 2. ГЕЙТ РЕЖИМА ──
case "$MIGRATION_MODE" in
    update) : ;;
    initial)
        mkdir -p -- "$(dirname -- "$JOURNAL")"
        printf '3.2.3\t%s\tskipped\tinitial\n' "$(date -u +%FT%TZ)" >> "$JOURNAL"

        mkdir -p -- "$ROLLBACK_DIR"
        echo "STATUS=skipped" > "$ROLLBACK_DIR/rollback_point.env"
        echo "REASON=initial" >> "$ROLLBACK_DIR/rollback_point.env" 

        echo "3.2.1: mode=initial — шаги 3.2.x не выполняются."
        echo "Точка отката не создаётся: откатывать нечего. Переходите к шагу 4."
        exit 0 ;;
    *)
        echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'update' или 'initial'" >&2
        exit 22 ;;
esac

# ── 3. нормализация и guard ──
TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"

case "$ROLLBACK_DIR/" in
    "$TARGET_PROJECT_DIR"/*|"$TARGET_PROJECT_DIR"/)
        echo "STOP: rollback_dir внутри project_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac

# ── 4. предусловия ФС ──
[[ -d "$ROLLBACK_DIR" && -w "$ROLLBACK_DIR" ]] \
    || { echo "STOP: rollback_dir недоступен на запись: $ROLLBACK_DIR" >&2; exit 24; }
[[ -f "$TARGET_PROJECT_DIR/docker-compose.yml" ]] \
    || { echo "STOP: нет docker-compose.yml в $TARGET_PROJECT_DIR" >&2; exit 25; }

cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }
```

#### 3.2.2 Основной шаг

```bash
# Коды завершения:
#   0  — дамп снят и подтверждён спутником .sha256
#  22  — плейсхолдер не подставлен
#  23  — rollback_dir внутри project_dir
#  24  — rollback_dir недоступен / нет каталога журнала
#  26  — cd в target.project_dir не выполнен
#  27  — контейнер database.service отсутствует или не running
#  28  — pg_isready: СУБД не принимает соединения
#  29  — дамп подозрительно мал (пустая/чужая БД)
#  30  — .sha256 не сходится сразу после записи (битая ФС)
#  прочее — FAIL <строка>, разбирать по выводу trap

set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 3.2.2 rc=$rc line=$LINENO" >&2' ERR

# ── заменить плейсхолдеры ──
TARGET_PROJECT_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
DB_SERVICE="⚠️**<database.service>**"
DB_USER="⚠️**<database.environment_keys.user>**"
DB_NAME="⚠️**<database.environment_keys.name>**"
JOURNAL="⚠️**<journal.path>**"

# ── проверка подстановки ──
for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'['* && "$val" != *'⚠️'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
for v in DB_SERVICE DB_USER DB_NAME; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'['* && "$val" != *'⚠️'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done

TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"
umask 077

case "$ROLLBACK_DIR/" in
    "$TARGET_PROJECT_DIR"/*|"$TARGET_PROJECT_DIR"/)
        echo "STOP: rollback_dir внутри project_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac
[[ -d "$ROLLBACK_DIR" && -w "$ROLLBACK_DIR" ]] \
    || { echo "STOP: rollback_dir недоступен на запись: $ROLLBACK_DIR" >&2; exit 24; }
mkdir -p -- "$(dirname -- "$JOURNAL")" || { echo "STOP: нет каталога журнала" >&2; exit 24; }
cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }

# ── предикат: состояние контейнера БД, а не наличие файлов ──
CID="$(docker compose ps -aq "$DB_SERVICE" 2>/dev/null || true)"
if [[ -z "$CID" ]]; then
    echo "STOP: контейнер $DB_SERVICE отсутствует при mode=update ($TARGET_PROJECT_DIR)" >&2
    exit 27
fi

DB_STATE="$(docker inspect -f '{{.State.Status}}' "$CID")"
if [[ "$DB_STATE" != "running" ]]; then
    echo "STOP: контейнер $DB_SERVICE в состоянии '$DB_STATE', а не running. Разберись до дампа." >&2
    exit 27
fi

docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -U \"\$$DB_USER\" -d \"\$$DB_NAME\"" >/dev/null \
    || { echo "STOP: СУБД не принимает соединения" >&2; exit 28; }

# ── снимок ──
# pg_dump фиксирует MVCC-снимок на момент старта: записи живой версии после старта в дамп не попадут.
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="${ROLLBACK_DIR}/db_rollback_${TS}.dump"
PG_MAJOR="$(docker compose exec -T "$DB_SERVICE" postgres --version \
    | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"

docker compose exec -T "$DB_SERVICE" \
    sh -c "pg_dump -U \"\$$DB_USER\" -d \"\$$DB_NAME\" -Fc -Z 6 --no-owner --no-acl" \
    > "${DUMP}.tmp"

mv -- "${DUMP}.tmp" "$DUMP"
BYTES="$(stat -c %s "$DUMP")"
[[ "$BYTES" -gt 1000 ]] || { echo "STOP: дамп подозрительно мал ($BYTES байт)" >&2; exit 29; }

# ── спутник артефакта и файл состояния для 3.2.3 ──
sha256sum "$DUMP" > "${DUMP}.sha256"
SHA="$(cut -d' ' -f1 "${DUMP}.sha256")"

cat <<EOF > "${ROLLBACK_DIR}/rollback_point.env"
STATUS=ok
DUMP="${DUMP}"
DUMP_BYTES="${BYTES}"
DUMP_SHA256="${SHA}"
DB_NAME="${DB_NAME}"
PG_MAJOR="${PG_MAJOR}"
EOF

printf '3.2.2\t%s\tok\tdb=%s\tdump=%s\tsha256=%s\tbytes=%s\tpg=%s\n' \
    "$TS" "$DB_NAME" "$DUMP" "$SHA" "$BYTES" "$PG_MAJOR" >> "$JOURNAL"

echo "OK 3.2.2"
echo "  dump   : $DUMP"
echo "  bytes  : $BYTES"
echo "  sha256 : $SHA"
echo "  pg     : $PG_MAJOR"
```

#### 3.2.3 Проверка результата

```bash
# Коды завершения:
#   0  — точка отката валидна, можно переходить к шагу 4
#  22  — плейсхолдер не подставлен
#  26  — cd в target.project_dir не выполнен
#  40  — нет db_rollback_*.dump в rollback_dir
#  42  — файл дампа из журнала отсутствует
#  43  — дамп внутри project_dir
#  44  — размер дампа изменился после 3.2.2
#  45  — sha256 не совпадает
#  46  — pg_restore -l не читает оглавление
#  47  — TOC пуст (в дампе нет объектов)
#  48  — имя БД в дампе != database.environment_keys.name
#  49  — недостаточно места под восстановление
#  прочее — FAIL <строка>, разбирать по выводу trap

set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 3.2.3 rc=$rc line=$LINENO" >&2' ERR

# ── заменить плейсхолдеры ──
TARGET_PROJECT_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
DB_SERVICE="⚠️**<database.service>**"
JOURNAL="⚠️**<journal.path>**"

for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'['* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
[[ -n "$DB_SERVICE" && "$DB_SERVICE" != *'['* ]] || { echo "STOP: DB_SERVICE не подставлена" >&2; exit 22; }

TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"
RESULTS="${ROLLBACK_DIR}/rollback_point.env"

# ── 1. файл результата предыдущего шага ──
[[ -f "$RESULTS" ]] || { echo "STOP: нет $RESULTS — шаг 3.2.2 не выполнялся" >&2; exit 40; }
. "$RESULTS"

[[ "${STATUS:-}" == "ok" ]] || { echo "STOP: STATUS='${STATUS:-}' в $RESULTS (ожидается ok)" >&2; exit 41; }

# ── 2. артефакт существует, ненулевой, вне зоны rsync --delete ──
[[ -f "$DUMP" ]] || { echo "STOP: файл дампа отсутствует: $DUMP" >&2; exit 42; }
case "$DUMP" in
    "$TARGET_PROJECT_DIR"/*) echo "STOP: дамп лежит внутри project_dir — 8.2 его удалит" >&2; exit 43 ;;
esac
SIZE_NOW="$(stat -c %s "$DUMP")"
[[ "$SIZE_NOW" -eq "${DUMP_BYTES}" ]] \
    || { echo "STOP: размер изменился: было ${DUMP_BYTES}, стало ${SIZE_NOW}" >&2; exit 44; }

# ── 3. контрольная сумма ──
echo "${DUMP_SHA256}  ${DUMP}" | sha256sum -c - >/dev/null \
    || { echo "STOP: sha256 не совпадает — файл повреждён" >&2; exit 45; }

# ── 4. содержимое читается pg_restore, имя БД совпадает ──
cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }
HEADER="$(docker compose exec -T "$DB_SERVICE" pg_restore -l < "$DUMP")" \
    || { echo "STOP: pg_restore не читает оглавление дампа" >&2; exit 46; }

ENTRIES="$(grep -c '^[0-9]' <<<"$HEADER" || true)"
[[ "$ENTRIES" -gt 0 ]] || { echo "STOP: в дампе нет объектов (TOC пуст)" >&2; exit 47; }

DB_IN_DUMP="$(sed -n 's/^; *dbname: *//p' <<<"$HEADER" | head -1)"
[[ "$DB_IN_DUMP" == "$DB_NAME" ]] \
    || { echo "STOP: имя БД в дампе '$DB_IN_DUMP' ≠ объявленному '$DB_NAME'" >&2; exit 48; }

# ── 5. место для восстановления ──
AVAIL_KB="$(df -Pk "$ROLLBACK_DIR" | awk 'NR==2{print $4}')"
NEED_KB=$(( DUMP_BYTES / 1024 * 3 ))
[[ "$AVAIL_KB" -ge "$NEED_KB" ]] \
    || { echo "STOP: свободно ${AVAIL_KB}K, для восстановления нужно ≈${NEED_KB}K" >&2; exit 49; }

printf '3.2.3\t%s\tok\tdump=%s\tsha256=%s\ttoc=%s\tpg=%s\n' \
    "$(date -u +%FT%TZ)" "$DUMP" "$DUMP_SHA256" "$ENTRIES" "$PG_MAJOR" >> "$JOURNAL"

echo "OK 3.2.3"
echo "  dump    : $DUMP"
echo "  bytes   : $SIZE_NOW"
echo "  sha256  : OK"
echo "  toc     : $ENTRIES объектов"
echo "  dbname  : $DB_IN_DUMP"
echo "  pg_major: $PG_MAJOR (цель должна быть ≥)"
```

**Ожидаемый результат:**
- В `[journal.rollback_dir]` создан файл `db_rollback_<TS>.dump` в custom-формате, ненулевого размера, с валидным оглавлением.
- Создан `rollback_point.env` с путём, контрольной суммой и мажором PG.
- В `rollback_index.tsv` добавлена строка выполнения.
- В `[target.project_dir]` не создано ни одного нового файла.

**Условия остановки:**
- `journal.rollback_dir` внутри `target.project_dir` или недоступен;
- контейнер `[database.service]` находится в статусе `restarting`/`exited` — это отдельный дефект, а не «нет БД»;
- `pg_dump` завершился с ненулевым кодом;
- `pg_restore -l` не читает созданный файл.

**Запись в журнал:** `3.2`, метка времени UTC, `ok`/`skipped`/`fail`, путь к дампу, `sha256`, `src_pg_major`, размер.

## 4. Доставка и сборка кода

### 4.1. Проверка Git и доступа к репозиторию

**Место выполнения:** целевой сервер, Bash.
*(Выполняется, если `migration.config:code_delivery.method` — `remote_git` или `local_git`)*

```bash
git --version
# Только для remote_git:
git ls-remote [code_delivery.remote_git.url]
```

**Ожидаемый результат:** Утилита `git` установлена. Команда `ls-remote` вывела список веток удаленного репозитория без интерактивного запроса пароля.

### 4.2. Доставка кода

*(Оператор выбирает и выполняет только один из вариантов А, Б или В согласно `migration.config:code_delivery.method`)*

**Вариант А (remote_git)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
git init
git remote add origin ⚠️**<code_delivery.remote_git.url>** 2>/dev/null || git remote set-url origin ⚠️**<code_delivery.remote_git.url>**
git fetch origin ⚠️**<code_delivery.remote_git.ref>**
git reset --hard FETCH_HEAD
```

**Вариант Б (local_git)**

**Место 1 (исходный сервер):**

```bash
cd ⚠️**<source.project_dir>**
git bundle create /tmp/repo.bundle ⚠️**<code_delivery.local_git.commit>**
```

**Место 2 (целевой сервер):**

```bash
cd ⚠️**<target.project_dir>**
rsync -avP -e "ssh -p ⚠️**<source.ssh.port>**" ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:/tmp/repo.bundle /tmp/repo.bundle
git init
git fetch /tmp/repo.bundle
git reset --hard FETCH_HEAD
rm /tmp/repo.bundle
```

**Место 3 (исходный сервер):**

```bash
rm /tmp/repo.bundle
```

**Вариант В (no_git)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>*
rsync -avz --delete -e "ssh -p ⚠️**<source.ssh.port>**" --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='.env' ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/ .⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/ .
```
*(Оператор обязательно дополняет команду ключами `--exclude` из `code_delivery.exclude_paths`, включая пути ко всем локальным хранилищам `storage.items`, иначе флаг `--delete` их уничтожит)*

**Ожидаемый результат (для всех вариантов 3.2):** Исходный код приложения успешно доставлен в директорию `target.project_dir` на целевом сервере.

### 4.3. Доставка файла переменных окружения

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
rsync -avz -e "ssh -p ⚠️**<source.ssh.port>**" ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/.env .
```

**Ожидаемый результат:** Файл `.env` скопирован в корень проекта на целевом сервере.

**Проверка совместимости образа СУБД доставленной конфигурации:** зафиксировать целевой тег образа PostgreSQL после доставки `docker-compose.yml` и `.env` — мажорная версия должна быть не ниже исходной (зафиксированной в 2.13).

```bash
cd ⚠️**<target.project_dir>**
docker compose config --images | grep -i postgres
```
### 4.4. Доставка и подготовка Docker-образов

*(Оператор выбирает и выполняет только один из вариантов)*

**Вариант А (Сборка из исходников на целевом сервере)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]
docker compose pull
docker compose build
```

**Ожидаемый результат:** Скачаны базовые образы, локальная сборка завершена без ошибок.

**Вариант Б (Registry: Push / Pull)**

**Место 1 (исходный сервер):**

```bash
cd [source.project_dir]
docker compose build
docker compose push
```

**Место 2 (целевой сервер):**

```bash
cd [target.project_dir]
# При необходимости авторизации в закрытом Registry предварительно выполните: docker login
docker compose pull
```

**Ожидаемый результат:** Образы загружены в хранилище и успешно стянуты на целевой сервер.

**Вариант В (Прямой перенос: Save / Load)**

**Место 1 (исходный сервер):**

```bash
docker save -o /tmp/app_image.tar [compose.source_project_name]-[application.service]
```

**Место 2 (целевой сервер):**

```bash
rsync -avP -e "ssh -p [source.ssh.port]" [source.ssh.user]@[source.ssh.host]:/tmp/app_image.tar /tmp/app_image.tar
docker load -i /tmp/app_image.tar
rm /tmp/app_image.tar
```

**Место 3 (исходный сервер):**

```bash
rm /tmp/app_image.tar
```

**Ожидаемый результат:** Образ приложения перенесен и загружен в локальное хранилище Docker на целевом сервере.

## 5. Согласованное резервирование

### 5.1. Блокировка изменения данных (остановка writers)

*(Оператор выбирает вариант согласно `migration.config:consistency.capture_method`)*

**Вариант А (stop_writers)**

**Место выполнения:** исходный сервер, Bash.

```bash
cd [source.project_dir]
docker compose stop [application.service]
# При наличии дополнительных пишущих сервисов (worker), остановить их:
# docker compose stop worker
```

**Ожидаемый результат:** Источники записи остановлены. Контейнер СУБД продолжает работать.

**Вариант Б (coordinated)**

**Место выполнения:** исходный сервер, Bash.

```bash
cd [source.project_dir]
# Шаблон для будущей реализации Maintenance Mode на уровне ядра Django
docker compose exec [application.service] python manage.py set_maintenance_mode on
```

**Ожидаемый результат:** Приложение переведено в режим обслуживания силами самого Django, активные сессии корректно закрыты.

**Вариант В (not_needed)**

Действия не требуются.

### 5.2. Резервирование базы данных (логический дамп)

*(Выполняется, если `migration.config:database.mode` — `restore`)*

**Место выполнения:** исходный сервер, Bash.

```bash
cd [source.project_dir]
DUMP_FILE="db_dump_$(date +%Y%m%d_%H%M%S).sql.gz"

docker compose exec -T [database.service] sh -c 'pg_dump -U "$[database.environment_keys.user]" "$[database.environment_keys.name]"' | gzip > "$DUMP_FILE"

ls -lh "$DUMP_FILE"
```

**Ожидаемый результат:** Создан архив дампа БД. Файл существует и имеет ненулевой размер.

### 5.3. Перенос дампа БД и хранилищ на целевой сервер

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]

# Запрос имени созданного на шаге 5.2 архива:
read -r -p 'Укажите имя файла дампа БД (например, db_dump_...sql.gz): ' DUMP_FILE

# Копирование дампа БД (с докачкой и прогресс-баром)
rsync -avP -e "ssh -p [source.ssh.port]" [source.ssh.user]@[source.ssh.host]:[source.project_dir]/"$DUMP_FILE" .

# Копирование файловых хранилищ (выполнить для каждого каталога из storage.items)
# Пример для каталога storage/cache:
rsync -avP -e "ssh -p ⚠️**<source.ssh.port>**" ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/⚠️**<storage.items[*].source_relative_path>**/ ⚠️**<storage.items[*].target_relative_path>**/
```

**Ожидаемый результат:** Архив дампа БД и директории хранилищ скопированы в целевую директорию проекта.

## 6. Восстановление БД и запуск

### 6.1. Настройка прав доступа к файловым хранилищам

**Место выполнения:** целевой сервер, Bash.

*(Внимание: для корректного резервирования в 3.1 и отката в 8.2 все пути `target_relative_path` должны располагаться строго внутри директории `target.project_dir`. Внешние docker-тома или пути вне проекта текущей процедурой отката не покрываются)*

```bash
cd ⚠️**<target.project_dir>**

# Выполнить команду для каждого каталога из списка storage.items:
chown -R ⚠️**<storage.items[*].uid>**:⚠️**<storage.items[*].gid>** ⚠️**<storage.items[*].target_relative_path>**
```

**Ожидаемый результат:** Права на целевые директории хранилищ изменены для корректного доступа на запись изнутри контейнеров приложения.

### 6.2. Инициализация и восстановление базы данных

*(Оператор выбирает вариант согласно `migration.config:database.mode`)*

**Вариант А (restore)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
docker compose up -d ⚠️**<database.service>**

# Дождаться готовности СУБД (выполнять команду до получения успешного ответа):
docker compose exec ⚠️**<database.service>** sh -c 'pg_isready -U "$⚠️**<database.environment_keys.user>**"'

# Запрос имени архива дампа, перенесенного на шаге 5.3:
read -r -p 'Укажите имя файла дампа БД (например, db_dump_...sql.gz): ' DUMP_FILE

# Очистка целевой БД перед восстановлением (гарантия идемпотентности):
docker compose exec -T ⚠️**<database.service>** sh -c 'dropdb -U "$⚠️**<database.environment_keys.user>**" --if-exists --force "$⚠️**<database.environment_keys.name>**"'
docker compose exec -T ⚠️**<database.service>** sh -c 'createdb -U "$⚠️**<database.environment_keys.user>**" -O "$⚠️**<database.environment_keys.user>**" "$⚠️**<database.environment_keys.name>**"'

# Восстановление дампа (строгая остановка при первой ошибке):
zcat "$DUMP_FILE" | docker compose exec -T ⚠️**<database.service>** sh -c 'psql -v ON_ERROR_STOP=1 -U "$⚠️**<database.environment_keys.user>**" "$⚠️**<database.environment_keys.name>**"'
```

**Ожидаемый результат:** Контейнер СУБД запущен. Логический дамп успешно развернут без критических ошибок.

**Вариант Б (fresh)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]
docker compose up -d [database.service]
```

**Ожидаемый результат:** Запущен пустой контейнер СУБД, готовый к первичному накатыванию схемы.

### 6.3. Применение миграций и запуск приложения

*(Оператор выбирает вариант согласно `migration.config:application.migrations_on_web_start`)*

**Вариант А (true)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]
docker compose up -d
```

**Ожидаемый результат:** Все контейнеры запущены. Приложение самостоятельно выполнило миграции (при необходимости) во время старта.

**Вариант Б (false)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]
# Ручное применение миграций до запуска основного пула
docker compose run --rm [application.service] python manage.py migrate

# Запуск всех контейнеров проекта
docker compose up -d
```

**Ожидаемый результат:** Миграции успешно применены, все контейнеры проекта запущены и работают.

## 7. Проверка готовности

### 7.1. Проверка статуса контейнеров и логов

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]

# Проверка, что все контейнеры находятся в статусе "Up" и не перезагружаются
docker compose ps

# Проверка отсутствия критических ошибок (Traceback, FATAL) при старте веб-сервера
docker compose logs --tail=100 [application.service]
```

**Ожидаемый результат:** Все сервисы запущены. В логах нет циклических перезагрузок (crashloop) или ошибок подключения к БД.

### 7.2. Проверка локальной доступности (Healthcheck)

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]

# Проверка HTTP-ответа напрямую от контейнера приложения
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://localhost:[application.port]
```

**Ожидаемый результат:** Возвращается код `200` (OK) или `301`/`302` (Redirect). Коды `500` или `502` свидетельствуют об ошибке конфигурации или падении приложения.

## 8. Процедура отката (Rollback)

*(Выполняется в случае критического сбоя после запуска новой версии для возврата целевого сервера в исходное состояние)*

### 8.1. Остановка неисправной версии

**Место выполнения:** целевой сервер, Bash.

```bash
cd [target.project_dir]
docker compose down
```

### 8.2. Восстановление файлов проекта

**Место выполнения:** целевой сервер, Bash.

```bash
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 8.2 rc=$rc line=$LINENO" >&2' ERR

# Коды завершения:
#   0  — содержимое project_dir восстановлено и сверено с точкой отката
#  22  — плейсхолдер не подставлен
#  23  — rollback_dir внутри project_dir (иначе удалим собственную точку отката)
#  24  — нет ни одной files_backup_* с валидной раскладкой
#  26  — cd в target.project_dir не выполнен
#  62  — оператор не подтвердил восстановление
#  63  — rsync завершился с ошибкой
#  64  — сверка показала расхождения (неполное восстановление)
#  65  — восстановленный docker-compose.yml не парсится
#  прочее — FAIL <строка>, разбирать по выводу trap

# ── заменить плейсхолдеры ──
TARGET_PROJECT_DIR='⚠️**<target.project_dir>**'
ROLLBACK_DIR='⚠️**<journal.rollback_dir>**'
JOURNAL='⚠️**<journal.path>**'

# ── 1. проверка подстановки ──
for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'['* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"

# ── 2. guard: точка отката не внутри зоны --delete ──
case "$ROLLBACK_DIR/" in
    "$TARGET_PROJECT_DIR"/*|"$TARGET_PROJECT_DIR"/)
        echo "STOP: rollback_dir внутри project_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac
[[ -d "$TARGET_PROJECT_DIR" ]] || { echo "STOP: нет каталога $TARGET_PROJECT_DIR" >&2; exit 26; }
cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }

# ── 3. выбор точки: чтение подтверждённой записи из журнала ──
[[ -f "$JOURNAL" ]] || { echo "STOP: нет журнала $JOURNAL" >&2; exit 24; }
BACKUP="$(awk -F'\t' '$1=="3.1" && $3=="ok" {for(i=4;i<=NF;i) if($i~/^backup=/) {sub(/^backup=/,"",$i); print $i}}' "$JOURNAL" | tail -1)"

if [[ -z "$BACKUP" || ! -d "$BACKUP" || ! -f "$BACKUP/docker-compose.yml" ]]; then
    echo "STOP: в журнале нет подтверждённой точки отката 3.1 (ok) или каталог не содержит docker-compose.yml. BACKUP='${BACKUP:-}'" >&2
    exit 24
fi

# ── 4. подтверждение: rsync --delete уничтожит текущее содержимое ──
echo "project_dir : $TARGET_PROJECT_DIR"
echo "backup      : $BACKUP"
echo "содержимое project_dir будет заменено на backup --delete"
read -r -p 'Продолжить? [yes/NO] ' a
[[ "$a" == "yes" ]] || { echo "Отменено оператором."; exit 62; }

# ── 5. восстановление ──
rsync -aHAX --numeric-ids --delete -- "$BACKUP/" "$TARGET_PROJECT_DIR/" \
    || { echo "STOP: rsync не выполнен" >&2; exit 63; }

# ── 6. сверка: пустой вывод = содержимое совпадает ──
DIFF_FILE="$(mktemp)"
rsync -aHAXnc --numeric-ids -n -i --delete -- "$BACKUP/" "$TARGET_PROJECT_DIR/" > "$DIFF_FILE" \
    || { echo "STOP: сверка не выполнена" >&2; exit 63; }
if [[ -s "$DIFF_FILE" ]]; then
    echo "STOP: восстановлено не всё, расхождения:" >&2
    head -20 "$DIFF_FILE" >&2; rm -f "$DIFF_FILE"; exit 64
fi
rm -f "$DIFF_FILE"

# ── 7. восстановленный compose парсится ──
docker compose config --services >/dev/null 2>&1 \
    || { echo "STOP: docker-compose.yml восстановлен, но не парсится" >&2; exit 65; }

printf '8.2\t%s\tok\tbackup=%s\ttarget=%s\n' \
    "$(date -u +%FT%TZ)" "$BACKUP" "$TARGET_PROJECT_DIR" >> "$JOURNAL"

echo "OK 8.2"
echo "  backup : $BACKUP"
echo "  target : $TARGET_PROJECT_DIR"
echo "  next   : 8.3 (восстановление БД), затем 8.4"
```

**Ожидаемый результат:** Исходный код и переменные окружения возвращены к состоянию до миграции.

### 8.3. Восстановление базы данных

**Место выполнения:** целевой сервер, Bash.

```bash
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 8.3 rc=$rc line=$LINENO" >&2' ERR

# Коды завершения:
#   0  — БД восстановлена из подтверждённой в журнале точки отката
#  22  — плейсхолдер не подставлен
#  26  — cd в target.project_dir не выполнен
#  70  — в журнале нет строки 3.2.3 ... ok (точка отката не подтверждена)
#  71  — файл дампа отсутствует
#  72  — sha256 дампа не совпадает со спутником .sha256
#  73  — целевой мажор PG меньше источника (downgrade не поддерживается)
#  74  — БД не поднялась / pg_isready не отвечает
#  75  — dropdb/createdb не выполнены
#  76  — pg_restore завершился ошибкой (БД откачена в пустое состояние, см. вывод)
#  77  — после восстановления в схеме нет таблиц
#  прочее — FAIL <строка>, разбирать по выводу trap

# ── заменить плейсхолдеры ──
TARGET_PROJECT_DIR='⚠️**<target.project_dir>**'
ROLLBACK_DIR='⚠️**<journal.rollback_dir>**'
DB_SERVICE='⚠️**<database.service>**'
DB_USER='⚠️**<database.environment_keys.user>**'
DB_NAME='⚠️**<database.environment_keys.name>**'
JOURNAL='⚠️**<journal.path>**'

# ── 1. проверка подстановки ──
for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'['* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
for v in DB_SERVICE DB_USER DB_NAME; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'['* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }

# ── 2. точка отката: только подтверждённая шагом 3.2.3, не «последняя по mtime» ──
[[ -f "$JOURNAL" ]] || { echo "STOP: нет журнала $JOURNAL" >&2; exit 70; }
DUMP="$(awk -F'\t' '$1=="3.2.3" && $3=="ok" {d=$4; sub(/^dump=/, "", d)} END{print d}' "$JOURNAL")"
[[ -n "$DUMP" ]] || { echo "STOP: в журнале нет подтверждённой точки отката (3.2.3 ok)" >&2; exit 70; }
[[ -f "$DUMP" ]] || { echo "STOP: файл дампа отсутствует: $DUMP" >&2; exit 71; }
[[ -f "${DUMP}.sha256" ]] || { echo "STOP: нет спутника ${DUMP}.sha256" >&2; exit 72; }
sha256sum -c "${DUMP}.sha256" >/dev/null \
    || { echo "STOP: sha256 дампа не совпадает: $DUMP" >&2; exit 72; }

# ── 3. мажор источника — из журнала шага 3.2.2 ──
SRC_PG="$(awk -F'\t' '$1=="3.2.2" && $3=="ok" {for(i=1;i<=NF;i++) if($i ~ /^pg=/) {sub(/^pg=/,"",$i); print $i}}' \
    "$JOURNAL" | tail -1)"

# ── 4. поднять БД и дождаться готовности ──
docker compose up -d "$DB_SERVICE" || { echo "STOP: не удалось поднять $DB_SERVICE" >&2; exit 74; }
for _ in $(seq 1 30); do
    docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -U \"\$$DB_USER\" -d postgres -q" && break
    sleep 1
done
docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -U \"\$$DB_USER\" -d postgres -q" \
    || { echo "STOP: СУБД не принимает соединения" >&2; exit 74; }

# ── 5. запрет downgrade: pg_restore старое->новое работает, обратное — нет ──
DST_PG="$(docker compose exec -T "$DB_SERVICE" postgres --version | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
if [[ -n "$SRC_PG" && "$DST_PG" -lt "$SRC_PG" ]]; then
    echo "STOP: target PG $DST_PG < source PG $SRC_PG — дамп несовместим" >&2; exit 73
fi

# ── 6. атомарная замена БД (не DROP SCHEMA: сохраняет owner и права) ──
docker compose exec -T "$DB_SERVICE" sh -c "dropdb -U \"\$$DB_USER\" --force --if-exists \"\$$DB_NAME\"" \
    || { echo "STOP: dropdb не выполнен (есть активные соединения?)" >&2; exit 75; }
docker compose exec -T "$DB_SERVICE" sh -c "createdb -U \"\$$DB_USER\" -O \"\$$DB_USER\" \"\$$DB_NAME\"" \
    || { echo "STOP: createdb не выполнен" >&2; exit 75; }

# ── 7. восстановление: одна транзакция, любая ошибка откатывает всё ──
docker compose exec -T "$DB_SERVICE" \
    sh -c "pg_restore -U \"\$$DB_USER\" -d \"\$$DB_NAME\" --no-owner --no-acl --exit-on-error -1" < "$DUMP" \
    || { echo "STOP: pg_restore упал, БД пуста. Дамп: $DUMP" >&2; exit 76; }

# ── 8. проверка: в схеме есть объекты ──
TABLES="$(docker compose exec -T "$DB_SERVICE" sh -c "psql -U \"\$$DB_USER\" -d \"\$$DB_NAME\" -tAc \
    \"select count(*) from pg_tables where schemaname not in ('pg_catalog','information_schema')\"")"
[[ "${TABLES:-0}" -gt 0 ]] \
    || { echo "STOP: после восстановления в схеме 0 таблиц" >&2; exit 77; }
docker compose exec -T "$DB_SERVICE" sh -c "psql -U \"\$$DB_USER\" -d \"\$$DB_NAME\" -q -c 'ANALYZE'" >/dev/null

printf '8.3\t%s\tok\tdump=%s\ttables=%s\tsrc_pg=%s\tdst_pg=%s\n' \
    "$(date -u +%FT%TZ)" "$DUMP" "$TABLES" "${SRC_PG:-?}" "$DST_PG" >> "$JOURNAL"

echo "OK 8.3"
echo "  dump   : $DUMP"
echo "  tables : $TABLES"
echo "  pg     : src=${SRC_PG:-?} -> dst=$DST_PG"
echo "  next   : 8.4 (поднять образ, зафиксированный до миграции)"
```

**Ожидаемый результат:** Структура и данные СУБД возвращены к состоянию до миграции без конфликтов таблиц.

### 8.4. Запуск предыдущей версии

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**

# Восстановление локального образа (критично при переиспользовании тегов, например :latest).
# Пересборка гарантирует, что образ будет собран из откаченных исходников старой версии, 
# затирая закэшированный образ новой версии под тем же тегом.
docker compose build
docker compose up -d

# Проверка успешного старта
docker compose ps
docker compose logs --tail=50 ⚠️**<application.service>**
```

**Ожидаемый результат:** Предыдущая версия приложения успешно запущена и обрабатывает запросы.

