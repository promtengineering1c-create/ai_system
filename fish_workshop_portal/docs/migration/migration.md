# Развёртывание и обновление приложения на Ubuntu (DJANGO + DOCKER COMPOSE + NGINX + POSTGRESQL)

## 1. Назначение, границы и правила выполнения

Инструкция описывает первичное развёртывание приложения на чистом целевом сервере (`initial`), выкатку новых релизов (`update`), подготовку отката и проверку готовности до переключения трафика.

В процедуру входят:
- проверка готовности исходного и целевого серверов;
- доставка и сборка заранее зафиксированной версии кода и Docker-образов;
- подготовка точки отката и условий отмены (при `update`);
- доставка файлов окружения и секретов, а также выбранных файловых хранилищ и Docker-томов;
- подготовка проектных каталогов, томов и прав доступа;
- инициализация или миграция БД (Expand/Contract) и проверка готовности приложения.

Вне процедуры:
- разработка, изменение кода и создание коммитов;
- установка и первоначальная настройка ОС, Docker, Compose, пользователей, межсетевого экрана хоста и DNS;
- определение состава и значений переменных файлов окружения и секретов;
- перенос (перелив) данных БД между серверами;
- переключение трафика и выполнение отката после переключения.

### Входные данные

`migration.config.yaml` в этой директории — единственный источник проектных параметров. Он должен быть заполнен до начала выполнения инструкции. Правила заполнения, определения полей и допустимые значения находятся внутри YAML.

YAML содержит входные параметры и заранее выбранные варианты действий. Результаты выполнения — время операций, фактические контрольные суммы, теги образов и статусы проверок — фиксируются в отдельном журнале миграции, а не в YAML.

Секреты в YAML не записываются. Для файлов окружения и секретов указываются только исходный и целевой пути; их содержимое не выводится в команды или журнал.

### Режимы работы (`migration.mode`)

- **`initial`** — первичное развёртывание на чистом сервере: шаги подготовки отката (3.x) пропускаются, создаётся пустой внешний том `pgdata`, доставляются код, конфигурация и образы, инициализируется БД и входной периметр.
- **`update`** — выкатка релиза без простоя: фиксируется предыдущий `APP_IMAGE_TAG`, при необходимости снимается страховочный онлайн-дамп БД и копия конфигов, применяются обратно совместимые миграции (Expand/Contract), выполняется параллельный запуск новой версии `web` (`start-first`) с сохранением `pgdata`.

### Правила выполнения

- Каждая развилка ссылается на определяющий её ключ: например, `migration.config.yaml: code_delivery.method`.
- Каждый переносимый объект имеет стабильный `id`. Ссылка на файловый объект: `migration.config.yaml: storage.items[id=application_cache]`.
- Проектные параметры не задаются повторно в тексте инструкции или командах: значения берутся из YAML.
- YAML сам ничего не выполняет. Способ передачи его значений в команды указывается явно перед первым использованием.
- Для каждого действия указывается место выполнения: исходный сервер, целевой сервер или машина оператора.
- Для каждого шага определяются ожидаемый результат, способ проверки и условие остановки.
- При отсутствии необходимого значения или несоответствии предусловий выполнение останавливается. Исполнитель указывает конкретный ключ YAML или неуспешную проверку, не подставляя предположения.
- Заполненный YAML сам по себе не разрешает удаление или перезапись данных: такие действия допускаются только на предусмотренном инструкцией шаге.

### Журнал оператора

- Ручные записи о ходе миграции, не привязанные к автоматическим шагам, ведутся в файле `migration-operator.log` на машине оператора.
- Файл создаётся до шага 2.1, ведётся сквозным образом до завершения миграции или отката, на исходный и целевой серверы не передаётся и артефактом отката не является.
- Формат строки: `<Шаг>\<Время>\<Сервер>\<Запись>`.
- Журнал оператора не заменяет `journal.path` на целевом сервере и не дублирует его.

## 2. Проверка готовности

### 2.1. Подключение к исходному серверу

**Место выполнения:** машина оператора, Bash.

Подключение к исходному серверу по параметрам `migration.config:source.ssh.*`.

```bash
SOURCE_SSH_PORT=⚠️**<source.ssh.port>**
SOURCE_SSH_USER=⚠️**<source.ssh.user>**
SOURCE_SSH_HOST=⚠️**<source.ssh.host>**

ssh -p "$SOURCE_SSH_PORT" "$SOURCE_SSH_USER"@"$SOURCE_SSH_HOST"
```

**Ожидаемый результат:** открыта сессия на исходном сервере.

### 2.2. Подтверждение исходного сервера

**Место выполнения:** исходный сервер, Bash.

Вывод имени хоста и пользователя сессии.

```bash
HOST_NAME="$(hostname)"
USER_SESSION="$(id -un)"

STEP=2.2; 
DATE_UTC="$(date -u +%FT%T)"
NOTE='подтверждён исходный сервер'; 
OUTPUT="$HOST_NAME; $USER_SESSION"

printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
```

**Ожидаемый результат:** получен фактический вывод имени хоста; вывод `id -un` соответствует `source.ssh.user`.

### 2.3. Подключение к целевому серверу

**Место выполнения:** машина оператора, новый Bash-терминал.

Подключение к целевому серверу по параметрам `migration.config:target.ssh.*`.

```bash
TARGET_SSH_PORT=⚠️**<target.ssh.port>**
TARGET_SSH_USER=⚠️**<target.ssh.user>**
TARGET_SSH_HOST=⚠️**<target.ssh.host>**

ssh -p "$TARGET_SSH_PORT" "$TARGET_SSH_USER"@"$TARGET_SSH_HOST"
```

**Ожидаемый результат:** открыта сессия на целевом сервере.

### 2.4. Подтверждение целевого сервера

**Место выполнения:** целевой сервер, Bash.

Вывод имени хоста и пользователя сессии.

```bash
HOST_NAME="$(hostname)"
USER_SESSION="$(id -un)"

STEP=2.4; 
DATE_UTC="$(date -u +%FT%T)"
NOTE='подтверждён целевой сервер'; 
OUTPUT="$HOST_NAME; $USER_SESSION"

printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
```

**Ожидаемый результат:** получен фактический вывод имени хоста; вывод `id -un` соответствует `target.ssh.user`.

### 2.5. Проверка директории исходного проекта

**Место выполнения:** исходный сервер, Bash.

```bash
SOURCE_PROJECT_DIR=⚠️**<source.project_dir>**

cd "$SOURCE_PROJECT_DIR" && \
ls -la docker-compose.yml

STEP=2.5; 
DATE_UTC="$(date -u +%FT%T)"
NOTE="docker-compose.yml существует на исходном сервере" 
OUTPUT=""

printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
```

**Ожидаемый результат:** Выведены атрибуты файла `docker-compose.yml`. Директория существует и содержит конфигурацию проекта.

### 2.6. Проверка базового ПО целевого сервера

**Место выполнения:** целевой сервер, Bash.

```bash
VERSION=$(docker --version)
COMPOSE_VERSION=$(docker compose version)
if command -v docker-rollout >/dev/null 2>&1 || docker rollout --help >/dev/null 2>&1; then
    ROLLOUT_STATUS="docker-rollout: ok"
else
    ROLLOUT_STATUS="docker-rollout: absent (fallback up -d)"
fi

STEP=2.6; 
DATE_UTC="$(date -u +%FT%T)"
NOTE='Базовое ПО проверено'; 
OUTPUT="$VERSION; $COMPOSE_VERSION; $ROLLOUT_STATUS"

printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
```

**Ожидаемый результат:** Установлены Docker и плагин `docker compose` версии `>= 2.24` (ADR-011); зафиксировано наличие `docker-rollout` (для бесшовного обновления `start-first` либо отсутствие плагина — в этом случае на шаге выкатки допускается fallback `up -d` с окном недоступности 5–15 с).

### 2.7. Подготовка целевой директории

**Место выполнения:** целевой сервер, Bash.

```bash
(
require_value() {
    local name="$1" val="$2" kind="${3:-plain}"

    [[ -n "$val" ]] || {
        echo "STOP: $name пуста" >&2
        return 26
    }

    case "$val" in
        *'⚠️'*|*'<'*|*'>'*|*'['*|*']'*|*'**'*)
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

set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
JOURNAL="⚠️**<journal.path>**"
MIGRATION_MODE="⚠️**<migration.mode>**"

require_value TARGET_DIR "$TARGET_DIR" path || exit 26
require_value ROLLBACK_DIR "$ROLLBACK_DIR" path || exit 26
require_value JOURNAL "$JOURNAL" path || exit 26
require_value MIGRATION_MODE "$MIGRATION_MODE" plain || exit 26

TARGET_DIR="${TARGET_DIR%/}"

mkdir -p "$TARGET_DIR" \
         "$TARGET_DIR/data/nginx-dynamic" \
         "$TARGET_DIR/data/ssl" \
         "$TARGET_DIR/data/letsencrypt" \
         "$ROLLBACK_DIR" \
         "$(dirname -- "$JOURNAL")"

case "$MIGRATION_MODE" in
    initial)
        docker volume inspect pgdata >/dev/null 2>&1 || docker volume create pgdata
        ;;
    update)
        docker volume inspect pgdata >/dev/null 2>&1 \
            || { echo "STOP: внешний том pgdata отсутствует при mode=update" >&2; exit 27; }
        ;;
    *)
        echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2
        exit 25
        ;;
esac
)
TARGET_DIR="⚠️**<target.project_dir>**"

cd "$TARGET_DIR"
pwd
```

**Ожидаемый результат:** Директории проекта, bind-маунтов (`data/nginx-dynamic`, `data/ssl`, `data/letsencrypt`), отката и каталога журнала созданы; внешний том `pgdata` создан (при `initial`) или подтверждён (при `update`). Осуществлён переход в целевую директорию, вывод `pwd` совпадает с `target.project_dir`.

### 2.8. Проверка входного межсетевого экрана (Cloudflare allowlist)

**Место выполнения:** целевой сервер, Bash.

*(Выполняется при `migration.config.yaml: migration.mode` — `initial` для окружения `production` или при `REQUIRE_FIREWALL=1`. При `update` и в `development`/`staging` шаг пропускается)*

```bash
(
set -Eeuo pipefail

MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"
REQUIRE_FIREWALL="${REQUIRE_FIREWALL:-}"

for v in MIGRATION_MODE APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$MIGRATION_MODE" in
    initial) ;;
    update)
        echo "2.8: mode=update — первичная проверка файрвола пропускается."
        exit 0
        ;;
    *)
        echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2
        exit 25
        ;;
esac

if [[ -z "$REQUIRE_FIREWALL" ]]; then
    [[ "$APP_ENV" == "production" ]] && REQUIRE_FIREWALL="1" || REQUIRE_FIREWALL="0"
fi

if [[ "$REQUIRE_FIREWALL" != "1" ]]; then
    echo "2.8: APP_ENV=$APP_ENV, REQUIRE_FIREWALL=$REQUIRE_FIREWALL — проверка DOCKER-USER пропускается."
    exit 0
fi

find_bin() {
    local name="$1"
    if command -v "$name" >/dev/null 2>&1; then
        command -v "$name"
    elif [[ -x "/usr/sbin/$name" ]]; then
        printf '/usr/sbin/%s\n' "$name"
    elif [[ -x "/sbin/$name" ]]; then
        printf '/sbin/%s\n' "$name"
    else
        return 1
    fi
}

IPT_BIN="$(find_bin iptables)" || { echo "STOP: утилита iptables не найдена (ADR-010)" >&2; exit 1; }
IPSET_BIN="$(find_bin ipset)" || { echo "STOP: утилита ipset не найдена (ADR-010)" >&2; exit 1; }

IPT_CMD=("$IPT_BIN")
IPSET_CMD=("$IPSET_BIN")
if [[ "${EUID}" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || { echo "STOP: требуется root или sudo для проверки DOCKER-USER" >&2; exit 1; }
    IPT_CMD=(sudo -n "$IPT_BIN")
    IPSET_CMD=(sudo -n "$IPSET_BIN")
fi

RULES="$("${IPT_CMD[@]}" -S DOCKER-USER 2>&1)" \
    || { echo "STOP: цепочка DOCKER-USER отсутствует или недоступна: $RULES" >&2; exit 1; }

RULE_COUNT="$(printf '%s\n' "$RULES" | grep -cE '^-A ' || true)"
[[ "$RULE_COUNT" -ge 1 ]] \
    || { echo "STOP: цепочка DOCKER-USER пуста — origin будет доступен в обход Cloudflare (ADR-010)" >&2; exit 1; }

printf '%s\n' "$RULES" | grep -q 'cf_ips_v4' \
    || { echo "STOP: в правилах DOCKER-USER не найдена ссылка на ipset cf_ips_v4 (ADR-010)" >&2; exit 1; }

IPSET_OUT="$("${IPSET_CMD[@]}" list cf_ips_v4 2>&1)" \
    || { echo "STOP: набор ipset cf_ips_v4 отсутствует: $IPSET_OUT" >&2; exit 1; }

CF_ENTRIES="$(printf '%s\n' "$IPSET_OUT" | awk -F': ' '/^Number of entries:/ {print $2}')"
[[ "${CF_ENTRIES:-0}" -ge 15 ]] \
    || { echo "STOP: набор cf_ips_v4 содержит ${CF_ENTRIES:-0} записей (требуется >= 15 по ADR-010)" >&2; exit 1; }

STEP=2.8
DATE_UTC="$(date -u +%FT%T)"
NOTE="Файрвол DOCKER-USER и ipset cf_ips_v4 проверены"
OUTPUT="rules=${RULE_COUNT}; cf_ips_v4=${CF_ENTRIES}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Цепочка `DOCKER-USER` существует, содержит активные правила со ссылкой на `cf_ips_v4`, а набор `ipset` `cf_ips_v4` загружен ($\ge 15$ префиксов IPv4) до публикации портов `80`/`443` (ADR-010).

**Условия остановки:** Отсутствие утилит `iptables`/`ipset`, отсутствие прав `root` или `sudo -n`, отсутствие/пустота цепочки `DOCKER-USER` либо отсутствие/неполнота набора `cf_ips_v4`.

### 2.9. Проверка обратного доступа «целевой → исходный»

**Место выполнения:** целевой сервер, Bash.

Шаги 4.2 (варианты Б и В), 4.3, 4.4 (вариант В) и 5.1 тянут данные с исходного сервера по SSH. Ключевая аутентификация должна работать в обе стороны, запрос пароля недопустим: `rsync` в неинтерактивном режиме при отсутствии ключа зависнет или упадёт.

```bash
SOURCE_SSH_PORT=⚠️**<source.ssh.port>**
SOURCE_SSH_USER=⚠️**<source.ssh.user>**
SOURCE_SSH_HOST=⚠️**<source.ssh.host>**

ssh -p "$SOURCE_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=5 \
    "$SOURCE_SSH_USER"@"$SOURCE_SSH_HOST" 'echo REVERSE_OK; id -un; command -v rsync'
```

**Ожидаемый результат:** `REVERSE_OK`, имя пользователя совпадает с `source.ssh.user`, путь к `rsync` выведен.

**Условия остановки:** `Permission denied`, `Host key verification failed`, таймаут, отсутствие `rsync` на исходном сервере.

### 2.10.1. Проверка прав чтения на исходном сервере

**Место выполнения:** исходный сервер, Bash.

```bash
(
set -Eeuo pipefail

SOURCE_PROJECT_DIR="⚠️**<source.project_dir>**"

[[ -n "$SOURCE_PROJECT_DIR" && "$SOURCE_PROJECT_DIR" != *'⚠️'* && "$SOURCE_PROJECT_DIR" != *'<'* && "$SOURCE_PROJECT_DIR" != *'>'* && "$SOURCE_PROJECT_DIR" != *'['* && "$SOURCE_PROJECT_DIR" != *']'* && "$SOURCE_PROJECT_DIR" != *'**'* ]] \
    || { echo "STOP: SOURCE_PROJECT_DIR не подставлена: '$SOURCE_PROJECT_DIR'" >&2; exit 26; }

[[ -d "$SOURCE_PROJECT_DIR" && -r "$SOURCE_PROJECT_DIR" && -x "$SOURCE_PROJECT_DIR" ]] \
    || { echo "STOP: каталог '$SOURCE_PROJECT_DIR' недоступен для чтения пользователю $(id -un)" >&2; exit 1; }

[[ -r "$SOURCE_PROJECT_DIR/docker-compose.yml" ]] \
    || { echo "STOP: файл '$SOURCE_PROJECT_DIR/docker-compose.yml' недоступен для чтения" >&2; exit 1; }

UNREADABLE_ENV="$(find "$SOURCE_PROJECT_DIR" -maxdepth 1 -name '.env*' ! -readable 2>/dev/null || true)"
[[ -z "$UNREADABLE_ENV" ]] \
    || { echo "STOP: на источнике есть нечитаемые файлы окружения: $UNREADABLE_ENV" >&2; exit 1; }

DOCKER_SRC="absent"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    DOCKER_SRC="ok"
fi

UNREADABLE_DATA=0
if [[ -d "$SOURCE_PROJECT_DIR/data" ]]; then
    UNREADABLE_DATA="$(find "$SOURCE_PROJECT_DIR/data" ! -readable 2>/dev/null | wc -l | tr -d ' ')"
fi

STEP=2.10.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Права чтения на исходном сервере проверены"
OUTPUT="user=$(id -un); src_dir=ok; docker=${DOCKER_SRC}; unreadable_data=${UNREADABLE_DATA}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Выведено `src_dir=ok`; каталог проекта, `docker-compose.yml` и файлы `.env*` доступны для чтения текущему пользователю (должен совпадать с `⚠️**<source.ssh.user>**`). При использовании шага `4.4` (вариант В) подтверждено `docker=ok`; при переносе `data/ssl` или `data/letsencrypt` на шаге `5.1` учтено наличие файлов с правами `0600` (`unreadable_data > 0`).

**Условия остановки:** Отсутствие прав на чтение `source.project_dir`, `docker-compose.yml` или `.env*`; отсутствие `docker=ok` при запланированном экспорте образов (`4.4.В`).

### 2.11. Проверка синхронизации времени

Место выполнения: исходный и целевой серверы, Bash.

Имена артефактов (TS, db_rollback_<TS>.dump), порядок записей в журнале и сравнение mtime при сверке бэкапов опираются на системные часы.

```bash 
timedatectl | sed -n '1,6p' 
date -u +'%s %FT%TZ' 
```

Ожидаемый результат: System clock synchronized: yes, NTP service: active. Расхождение выводов date -u %s между серверами — не более 2 с.

Условия остановки: расхождение более 2 с — устранить до выполнения шага 3 (сдвиг часов искажает порядок артефактов и делает журнал неупорядочиваемым).

### 2.12. Проверка свободного места на дисках и размера БД

**Место выполнения:** исходный сервер, Bash.

```bash
(
set -Eeuo pipefail

SOURCE_PROJECT_DIR="⚠️**<source.project_dir>**"

[[ -n "$SOURCE_PROJECT_DIR" && "$SOURCE_PROJECT_DIR" != *'⚠️'* && "$SOURCE_PROJECT_DIR" != *'<'* && "$SOURCE_PROJECT_DIR" != *'>'* && "$SOURCE_PROJECT_DIR" != *'['* && "$SOURCE_PROJECT_DIR" != *']'* && "$SOURCE_PROJECT_DIR" != *'**'* ]] \
    || { echo "STOP: SOURCE_PROJECT_DIR не подставлена: '$SOURCE_PROJECT_DIR'" >&2; exit 26; }

df -Ph "$SOURCE_PROJECT_DIR" /tmp | awk 'NR==1 || !seen[$0]++'

SRC_AVAIL="$(df -Ph "$SOURCE_PROJECT_DIR" | awk 'NR==2 {print $4}')"
TMP_AVAIL="$(df -Ph /tmp | awk 'NR==2 {print $4}')"

STEP=2.12
DATE_UTC="$(date -u +%FT%T)"
NOTE="Свободное место на исходном сервере проверено"
OUTPUT="src_avail=${SRC_AVAIL}; tmp_avail=${TMP_AVAIL}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"

for v in TARGET_DIR ROLLBACK_DIR MIGRATION_MODE APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}')"
df -Ph "$TARGET_DIR" "$ROLLBACK_DIR" "$DOCKER_ROOT" | awk 'NR==1 || !seen[$0]++'

TGT_AVAIL="$(df -Ph "$TARGET_DIR" | awk 'NR==2 {print $4}')"
RB_AVAIL="$(df -Ph "$ROLLBACK_DIR" | awk 'NR==2 {print $4}')"
DKR_AVAIL="$(df -Ph "$DOCKER_ROOT" | awk 'NR==2 {print $4}')"

DB_SIZE="n/a (initial)"
if [[ "$MIGRATION_MODE" == "update" ]]; then
    cd "$TARGET_DIR"
    DB_SIZE="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="${APP_IMAGE_TAG:-check}" \
        ./scripts/cc.sh exec -T postgres sh -c \
        'psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -tAc "SELECT pg_size_pretty(pg_database_size(current_database()));"' \
        | tr -d '[:space:]')"
    [[ -n "$DB_SIZE" ]] \
        || { echo "STOP: не удалось получить размер текущей БД на целевом сервере" >&2; exit 1; }
fi

STEP=2.12
DATE_UTC="$(date -u +%FT%T)"
NOTE="Свободное место на целевом сервере проверено"
OUTPUT="tgt_avail=${TGT_AVAIL}; rb_avail=${RB_AVAIL}; docker_avail=${DKR_AVAIL}; db_size=${DB_SIZE}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** На исходном сервере достаточно свободного места в каталоге проекта и `/tmp` для сборки `repo.bundle` и/или архива образов. На целевом сервере достаточно места в `target.project_dir`, `journal.rollback_dir` (при `update` — с запасом под страховочный дамп БД относительно `db_size`) и `DockerRootDir` (под образы и именованные тома `pgdata`, `redisdata`, `static_volume`, `cache_volume`, `exchange_volume`).

**Условия остановки:** Недостаток свободного места на любом из разделов; при `mode = update` — невозможность определить размер БД или нехватка свободного места в `journal.rollback_dir` под страховочный дамп.

### 2.13. Проверка инструментария целевого сервера

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"
REQUIRE_FIREWALL="${REQUIRE_FIREWALL:-}"

for v in TARGET_DIR MIGRATION_MODE APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$MIGRATION_MODE" in
    initial|update) ;;
    *) echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2; exit 25 ;;
esac

MISSING_BASE=()
for bin in python3 rsync tar gzip curl openssl sha256sum; do
    command -v "$bin" >/dev/null 2>&1 || MISSING_BASE+=("$bin")
done
[[ "${#MISSING_BASE[@]}" -eq 0 ]] \
    || { echo "STOP: на целевом сервере отсутствуют обязательные утилиты: ${MISSING_BASE[*]}" >&2; exit 1; }

HTPASSWD_STATUS="ok"
if ! command -v htpasswd >/dev/null 2>&1; then
    if [[ "$MIGRATION_MODE" == "initial" ]]; then
        echo "STOP: утилита htpasswd (пакет apache2-utils) не найдена — требуется для генерации .htpasswd на шаге 4.3 (ADR-010)" >&2
        exit 1
    elif [[ -s "$TARGET_DIR/data/nginx-dynamic/.htpasswd" ]]; then
        HTPASSWD_STATUS="absent (existing .htpasswd)"
    else
        echo "STOP: утилита htpasswd не найдена, а файл '$TARGET_DIR/data/nginx-dynamic/.htpasswd' отсутствует или пуст" >&2
        exit 1
    fi
fi

if [[ -z "$REQUIRE_FIREWALL" ]]; then
    [[ "$APP_ENV" == "production" ]] && REQUIRE_FIREWALL="1" || REQUIRE_FIREWALL="0"
fi

find_bin() {
    local name="$1"
    if command -v "$name" >/dev/null 2>&1; then
        command -v "$name"
    elif [[ -x "/usr/sbin/$name" ]]; then
        printf '/usr/sbin/%s\n' "$name"
    elif [[ -x "/sbin/$name" ]]; then
        printf '/sbin/%s\n' "$name"
    else
        return 1
    fi
}

FW_TOOLS_STATUS="skipped"
if [[ "$REQUIRE_FIREWALL" == "1" ]]; then
    find_bin iptables >/dev/null 2>&1 || { echo "STOP: утилита iptables не найдена (ADR-010)" >&2; exit 1; }
    find_bin ipset >/dev/null 2>&1 || { echo "STOP: утилита ipset не найдена (ADR-010)" >&2; exit 1; }
    FW_TOOLS_STATUS="ok"
fi

STEP=2.13
DATE_UTC="$(date -u +%FT%T)"
NOTE="Инструментарий целевого сервера проверен"
OUTPUT="base=ok; htpasswd=${HTPASSWD_STATUS}; fw_tools=${FW_TOOLS_STATUS}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** На целевом сервере установлены `python3` (нужен `scripts/render_check.py` внутри `scripts/cc.sh`), `rsync`, `tar`, `gzip`, `curl`, `openssl`, `sha256sum`; при `mode = initial` (или отсутствии готового `.htpasswd`) доступна утилита `htpasswd`; для `production` (или `REQUIRE_FIREWALL=1`) доступны `iptables` и `ipset`.

**Условия остановки:** Отсутствие любой обязательной утилиты, отсутствие `htpasswd` при `mode = initial` или отсутствие `iptables`/`ipset` при `REQUIRE_FIREWALL=1`.

## 3. Резервное копирование текущего состояния (только для `update`)

*(Выполняется только при `migration.config.yaml: migration.mode` — `update`. При `initial` весь раздел 3 пропускается — переход сразу к разделу 4. Остановка контейнеров не выполняется: резервное копирование конфигурации и онлайн-дамп БД проходят без прерывания работы стека)*

### 3.0. Проверка отсутствия фоновых конфликтов

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

MIGRATION_MODE="⚠️**<migration.mode>**"

[[ -n "$MIGRATION_MODE" && "$MIGRATION_MODE" != *'⚠️'* && "$MIGRATION_MODE" != *'<'* && "$MIGRATION_MODE" != *'>'* && "$MIGRATION_MODE" != *'['* && "$MIGRATION_MODE" != *']'* && "$MIGRATION_MODE" != *'**'* ]] \
    || { echo "STOP: MIGRATION_MODE не подставлена: '$MIGRATION_MODE'" >&2; exit 26; }

case "$MIGRATION_MODE" in
    initial)
        echo "3.0: mode=initial — раздел 3 пропускается."
        exit 0
        ;;
    update) ;;
    *)
        echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2
        exit 25
        ;;
esac

CONFLICTS="$(pgrep -af '[p]g_dump|[c]ertbot|[u]pdate_cf_ips\.sh|[d]eploy\.sh' || true)"
[[ -z "$CONFLICTS" ]] \
    || { echo "STOP: обнаружены активные фоновые процессы, дождитесь их завершения:"$'\n'"$CONFLICTS" >&2; exit 1; }

echo "=== Текущий crontab ($(id -un)) ==="
crontab -l 2>/dev/null || echo "(crontab пуст)"

STEP=3.0
DATE_UTC="$(date -u +%FT%T)"
NOTE="Фоновые конфликты отсутствуют, стек продолжает работу"
OUTPUT="conflicts=0"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Конкурирующие фоновые задачи (`pg_dump`, `certbot`, `update_cf_ips.sh`, `deploy.sh`) не выполняются; текущий `crontab` выведен для контроля времени ближайших плановых запусков; рабочие контейнеры продолжают обслуживание запросов.

**Условия остановки:** Обнаружен активный конкурирующий процесс или не подставлен параметр `migration.mode`.

### 3.1. Резервное копирование конфигурации, сертификатов и фиксация текущего релиза

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
APP_ENV="⚠️**<application.app_env>**"

for v in TARGET_DIR ROLLBACK_DIR APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

cd "$TARGET_DIR"

WEB_CID="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="${APP_IMAGE_TAG:-current}" ./scripts/cc.sh ps -q web | head -n 1)"
[[ -n "$WEB_CID" ]] \
    || { echo "STOP: запущенный контейнер web не найден" >&2; exit 1; }

PREV_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$WEB_CID")"
PREV_IMAGE_TAG="${PREV_IMAGE##*:}"
[[ -n "$PREV_IMAGE" && -n "$PREV_IMAGE_TAG" ]] \
    || { echo "STOP: не удалось определить текущий образ/тег контейнера web" >&2; exit 1; }

ITEMS=()
shopt -s nullglob
for f in .env*; do
    ITEMS+=("$f")
done
shopt -u nullglob

for p in docker-compose.yml nginx scripts data/nginx-dynamic data/ssl data/letsencrypt; do
    [[ -e "$p" ]] && ITEMS+=("$p")
done

[[ "${#ITEMS[@]}" -gt 0 ]] \
    || { echo "STOP: не найдены файлы конфигурации для резервного копирования" >&2; exit 1; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$ROLLBACK_DIR/config_backup_${TS}.tar.gz"

TAR_CMD=(tar)
NEED_CHOWN=0
if [[ "${EUID}" -ne 0 ]] && [[ -n "$(find "${ITEMS[@]}" ! -readable 2>/dev/null | head -n 1)" ]]; then
    TAR_CMD=(sudo -n tar)
    NEED_CHOWN=1
fi

"${TAR_CMD[@]}" -czf "$ARCHIVE" "${ITEMS[@]}"
if [[ "$NEED_CHOWN" -eq 1 ]]; then
    sudo -n chown "$(id -u):$(id -g)" "$ARCHIVE"
fi

chmod 600 "$ARCHIVE"
sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"
chmod 600 "${ARCHIVE}.sha256"

cat > "$ROLLBACK_DIR/prev_release.env" <<EOF
PREV_IMAGE=$PREV_IMAGE
PREV_IMAGE_TAG=$PREV_IMAGE_TAG
CONFIG_BACKUP_ARCHIVE=$ARCHIVE
BACKUP_TIMESTAMP_UTC=$TS
EOF
chmod 600 "$ROLLBACK_DIR/prev_release.env"

ARCHIVE_SIZE="$(du -h "$ARCHIVE" | cut -f1)"

STEP=3.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Конфигурация и сертификаты заархивированы, текущий тег зафиксирован"
OUTPUT="prev_tag=${PREV_IMAGE_TAG}; archive=$(basename -- "$ARCHIVE"); size=${ARCHIVE_SIZE}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** В `journal.rollback_dir` создан архив `config_backup_<timestamp>.tar.gz` (права `0600`) с контрольной суммой `.sha256`, включающий `.env*`, `docker-compose.yml`, `nginx/`, `scripts/`, `data/nginx-dynamic/`, `data/ssl/` и `data/letsencrypt/`; в `prev_release.env` сохранены текущий образ и тег контейнера `web` для быстрого отката.

**Условия остановки:** Отсутствие запущенного контейнера `web`, невозможность определить текущий тег образа или ошибка чтения/упаковки файлов конфигурации и сертификатов.

### 3.2. Страховочный онлайн-дамп БД PostgreSQL на целевом сервере

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
APP_ENV="⚠️**<application.app_env>**"

for v in TARGET_DIR ROLLBACK_DIR APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

cd "$TARGET_DIR"

PG_CID="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="${APP_IMAGE_TAG:-current}" ./scripts/cc.sh ps -q postgres | head -n 1)"
[[ -n "$PG_CID" ]] \
    || { echo "STOP: запущенный контейнер postgres не найден" >&2; exit 1; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="$ROLLBACK_DIR/db_backup_${TS}.dump"

APP_ENV="$APP_ENV" APP_IMAGE_TAG="${APP_IMAGE_TAG:-current}" \
    ./scripts/cc.sh exec -T postgres sh -c \
    'pg_dump -Fc -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"' > "$DUMP_FILE"

[[ -s "$DUMP_FILE" ]] \
    || { rm -f "$DUMP_FILE"; echo "STOP: файл дампа БД пуст" >&2; exit 1; }

APP_ENV="$APP_ENV" APP_IMAGE_TAG="${APP_IMAGE_TAG:-current}" \
    ./scripts/cc.sh exec -T postgres pg_restore -l < "$DUMP_FILE" >/dev/null \
    || { echo "STOP: дамп БД '$DUMP_FILE' не прошёл проверку чтения pg_restore -l" >&2; exit 1; }

chmod 600 "$DUMP_FILE"
sha256sum "$DUMP_FILE" > "${DUMP_FILE}.sha256"
chmod 600 "${DUMP_FILE}.sha256"

touch "$ROLLBACK_DIR/prev_release.env"
grep -v '^DB_BACKUP_FILE=' "$ROLLBACK_DIR/prev_release.env" > "$ROLLBACK_DIR/prev_release.env.tmp" || true
printf 'DB_BACKUP_FILE=%s\n' "$DUMP_FILE" >> "$ROLLBACK_DIR/prev_release.env.tmp"
mv "$ROLLBACK_DIR/prev_release.env.tmp" "$ROLLBACK_DIR/prev_release.env"
chmod 600 "$ROLLBACK_DIR/prev_release.env"

DUMP_SIZE="$(du -h "$DUMP_FILE" | cut -f1)"

STEP=3.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Страховочный онлайн-дамп БД создан и проверен"
OUTPUT="dump=$(basename -- "$DUMP_FILE"); size=${DUMP_SIZE}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Без остановки контейнеров в `journal.rollback_dir` создан непустой custom-дамп `db_backup_<timestamp>.dump` (права `0600`) с контрольной суммой `.sha256`; целостность оглавления подтверждена через `pg_restore -l`; путь к дампу зафиксирован в `prev_release.env` (`DB_BACKUP_FILE`) для раздела 8.

**Условия остановки:** Отсутствие запущенного контейнера `postgres`, ошибка `pg_dump`, нулевой размер файла дампа или сбой проверки `pg_restore -l`.

## 4. Доставка кода, конфигурации и образов

### 4.1. Подготовка рабочего дерева на целевом сервере

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
CODE_DELIVERY_METHOD="⚠️**<code_delivery.method>**"

for v in TARGET_DIR ROLLBACK_DIR MIGRATION_MODE CODE_DELIVERY_METHOD; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$MIGRATION_MODE" in
    initial|update) ;;
    *) echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2; exit 25 ;;
esac

case "$CODE_DELIVERY_METHOD" in
    remote_git|local_git|no_git) ;;
    *) echo "STOP: CODE_DELIVERY_METHOD='$CODE_DELIVERY_METHOD', ожидается 'remote_git', 'local_git' или 'no_git'" >&2; exit 25 ;;
esac

cd "$TARGET_DIR"

if [[ "$MIGRATION_MODE" == "initial" ]]; then
    EXTRA_ITEMS="$(find . -mindepth 1 -maxdepth 1 ! -name 'data' ! -name '.git' | sed 's|^\./||' || true)"
    [[ -z "$EXTRA_ITEMS" ]] \
        || { echo "STOP: целевой каталог '$TARGET_DIR' содержит посторонние файлы при mode=initial:"$'\n'"$EXTRA_ITEMS" >&2; exit 1; }

    case "$CODE_DELIVERY_METHOD" in
        remote_git|local_git)
            command -v git >/dev/null 2>&1 || { echo "STOP: утилита git не найдена на целевом сервере" >&2; exit 1; }
            [[ -d .git ]] || git init -q
            TREE_STATE="initialized (.git)"
            ;;
        no_git)
            TREE_STATE="ready (no_git)"
            ;;
    esac
else
    case "$CODE_DELIVERY_METHOD" in
        remote_git|local_git)
            command -v git >/dev/null 2>&1 || { echo "STOP: утилита git не найдена на целевом сервере" >&2; exit 1; }
            [[ -d .git ]] || { echo "STOP: в '$TARGET_DIR' отсутствует .git при mode=update и method=$CODE_DELIVERY_METHOD" >&2; exit 1; }

            DIRTY="$(git status --porcelain --untracked-files=no)"
            [[ -z "$DIRTY" ]] \
                || { echo "STOP: в '$TARGET_DIR' есть незакоммиченные изменения в отслеживаемых файлах:"$'\n'"$DIRTY" >&2; exit 1; }

            PREV_GIT_COMMIT="$(git rev-parse HEAD)"
            touch "$ROLLBACK_DIR/prev_release.env"
            grep -v '^PREV_GIT_COMMIT=' "$ROLLBACK_DIR/prev_release.env" > "$ROLLBACK_DIR/prev_release.env.tmp" || true
            printf 'PREV_GIT_COMMIT=%s\n' "$PREV_GIT_COMMIT" >> "$ROLLBACK_DIR/prev_release.env.tmp"
            mv "$ROLLBACK_DIR/prev_release.env.tmp" "$ROLLBACK_DIR/prev_release.env"
            chmod 600 "$ROLLBACK_DIR/prev_release.env"

            TREE_STATE="clean (prev_commit=${PREV_GIT_COMMIT:0:12})"
            ;;
        no_git)
            [[ -f docker-compose.yml ]] \
                || { echo "STOP: в '$TARGET_DIR' отсутствует docker-compose.yml при mode=update и method=no_git" >&2; exit 1; }
            TREE_STATE="ready (no_git, existing project)"
            ;;
    esac
fi

STEP=4.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Рабочее дерево целевого каталога подготовлено"
OUTPUT="mode=${MIGRATION_MODE}; method=${CODE_DELIVERY_METHOD}; state=${TREE_STATE}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Целевой каталог готов к приёму кода согласно `migration.mode` и `code_delivery.method`: при `initial` проверено отсутствие посторонних файлов (кроме `data/`) и при необходимости инициализирован `.git`; при `update` подтверждена чистота рабочего дерева и зафиксирован `PREV_GIT_COMMIT` в `prev_release.env`.

**Условия остановки:** Неподставленные параметры, наличие посторонних файлов при `initial`, отсутствие `.git` / `docker-compose.yml` или наличие локальных правок в отслеживаемых файлах при `update`.

### 4.2. Доставка кода проекта

**Место выполнения:** целевой сервер, Bash.

*(Выполняется строго один вариант в соответствии со значением `migration.config.yaml: code_delivery.method` — `remote_git`, `local_git` или `no_git`)*

#### Вариант А (`code_delivery.method = remote_git`)

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
CODE_DELIVERY_METHOD="⚠️**<code_delivery.method>**"
REMOTE_URL="⚠️**<code_delivery.remote_url>**"
CODE_REF="⚠️**<code_delivery.ref>**"

for v in TARGET_DIR CODE_DELIVERY_METHOD REMOTE_URL CODE_REF; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$CODE_DELIVERY_METHOD" == "remote_git" ]] \
    || { echo "STOP: выбран Вариант А (remote_git), но CODE_DELIVERY_METHOD='$CODE_DELIVERY_METHOD'" >&2; exit 25; }

cd "$TARGET_DIR"

if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi

git fetch --prune --tags origin

if git rev-parse --verify --quiet "refs/remotes/origin/${CODE_REF}^{commit}" >/dev/null; then
    TARGET_COMMIT="$(git rev-parse "refs/remotes/origin/${CODE_REF}^{commit}")"
elif git rev-parse --verify --quiet "refs/tags/${CODE_REF}^{commit}" >/dev/null; then
    TARGET_COMMIT="$(git rev-parse "refs/tags/${CODE_REF}^{commit}")"
elif git rev-parse --verify --quiet "${CODE_REF}^{commit}" >/dev/null; then
    TARGET_COMMIT="$(git rev-parse "${CODE_REF}^{commit}")"
else
    echo "STOP: ссылка code_delivery.ref='$CODE_REF' не найдена в origin" >&2
    exit 1
fi

git checkout -q --detach "$TARGET_COMMIT"

for req in docker-compose.yml scripts/deploy.sh scripts/cc.sh; do
    [[ -f "$req" ]] || { echo "STOP: в доставленном коде отсутствует обязательный файл '$req'" >&2; exit 1; }
done
chmod +x scripts/*.sh

STEP=4.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Код доставлен из удалённого Git-репозитория"
OUTPUT="method=remote_git; ref=${CODE_REF}; commit=${TARGET_COMMIT:0:12}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

#### Вариант Б (`code_delivery.method = local_git`)

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
CODE_DELIVERY_METHOD="⚠️**<code_delivery.method>**"
CODE_REF="⚠️**<code_delivery.ref>**"
SOURCE_SSH_PORT="⚠️**<source.ssh.port>**"
SOURCE_SSH_USER="⚠️**<source.ssh.user>**"
SOURCE_SSH_HOST="⚠️**<source.ssh.host>**"
SOURCE_PROJECT_DIR="⚠️**<source.project_dir>**"

for v in TARGET_DIR CODE_DELIVERY_METHOD CODE_REF SOURCE_SSH_PORT SOURCE_SSH_USER SOURCE_SSH_HOST SOURCE_PROJECT_DIR; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$CODE_DELIVERY_METHOD" == "local_git" ]] \
    || { echo "STOP: выбран Вариант Б (local_git), но CODE_DELIVERY_METHOD='$CODE_DELIVERY_METHOD'" >&2; exit 25; }

TS="$(date -u +%Y%m%dT%H%M%SZ)_$$"
SRC_BUNDLE="/tmp/repo_${TS}.bundle"
TGT_BUNDLE="/tmp/repo_${TS}.bundle"

cleanup() {
    rm -f "${TGT_BUNDLE:-}"
    ssh -p "$SOURCE_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=5 \
        "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}" "rm -f '${SRC_BUNDLE:-}'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

TARGET_COMMIT="$(
    ssh -p "$SOURCE_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=10 \
        "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}" bash -s -- "$SOURCE_PROJECT_DIR" "$CODE_REF" "$SRC_BUNDLE" <<'EOF'
set -Eeuo pipefail
SRC_DIR="$1"
REF="$2"
BUNDLE_PATH="$3"

cd "$SRC_DIR"
[[ -d .git ]] || { echo "STOP: на исходном сервере в '$SRC_DIR' отсутствует .git" >&2; exit 1; }

if git rev-parse --verify --quiet "refs/heads/${REF}^{commit}" >/dev/null; then
    COMMIT="$(git rev-parse "refs/heads/${REF}^{commit}")"
elif git rev-parse --verify --quiet "refs/tags/${REF}^{commit}" >/dev/null; then
    COMMIT="$(git rev-parse "refs/tags/${REF}^{commit}")"
elif git rev-parse --verify --quiet "${REF}^{commit}" >/dev/null; then
    COMMIT="$(git rev-parse "${REF}^{commit}")"
else
    echo "STOP: ссылка code_delivery.ref='$REF' не найдена в репозитории источника" >&2
    exit 1
fi

git bundle create "$BUNDLE_PATH" "$COMMIT" >/dev/null
printf '%s\n' "$COMMIT"
EOF
)"

[[ -n "$TARGET_COMMIT" ]] \
    || { echo "STOP: не удалось создать git bundle на исходном сервере" >&2; exit 1; }

rsync -az -e "ssh -p $SOURCE_SSH_PORT -o BatchMode=yes -o ConnectTimeout=10" \
    "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}:${SRC_BUNDLE}" "$TGT_BUNDLE"

cd "$TARGET_DIR"
git bundle verify "$TGT_BUNDLE" >/dev/null
git fetch -q "$TGT_BUNDLE" "$TARGET_COMMIT"
git checkout -q --detach "$TARGET_COMMIT"

for req in docker-compose.yml scripts/deploy.sh scripts/cc.sh; do
    [[ -f "$req" ]] || { echo "STOP: в доставленном коде отсутствует обязательный файл '$req'" >&2; exit 1; }
done
chmod +x scripts/*.sh

STEP=4.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Код доставлен через git bundle с исходного сервера"
OUTPUT="method=local_git; ref=${CODE_REF}; commit=${TARGET_COMMIT:0:12}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

#### Вариант В (`code_delivery.method = no_git`)

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
CODE_DELIVERY_METHOD="⚠️**<code_delivery.method>**"
SOURCE_SSH_PORT="⚠️**<source.ssh.port>**"
SOURCE_SSH_USER="⚠️**<source.ssh.user>**"
SOURCE_SSH_HOST="⚠️**<source.ssh.host>**"
SOURCE_PROJECT_DIR="⚠️**<source.project_dir>**"

for v in TARGET_DIR CODE_DELIVERY_METHOD SOURCE_SSH_PORT SOURCE_SSH_USER SOURCE_SSH_HOST SOURCE_PROJECT_DIR; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$CODE_DELIVERY_METHOD" == "no_git" ]] \
    || { echo "STOP: выбран Вариант В (no_git), но CODE_DELIVERY_METHOD='$CODE_DELIVERY_METHOD'" >&2; exit 25; }

rsync -az --delete \
    --include='.env.example' \
    --exclude='.git/' \
    --exclude='.env*' \
    --exclude='data/' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    -e "ssh -p $SOURCE_SSH_PORT -o BatchMode=yes -o ConnectTimeout=10" \
    "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}:${SOURCE_PROJECT_DIR%/}/" "${TARGET_DIR%/}/"

cd "$TARGET_DIR"
for req in docker-compose.yml scripts/deploy.sh scripts/cc.sh; do
    [[ -f "$req" ]] || { echo "STOP: в доставленном коде отсутствует обязательный файл '$req'" >&2; exit 1; }
done
chmod +x scripts/*.sh

STEP=4.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Код синхронизирован с исходного сервера через rsync"
OUTPUT="method=no_git; source=${SOURCE_SSH_HOST}:${SOURCE_PROJECT_DIR}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Код проекта целевой версии развёрнут в `target.project_dir` (для `remote_git` и `local_git` — в состоянии `detached HEAD` на точном коммите `code_delivery.ref`; для `no_git` — синхронизирован без перезаписи целевых `.env*` и каталога `data/`), подтверждено наличие `docker-compose.yml`, `scripts/deploy.sh`, `scripts/cc.sh` и выставлены права `+x` на `scripts/*.sh`.

**Условия остановки:** Несоответствие выбранного варианта значению `code_delivery.method`, недоступность удалённого репозитория или исходного сервера по SSH, отсутствие ветки/тега/коммита `code_delivery.ref`, повреждение `git bundle` либо отсутствие обязательных файлов стека (`docker-compose.yml`, `scripts/deploy.sh`, `scripts/cc.sh`).

### 4.3. Доставка и настройка конфигурации окружения (`.env` и `.htpasswd`)

**Место выполнения:** целевой сервер, Bash.

#### 4.3.1. Доставка (для `initial`) или сверка ключей (для `update`) файлов `.env*`

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"

for v in TARGET_DIR MIGRATION_MODE APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

cd "$TARGET_DIR"

case "$MIGRATION_MODE" in
    initial)
        SOURCE_SSH_PORT="⚠️**<source.ssh.port>**"
        SOURCE_SSH_USER="⚠️**<source.ssh.user>**"
        SOURCE_SSH_HOST="⚠️**<source.ssh.host>**"
        SOURCE_PROJECT_DIR="⚠️**<source.project_dir>**"

        for v in SOURCE_SSH_PORT SOURCE_SSH_USER SOURCE_SSH_HOST SOURCE_PROJECT_DIR; do
            val="${!v}"
            [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
                || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
        done

        rsync -az \
            --include='.env' \
            --include=".env.${APP_ENV}" \
            --exclude='*' \
            -e "ssh -p $SOURCE_SSH_PORT -o BatchMode=yes -o ConnectTimeout=10" \
            "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}:${SOURCE_PROJECT_DIR%/}/" "${TARGET_DIR%/}/"

        [[ -f ".env.${APP_ENV}" || -f ".env" ]] \
            || { echo "STOP: с исходного сервера не скопирован ни .env.${APP_ENV}, ни .env" >&2; exit 1; }

        shopt -s nullglob
        for f in .env .env.*; do
            [[ "$f" == ".env.example" ]] && continue
            chmod 600 "$f"
        done
        shopt -u nullglob

        ENV_STATE="copied from source (edit target-specific values before 4.3.2)"
        ;;
    update)
        [[ -f ".env.${APP_ENV}" || -f ".env" ]] \
            || { echo "STOP: на целевом сервере отсутствуют .env.${APP_ENV} и .env при mode=update" >&2; exit 1; }

        shopt -s nullglob
        for f in .env .env.*; do
            [[ "$f" == ".env.example" ]] && continue
            chmod 600 "$f"
        done
        shopt -u nullglob

        if [[ -f ".env.example" ]]; then
            MISSING_KEYS="$(python3 - "$APP_ENV" <<'PY'
import re, sys
from pathlib import Path

app_env = sys.argv[1]
key_re = re.compile(r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=')

def read_keys(path: Path) -> set[str]:
    keys = set()
    if not path.is_file():
        return keys
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = key_re.match(s)
        if m:
            keys.add(m.group(1))
    return keys

example_keys = read_keys(Path('.env.example'))
present_keys = read_keys(Path('.env')) | read_keys(Path(f'.env.{app_env}'))
missing = sorted(example_keys - present_keys)
if missing:
    print('\n'.join(missing))
PY
)"
            [[ -z "$MISSING_KEYS" ]] \
                || { echo "STOP: в целевых .env / .env.${APP_ENV} отсутствуют новые ключи из .env.example:"$'\n'"$MISSING_KEYS" >&2; exit 1; }
        fi

        ENV_STATE="preserved and verified against .env.example"
        ;;
    *)
        echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2
        exit 25
        ;;
esac

STEP=4.3.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Файлы окружения подготовлены"
OUTPUT="mode=${MIGRATION_MODE}; app_env=${APP_ENV}; state=${ENV_STATE}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

*(При `migration.mode = initial` перед запуском `4.3.2` проверьте в `.env.<APP_ENV>` целевые значения: `APP_ENV`, домен, секреты, параметры БД и `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` для закрытых зон Nginx)*

#### 4.3.2. Генерация `.htpasswd` из `.env*` и валидация конфигурации стека

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"
FORCE_HTPASSWD="${FORCE_HTPASSWD:-0}"

for v in TARGET_DIR MIGRATION_MODE APP_ENV; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

cd "$TARGET_DIR"

HTPASSWD_FILE="$TARGET_DIR/data/nginx-dynamic/.htpasswd"
HTPASSWD_STATE="preserved"

if [[ "$MIGRATION_MODE" == "initial" || ! -s "$HTPASSWD_FILE" || "$FORCE_HTPASSWD" == "1" ]]; then
    command -v htpasswd >/dev/null 2>&1 \
        || { echo "STOP: утилита htpasswd не найдена (пакет apache2-utils)" >&2; exit 1; }

    CREDS="$(python3 - "$APP_ENV" <<'PY'
import re, sys
from pathlib import Path

app_env = sys.argv[1]
kv_re = re.compile(r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
env_map: dict[str, str] = {}

for fname in ('.env', f'.env.{app_env}'):
    p = Path(fname)
    if not p.is_file():
        continue
    for line in p.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = kv_re.match(s)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        env_map[k] = v

user = env_map.get('BASIC_AUTH_USER', '')
pwd = env_map.get('BASIC_AUTH_PASSWORD', '')
if not user or not pwd:
    sys.exit(2)
sys.stdout.write(f"{user}\n{pwd}")
PY
)" || { echo "STOP: в .env или .env.${APP_ENV} не заданы BASIC_AUTH_USER и BASIC_AUTH_PASSWORD" >&2; exit 1; }

    AUTH_USER="$(printf '%s' "$CREDS" | sed -n '1p')"
    AUTH_PASS="$(printf '%s' "$CREDS" | sed -n '2p')"

    printf '%s\n' "$AUTH_PASS" | htpasswd -biB "$HTPASSWD_FILE" "$AUTH_USER" >/dev/null
    chmod 644 "$HTPASSWD_FILE"
    unset CREDS AUTH_USER AUTH_PASS
    HTPASSWD_STATE="generated"
fi

APP_ENV="$APP_ENV" APP_IMAGE_TAG="${APP_IMAGE_TAG:-check}" ./scripts/cc.sh config -q

STEP=4.3.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Файл .htpasswd готов, конфигурация Compose и Nginx провалидирована"
OUTPUT="htpasswd=${HTPASSWD_STATE}; config=ok"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Файлы `.env` и `.env.<APP_ENV>` имеют права `0600` (при `initial` скопированы с исходного сервера и адаптированы под целевое окружение; при `update` сохранены без перезаписи и сверены с `.env.example`); файл `data/nginx-dynamic/.htpasswd` сгенерирован из `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` (права `0644`); команда `./scripts/cc.sh config -q` завершилась без ошибок.

**Условия остановки:** Отсутствие `.env*` на исходном (при `initial`) или целевом (при `update`) сервере; наличие незаполненных новых ключей из `.env.example` при `update`; отсутствие `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` при генерации `.htpasswd` или ошибка валидации `./scripts/cc.sh config -q`.

### 4.4. Доставка или сборка Docker-образов

**Место выполнения:** целевой сервер, Bash.

*(Выполняется строго один вариант в соответствии со значением `migration.config.yaml: images.method` — `registry`, `build` или `transfer`. Во всех вариантах инфраструктурные образы стека подтягиваются из registry через `./scripts/cc.sh pull`, чтобы к моменту cutover все образы находились в локальном кэше Docker)*

#### Вариант А (`images.method = registry`)

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
APP_ENV="⚠️**<application.app_env>**"
IMAGES_METHOD="⚠️**<images.method>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"

for v in TARGET_DIR APP_ENV IMAGES_METHOD APP_IMAGE_TAG; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$IMAGES_METHOD" == "registry" ]] \
    || { echo "STOP: выбран Вариант А (registry), но IMAGES_METHOD='$IMAGES_METHOD'" >&2; exit 25; }

cd "$TARGET_DIR"

APP_IMAGE="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh config --images \
    | awk -v tag=":${APP_IMAGE_TAG}" 'length($0) >= length(tag) && substr($0, length($0)-length(tag)+1) == tag {print; exit}')"
[[ -n "$APP_IMAGE" ]] \
    || { echo "STOP: не удалось определить образ приложения с тегом ':${APP_IMAGE_TAG}' из docker-compose.yml" >&2; exit 1; }

APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh pull

while IFS= read -r img; do
    [[ -z "$img" ]] && continue
    docker image inspect "$img" >/dev/null 2>&1 \
        || { echo "STOP: обязательный образ стека '$img' отсутствует в локальном Docker" >&2; exit 1; }
done < <(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh config --images)

APP_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$APP_IMAGE")"

STEP=4.4
DATE_UTC="$(date -u +%FT%T)"
NOTE="Образ приложения и базовые образы стека загружены из registry"
OUTPUT="method=registry; app_image=${APP_IMAGE}; id=${APP_IMAGE_ID:0:19}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

#### Вариант Б (`images.method = build`)

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
APP_ENV="⚠️**<application.app_env>**"
IMAGES_METHOD="⚠️**<images.method>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"

for v in TARGET_DIR APP_ENV IMAGES_METHOD APP_IMAGE_TAG; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$IMAGES_METHOD" == "build" ]] \
    || { echo "STOP: выбран Вариант Б (build), но IMAGES_METHOD='$IMAGES_METHOD'" >&2; exit 25; }

cd "$TARGET_DIR"

APP_IMAGE="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh config --images \
    | awk -v tag=":${APP_IMAGE_TAG}" 'length($0) >= length(tag) && substr($0, length($0)-length(tag)+1) == tag {print; exit}')"
[[ -n "$APP_IMAGE" ]] \
    || { echo "STOP: не удалось определить образ приложения с тегом ':${APP_IMAGE_TAG}' из docker-compose.yml" >&2; exit 1; }

APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh pull --ignore-buildable
APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh build

while IFS= read -r img; do
    [[ -z "$img" ]] && continue
    docker image inspect "$img" >/dev/null 2>&1 \
        || { echo "STOP: обязательный образ стека '$img' отсутствует в локальном Docker" >&2; exit 1; }
done < <(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh config --images)

APP_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$APP_IMAGE")"

STEP=4.4
DATE_UTC="$(date -u +%FT%T)"
NOTE="Базовые образы загружены, образ приложения собран на целевом сервере"
OUTPUT="method=build; app_image=${APP_IMAGE}; id=${APP_IMAGE_ID:0:19}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

#### Вариант В (`images.method = transfer`)

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
APP_ENV="⚠️**<application.app_env>**"
IMAGES_METHOD="⚠️**<images.method>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"
SOURCE_SSH_PORT="⚠️**<source.ssh.port>**"
SOURCE_SSH_USER="⚠️**<source.ssh.user>**"
SOURCE_SSH_HOST="⚠️**<source.ssh.host>**"

for v in TARGET_DIR APP_ENV IMAGES_METHOD APP_IMAGE_TAG SOURCE_SSH_PORT SOURCE_SSH_USER SOURCE_SSH_HOST; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$IMAGES_METHOD" == "transfer" ]] \
    || { echo "STOP: выбран Вариант В (transfer), но IMAGES_METHOD='$IMAGES_METHOD'" >&2; exit 25; }

cd "$TARGET_DIR"

APP_IMAGE="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh config --images \
    | awk -v tag=":${APP_IMAGE_TAG}" 'length($0) >= length(tag) && substr($0, length($0)-length(tag)+1) == tag {print; exit}')"
[[ -n "$APP_IMAGE" ]] \
    || { echo "STOP: не удалось определить образ приложения с тегом ':${APP_IMAGE_TAG}' из docker-compose.yml" >&2; exit 1; }

TS="$(date -u +%Y%m%dT%H%M%SZ)_$$"
SRC_ARCHIVE="/tmp/app_image_${TS}.tar.gz"
TGT_ARCHIVE="/tmp/app_image_${TS}.tar.gz"

cleanup() {
    rm -f "${TGT_ARCHIVE:-}"
    ssh -p "$SOURCE_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=5 \
        "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}" "rm -f '${SRC_ARCHIVE:-}'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

SRC_SHA256="$(
    ssh -p "$SOURCE_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=10 \
        "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}" bash -s -- "$APP_IMAGE" "$SRC_ARCHIVE" <<'EOF'
set -Eeuo pipefail
IMG="$1"
ARCHIVE="$2"

docker image inspect "$IMG" >/dev/null 2>&1 \
    || { echo "STOP: образ '$IMG' не найден в Docker на исходном сервере" >&2; exit 1; }

docker save "$IMG" | gzip -1 > "$ARCHIVE"
sha256sum "$ARCHIVE" | awk '{print $1}'
EOF
)"

[[ -n "$SRC_SHA256" ]] \
    || { echo "STOP: не удалось экспортировать образ '$APP_IMAGE' на исходном сервере" >&2; exit 1; }

rsync -az -e "ssh -p $SOURCE_SSH_PORT -o BatchMode=yes -o ConnectTimeout=10" \
    "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}:${SRC_ARCHIVE}" "$TGT_ARCHIVE"

TGT_SHA256="$(sha256sum "$TGT_ARCHIVE" | awk '{print $1}')"
[[ "$SRC_SHA256" == "$TGT_SHA256" ]] \
    || { echo "STOP: не совпала контрольная сумма архива образа (src=$SRC_SHA256, tgt=$TGT_SHA256)" >&2; exit 1; }

gunzip -c "$TGT_ARCHIVE" | docker load >/dev/null
rm -f "$TGT_ARCHIVE"

APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh pull --ignore-buildable

while IFS= read -r img; do
    [[ -z "$img" ]] && continue
    docker image inspect "$img" >/dev/null 2>&1 \
        || { echo "STOP: обязательный образ стека '$img' отсутствует в локальном Docker" >&2; exit 1; }
done < <(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" ./scripts/cc.sh config --images)

APP_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$APP_IMAGE")"

STEP=4.4
DATE_UTC="$(date -u +%FT%T)"
NOTE="Образ приложения перенесён с источника, базовые образы загружены из registry"
OUTPUT="method=transfer; app_image=${APP_IMAGE}; id=${APP_IMAGE_ID:0:19}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Образ приложения с тегом `images.app_tag` и все инфраструктурные образы из `docker-compose.yml` (`postgres`, `redis`, `nginx`, `certbot` и др.) присутствуют в локальном кэше Docker на целевом сервере; при `method = transfer` контрольная сумма архива совпала, а временные файлы `.tar.gz` удалены на обоих серверах.

**Условия остановки:** Несоответствие выбранного варианта значению `images.method`, отсутствие авторизации/доступа к container registry (для `registry` или базовых образов), ошибка сборки (`build`), отсутствие образа `images.app_tag` на исходном сервере или несовпадение `sha256sum` при переносе (`transfer`).

## 5. Перенос файловых хранилищ

*(Перенос данных БД между серверами выведен за рамки процедуры согласно разделу 1, поэтому шаги блокировки записи и снятия дампа БД на исходном сервере исключены. Если в `migration.config.yaml` отсутствуют элементы `storage.items` с `transfer: true`, раздел 5 пропускается полностью)*

### 5.1. Перенос выбранных файловых хранилищ

**Место выполнения:** целевой сервер, Bash.

*(Выполняется по одному запуску на каждый элемент `migration.config.yaml: storage.items[id=...]`, у которого `transfer: true`, например `data/ssl` или `data/letsencrypt`. При отсутствии элементов с `transfer: true` шаг пропускается)*

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
SOURCE_PROJECT_DIR="⚠️**<source.project_dir>**"
SOURCE_SSH_PORT="⚠️**<source.ssh.port>**"
SOURCE_SSH_USER="⚠️**<source.ssh.user>**"
SOURCE_SSH_HOST="⚠️**<source.ssh.host>**"
ITEM_ID="⚠️**<storage.items[id=...].id>**"
ITEM_TRANSFER="⚠️**<storage.items[id=...].transfer>**"
SRC_REL_PATH="⚠️**<storage.items[id=...].source_relative_path>**"
TGT_REL_PATH="⚠️**<storage.items[id=...].target_relative_path>**"

for v in TARGET_DIR SOURCE_PROJECT_DIR SOURCE_SSH_PORT SOURCE_SSH_USER SOURCE_SSH_HOST ITEM_ID ITEM_TRANSFER SRC_REL_PATH TGT_REL_PATH; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$ITEM_TRANSFER" in
    true) ;;
    false)
        echo "5.1: для элемента '${ITEM_ID}' задано transfer=false — перенос пропускается."
        exit 0
        ;;
    *)
        echo "STOP: ITEM_TRANSFER='$ITEM_TRANSFER' для '${ITEM_ID}', ожидается 'true' или 'false'" >&2
        exit 25
        ;;
esac

[[ "$TARGET_DIR" == /* && "$SOURCE_PROJECT_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR и SOURCE_PROJECT_DIR должны быть абсолютными путями" >&2; exit 26; }

TARGET_DIR="${TARGET_DIR%/}"
SOURCE_PROJECT_DIR="${SOURCE_PROJECT_DIR%/}"
SRC_REL_PATH="${SRC_REL_PATH#./}"; SRC_REL_PATH="${SRC_REL_PATH%/}"
TGT_REL_PATH="${TGT_REL_PATH#./}"; TGT_REL_PATH="${TGT_REL_PATH%/}"

for rel in "$SRC_REL_PATH" "$TGT_REL_PATH"; do
    [[ -n "$rel" && "$rel" != /* && "$rel" != "." && ! "$rel" =~ (^|/)\.\.(/|$) ]] \
        || { echo "STOP: недопустимый относительный путь хранилища: '$rel'" >&2; exit 26; }
done

SRC_FULL_PATH="${SOURCE_PROJECT_DIR}/${SRC_REL_PATH}"
TGT_FULL_PATH="${TARGET_DIR}/${TGT_REL_PATH}"

if [[ -d "$TGT_FULL_PATH" ]]; then
    if ! EXISTING_FILES="$(find "$TGT_FULL_PATH" -mindepth 1 -printf '%TY-%Tm-%Td %TH:%TM:%.2TS %TZ\t%y\t%s\t%P\n' 2>/dev/null)"; then
        if [[ "${EUID}" -ne 0 ]]; then
            EXISTING_FILES="$(sudo -n find "$TGT_FULL_PATH" -mindepth 1 -printf '%TY-%Tm-%Td %TH:%TM:%.2TS %TZ\t%y\t%s\t%P\n')"
        else
            echo "STOP: не удалось просканировать целевой каталог '$TGT_FULL_PATH'" >&2
            exit 1
        fi
    fi

    if [[ -n "$EXISTING_FILES" ]]; then
        echo "STOP: целевой каталог '$TGT_FULL_PATH' не пуст. Перенос элемента '${ITEM_ID}' остановлен во избежание перезаписи:" >&2
        printf '%s\n' "$EXISTING_FILES" >&2
        echo "Проверьте даты файлов. Для выполнения переноса предварительно очистите '$TGT_FULL_PATH' вручную либо установите transfer=false." >&2
        exit 1
    fi
elif [[ -e "$TGT_FULL_PATH" ]]; then
    echo "STOP: целевой путь '$TGT_FULL_PATH' существует и не является каталогом" >&2
    exit 1
fi

mkdir -p "$TGT_FULL_PATH"

RSYNC_CMD=(rsync)
if [[ "${EUID}" -ne 0 ]]; then
    RSYNC_CMD=(sudo -n rsync)
fi

"${RSYNC_CMD[@]}" -aHAX --numeric-ids --delete \
    --rsync-path="sudo -n rsync" \
    -e "ssh -p $SOURCE_SSH_PORT -o BatchMode=yes -o ConnectTimeout=10" \
    "${SOURCE_SSH_USER}@${SOURCE_SSH_HOST}:${SRC_FULL_PATH}/" "${TGT_FULL_PATH}/"

STEP=5.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Файловое хранилище перенесено с исходного сервера"
OUTPUT="id=${ITEM_ID}; src=${SRC_REL_PATH}; tgt=${TGT_REL_PATH}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Содержимое каталога `source_relative_path` перенесено в `target_relative_path` с сохранением владельцев и прав доступа (`UID`/`GID`, режимы `0600`/`0644`).

**Условия остановки:** Неподставленные или некорректные параметры пути, наличие существующих файлов в целевом каталоге (выводится список с датами модификации), ошибка SSH-доступа или отсутствие прав чтения/записи через `sudo -n rsync`.

## 6. Применение миграций и запуск стека

*(Шаги `6.1`, `6.2` и `6.2.1` предыдущей редакции исключены: подготовка каталогов и тома `pgdata` выполняется на шаге `2.7`, проверка конфигурации — на `4.3.2`, а оркестрация сервисов БД, кэша, миграций, статики, TLS и приложения делегирована в `scripts/deploy.sh`)*

### 6.1. Применение миграций и запуск стека (`deploy.sh`)

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"
ENABLE_WORKER="⚠️**<application.enable_worker>**"

for v in TARGET_DIR MIGRATION_MODE APP_ENV APP_IMAGE_TAG ENABLE_WORKER; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$MIGRATION_MODE" in
    initial|update) ;;
    *) echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2; exit 25 ;;
esac

case "$ENABLE_WORKER" in
    0|1) ;;
    *) echo "STOP: ENABLE_WORKER='$ENABLE_WORKER', ожидается '0' или '1'" >&2; exit 25 ;;
esac

[[ "$TARGET_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR должен быть абсолютным путём: '$TARGET_DIR'" >&2; exit 26; }

cd "$TARGET_DIR"

# Очистка shell-переменных БД/Compose перед вызовом deploy.sh (ADR-011).
# CANONICAL_HOST и LE_EMAIL читаются скриптом из окружения / .env.<APP_ENV>.
clean_env_cmd=(
    env
    -u DB_NAME -u DB_USER -u DB_PASSWORD -u DB_HOST
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD
    -u COMPOSE_ENV_FILES -u COMPOSE_FILE
)

# Защита от смены мажора PostgreSQL при update до остановки живой СУБД.
if [[ "$MIGRATION_MODE" == "update" ]]; then
    PG_CID="$("${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
        ./scripts/cc.sh ps -q postgres | head -n 1)"
    if [[ -n "$PG_CID" ]]; then
        CUR_PG_IMG="$(docker inspect --format '{{.Config.Image}}' "$PG_CID")"
        CUR_PG_VER="$(docker run --rm --entrypoint postgres "$CUR_PG_IMG" --version \
            | tr -d '\r' | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
        TGT_PG_IMG="$("${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
            ./scripts/cc.sh config --images | grep -E '(^|/)postgres(:|$)' | head -n 1)"
        [[ -n "$TGT_PG_IMG" ]] \
            || { echo "STOP: не удалось определить целевой образ postgres из compose" >&2; exit 1; }
        TGT_PG_VER="$(docker run --rm --entrypoint postgres "$TGT_PG_IMG" --version \
            | tr -d '\r' | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
        [[ "$CUR_PG_VER" == "$TGT_PG_VER" ]] \
            || { echo "STOP: при mode=update смена мажора PostgreSQL ($CUR_PG_VER -> $TGT_PG_VER) запрещена" >&2; exit 1; }
    fi
fi

NGINX_WAS_RUNNING=0
HOST_NGINX_HASH=""
if [[ -f nginx/nginx.conf ]] && "${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
    ./scripts/cc.sh ps --status running --services | grep -qx nginx; then
    NGINX_WAS_RUNNING=1
    HOST_NGINX_HASH="$(sha256sum nginx/nginx.conf | awk '{print $1}')"
fi

"${clean_env_cmd[@]}" \
    APP_ENV="$APP_ENV" \
    APP_IMAGE_TAG="$APP_IMAGE_TAG" \
    ENABLE_WORKER="$ENABLE_WORKER" \
    ./scripts/deploy.sh

# ADR-010: если nginx уже работал и nginx/nginx.conf сменил inode, пересоздаём контейнер,
# чтобы смонтировать актуальный файл (nginx -s reload перечитывает старый inode).
if [[ "$NGINX_WAS_RUNNING" -eq 1 && -n "$HOST_NGINX_HASH" ]]; then
    CTR_NGINX_HASH="$("${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
        ./scripts/cc.sh exec -T nginx sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
    if [[ "$HOST_NGINX_HASH" != "$CTR_NGINX_HASH" ]]; then
        "${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
            ./scripts/cc.sh run --rm --no-deps --entrypoint nginx nginx -t
        "${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
            ./scripts/cc.sh up -d --no-deps --force-recreate nginx

        for _ in $(seq 1 60); do
            NGINX_CID="$("${clean_env_cmd[@]}" APP_ENV="$APP_ENV" APP_IMAGE_TAG="$APP_IMAGE_TAG" \
                ./scripts/cc.sh ps -q nginx | head -n 1)"
            if [[ -n "$NGINX_CID" ]] && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$NGINX_CID" 2>/dev/null || true)" == "healthy" ]]; then
                break
            fi
            sleep 2
        done
    fi
fi

STEP=6.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Миграции применены и стек запущен через deploy.sh"
OUTPUT="mode=${MIGRATION_MODE}; env=${APP_ENV}; tag=${APP_IMAGE_TAG}; worker=${ENABLE_WORKER}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Выполнены `migrate-job`, `static-publish-job` и `cert-init`, запущены/обновлены `postgres`, `redis`, `web` (по схеме `start-first`), опционально `worker` (`ENABLE_WORKER=1`) и `nginx` (с выпуском LE-сертификата в `production` и пересозданием `nginx` при изменении `nginx/nginx.conf`).

**Условия остановки:** Неподставленные параметры, несовпадение мажора PostgreSQL при `update`, сбой `preflight` или `deploy.sh`, либо ошибка валидации/здоровья `nginx` при обновлении `nginx.conf`.

## 7. Проверка готовности

### 7.1. Проверка статуса сервисов, одноразовых джобов и логов стека

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
APP_ENV="⚠️**<application.app_env>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"
ENABLE_WORKER="⚠️**<application.enable_worker>**"

for v in TARGET_DIR APP_ENV APP_IMAGE_TAG ENABLE_WORKER; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$ENABLE_WORKER" in
    0|1) ;;
    *) echo "STOP: ENABLE_WORKER='$ENABLE_WORKER', ожидается '0' или '1'" >&2; exit 25 ;;
esac

[[ "$TARGET_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR должен быть абсолютным путём: '$TARGET_DIR'" >&2; exit 26; }

cd "$TARGET_DIR"

cc_cmd=(
    env
    -u DB_NAME -u DB_USER -u DB_PASSWORD -u DB_HOST
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD
    -u COMPOSE_ENV_FILES -u COMPOSE_FILE
    ./scripts/cc.sh
)

"${cc_cmd[@]}" ps -a

for svc in postgres redis web nginx; do
    cid="$("${cc_cmd[@]}" ps -q "$svc" | head -n 1)"
    [[ -n "$cid" ]] || { echo "STOP: отсутствует контейнер сервиса '$svc'" >&2; exit 1; }
    running="$(docker inspect --format '{{.State.Running}}' "$cid")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    [[ "$running" == "true" && "$health" == "healthy" ]] \
        || { echo "STOP: сервис '$svc' не готов (running=$running, health=$health)" >&2; exit 1; }
done

if [[ "$ENABLE_WORKER" == "1" ]]; then
    cid="$("${cc_cmd[@]}" ps -q worker | head -n 1)"
    [[ -n "$cid" ]] || { echo "STOP: отсутствует контейнер сервиса 'worker' при ENABLE_WORKER=1" >&2; exit 1; }
    running="$(docker inspect --format '{{.State.Running}}' "$cid")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    [[ "$running" == "true" && "$health" == "healthy" ]] \
        || { echo "STOP: сервис 'worker' не готов (running=$running, health=$health)" >&2; exit 1; }
    worker_state="healthy"
else
    worker_state="disabled"
fi

for job in migrate-job static-publish-job cert-init; do
    cid="$("${cc_cmd[@]}" ps -a -q "$job" | head -n 1)"
    [[ -n "$cid" ]] || { echo "STOP: не найден контейнер одноразового джоба '$job'" >&2; exit 1; }
    status="$(docker inspect --format '{{.State.Status}}' "$cid")"
    exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$cid")"
    [[ "$status" == "exited" && "$exit_code" == "0" ]] \
        || { echo "STOP: джоб '$job' завершился неуспешно (status=$status, exit_code=$exit_code)" >&2; exit 1; }
done

LOG_SERVICES=(migrate-job static-publish-job cert-init web nginx)
if [[ "$ENABLE_WORKER" == "1" ]]; then
    LOG_SERVICES+=(worker)
fi

"${cc_cmd[@]}" logs --no-color --tail=25 "${LOG_SERVICES[@]}"

STEP=7.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Статус сервисов, одноразовых джобов и логи проверены"
OUTPUT="env=${APP_ENV}; tag=${APP_IMAGE_TAG}; worker=${worker_state}; jobs=ok"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Сервисы `postgres`, `redis`, `web`, `nginx` (и `worker` при `ENABLE_WORKER=1`) находятся в статусе `running` и `healthy`; одноразовые контейнеры `migrate-job`, `static-publish-job` и `cert-init` завершились с кодом `0`; выведены хвостовые логи ключевых сервисов.

**Условия остановки:** Неподставленные параметры, отсутствие контейнера, статус отличного от `healthy` у долгоживущего сервиса или ненулевой код выхода / отсутствие одноразового джоба.

### 7.2. Проверка внутреннего `/healthz/` и smoke-теста периметра Nginx/TLS

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
APP_ENV="⚠️**<application.app_env>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"

for v in TARGET_DIR APP_ENV APP_IMAGE_TAG; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$TARGET_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR должен быть абсолютным путём: '$TARGET_DIR'" >&2; exit 26; }

cd "$TARGET_DIR"

ENV_FILE=".env.${APP_ENV}"
[[ -f "$ENV_FILE" ]] \
    || { echo "STOP: файл окружения '$ENV_FILE' не найден" >&2; exit 1; }

CANONICAL_HOST="$(
    python3 - "$ENV_FILE" <<'PY'
import re, sys
from pathlib import Path

kv_re = re.compile(r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
val = ""
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    m = kv_re.match(s)
    if m and m.group(1) == "CANONICAL_HOST":
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        val = v
sys.stdout.write(val)
PY
)"
: "${CANONICAL_HOST:=uralsfish.ru}"

cc_cmd=(
    env
    -u DB_NAME -u DB_USER -u DB_PASSWORD -u DB_HOST
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD
    -u COMPOSE_ENV_FILES -u COMPOSE_FILE
    ./scripts/cc.sh
)

# 1. Внутренняя проверка /healthz/ внутри контейнера web (без редиректов и внешнего прокси)
"${cc_cmd[@]}" exec -T web python - "[http://127.0.0.1:8000/healthz/](http://127.0.0.1:8000/healthz/)" "$CANONICAL_HOST" <<'PY'
import sys
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

url, host = sys.argv[1:]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
request = urllib.request.Request(url, headers={"Host": host})
try:
    with opener.open(request, timeout=5) as response:
        status = response.status
except urllib.error.HTTPError as exc:
    status = exc.code
    exc.close()
except (urllib.error.URLError, OSError, ValueError) as exc:
    print(f"STOP 7.2: транспортная ошибка /healthz/: {exc}", file=sys.stderr)
    sys.exit(70)

if status != 200:
    print(f"STOP 7.2: ожидался HTTP 200 на /healthz/, получено {status}", file=sys.stderr)
    sys.exit(71)
PY

# 2. Внешний smoke-тест периметра Nginx/TLS через SNI (--resolve на loopback)
(
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy

code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/healthz/")"
[[ "$code" == "404" ]] \
    || { echo "STOP 7.2: внешний /healthz/ вернул $code (ожидалось 404)" >&2; exit 71; }

code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/exchange/")"
[[ "$code" == "404" ]] \
    || { echo "STOP 7.2: внешний /exchange/ вернул $code (ожидалось 404)" >&2; exit 71; }

code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/admin/")"
[[ "$code" == "401" ]] \
    || { echo "STOP 7.2: /admin/ вернул $code (ожидалось 401 Basic Auth)" >&2; exit 71; }

code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/")"
[[ "$code" =~ ^(200|301|302)$ ]] \
    || { echo "STOP 7.2: корневой / вернул $code (ожидалось 200/301/302)" >&2; exit 71; }
)

STEP=7.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Внутренний /healthz/ и периметр Nginx/TLS проверены"
OUTPUT="host=${CANONICAL_HOST}; healthz=200(in)/404(out); exchange=404; admin=401"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Внутри контейнера `web` эндпоинт `/healthz/` возвращает `200`; снаружи через `nginx` по `https://<CANONICAL_HOST>` с SNI закрыты `/healthz/` (`404`) и `/exchange/` (`404`), `/admin/` требует Basic Auth (`401`), а `/` отвечает `200`, `301` или `302`.

**Условия остановки:** Неподставленные параметры, отсутствие `.env.<APP_ENV>`, транспортная ошибка или код отличного от `200` внутри `web` по `/healthz/`, либо несоответствие ожидаемым HTTP-кодам на периметре `nginx`.

### 7.3. Ввод в эксплуатацию `worker`, проверка `cron` и фиксация тега релиза

**Место выполнения:** целевой сервер, Bash.

*(Выполняется после успешного прохождения шагов `7.1` и `7.2`. При `migration.mode = initial` проверьте/настройте регламентные задачи в `cron` на хосте: `./scripts/backup_db.sh`, `./scripts/update_cf_ips.sh` (по `ADR-010`) и продление сертификатов `certbot` + `./scripts/cc.sh reload-nginx` (из `docker-compose.yml`))*

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"
ENABLE_WORKER="⚠️**<application.enable_worker>**"

for v in TARGET_DIR MIGRATION_MODE APP_ENV APP_IMAGE_TAG ENABLE_WORKER; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$MIGRATION_MODE" in
    initial|update) ;;
    *) echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'initial' или 'update'" >&2; exit 25 ;;
esac

case "$ENABLE_WORKER" in
    0|1) ;;
    *) echo "STOP: ENABLE_WORKER='$ENABLE_WORKER', ожидается '0' или '1'" >&2; exit 25 ;;
esac

[[ "$TARGET_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR должен быть абсолютным путём: '$TARGET_DIR'" >&2; exit 26; }

cd "$TARGET_DIR"

cc_cmd=(
    env
    -u DB_NAME -u DB_USER -u DB_PASSWORD -u DB_HOST
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD
    -u COMPOSE_ENV_FILES -u COMPOSE_FILE
    ./scripts/cc.sh
)

if [[ "$ENABLE_WORKER" == "1" ]]; then
    cid="$("${cc_cmd[@]}" ps -q worker | head -n 1)"
    [[ -n "$cid" ]] || { echo "STOP 7.3: контейнер 'worker' не найден при ENABLE_WORKER=1" >&2; exit 1; }
    running="$(docker inspect --format '{{.State.Running}}' "$cid")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    [[ "$running" == "true" && "$health" == "healthy" ]] \
        || { echo "STOP 7.3: 'worker' не готов (running=$running, health=$health)" >&2; exit 1; }
    "${cc_cmd[@]}" logs --no-color --tail=15 worker
    worker_status="active(healthy)"
else
    worker_status="disabled"
fi

for job_script in scripts/backup_db.sh scripts/update_cf_ips.sh; do
    if [[ ! -f "$job_script" ]]; then
        if [[ "$MIGRATION_MODE" == "initial" ]]; then
            echo "WARN 7.3: скрипт регламентной задачи '$job_script' отсутствует в репозитории (проверьте перед настройкой cron)" >&2
        fi
    fi
done

echo "=== Текущий crontab ($(id -un)) ==="
crontab -l 2>/dev/null || echo "(crontab пуст)"

if [[ "$MIGRATION_MODE" == "initial" ]]; then
    echo "Рекомендуемые регламентные задачи на хосте (ADR-009, ADR-010, docker-compose.yml):"
    echo "  - Бэкап БД: ${TARGET_DIR}/scripts/backup_db.sh"
    echo "  - Обновление IP Cloudflare: ${TARGET_DIR}/scripts/update_cf_ips.sh"
    echo "  - Продление TLS: cd ${TARGET_DIR} && ./scripts/cc.sh --profile tls run --rm certbot renew --quiet && ./scripts/cc.sh reload-nginx"
fi

STEP=7.3
DATE_UTC="$(date -u +%FT%T)"
NOTE="Релиз введён в эксплуатацию, тег зафиксирован как точка отката"
OUTPUT="mode=${MIGRATION_MODE}; env=${APP_ENV}; tag=${APP_IMAGE_TAG}; worker=${worker_status}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Состояние `worker` проверено согласно `ENABLE_WORKER`; выведен текущий `crontab` (при `initial` — памятка по регламентным задачам); в журнале зафиксирован активный `APP_IMAGE_TAG` для последующих обновлений и откатов.

**Условия остановки:** Неподставленные параметры или неготовый/отсутствующий контейнер `worker` при `ENABLE_WORKER=1`.

## 8. Подтверждение или отказ релиза

*(Раздел применяется только при `migration.mode = update` после проверок Раздела 7. При `migration.mode = initial` процедура отката не применяется: при обнаружении проблемы устраняется её причина и повторно выполняется соответствующий шаг развёртывания.)*

### 8.1. Подтверждение релиза

**Место выполнения:** целевой сервер, Bash.

*(Выполняется, если проверки Раздела 7 пройдены успешно и решено закрепить новый релиз `APP_IMAGE_TAG` в эксплуатации.)*

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
APP_ENV="⚠️**<application.app_env>**"
APP_IMAGE_TAG="⚠️**<images.app_tag>**"

for v in TARGET_DIR APP_ENV APP_IMAGE_TAG; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

[[ "$TARGET_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR должен быть абсолютным путём: '$TARGET_DIR'" >&2; exit 26; }

cd "$TARGET_DIR"

STEP=8.1
DATE_UTC="$(date -u +%FT%T)"
NOTE="Релиз подтверждён и закреплён в эксплуатации"
OUTPUT="decision=confirmed; env=${APP_ENV}; tag=${APP_IMAGE_TAG}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** В журнале зафиксировано подтверждение релиза `APP_IMAGE_TAG`; возврат к предыдущей версии не требуется.

**Условия остановки:** Неподставленные параметры.

---

### 8.2. Отказ от релиза: остановка новой версии и возврат на `PREV_IMAGE_TAG`

**Место выполнения:** целевой сервер, Bash.

*(Выполняется только при `migration.mode = update`, если принято решение отклонить новый релиз. Схема БД (Expand/Contract), тома данных и хешированная статика в `static_volume` сохраняются; контейнеры `web` и `worker` (если включён) переключаются на `PREV_IMAGE_TAG` из `$ROLLBACK_DIR/prev_release.env`.)*

```bash
(
set -Eeuo pipefail

TARGET_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<target.rollback_dir>**"
MIGRATION_MODE="⚠️**<migration.mode>**"
APP_ENV="⚠️**<application.app_env>**"
ENABLE_WORKER="⚠️**<application.enable_worker>**"

for v in TARGET_DIR ROLLBACK_DIR MIGRATION_MODE APP_ENV ENABLE_WORKER; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 26; }
done

case "$MIGRATION_MODE" in
    update) ;;
    *) echo "STOP: шаг 8.2 выполняется только при MIGRATION_MODE='update' (получено '$MIGRATION_MODE')" >&2; exit 25 ;;
esac

case "$ENABLE_WORKER" in
    0|1) ;;
    *) echo "STOP: ENABLE_WORKER='$ENABLE_WORKER', ожидается '0' или '1'" >&2; exit 25 ;;
esac

[[ "$TARGET_DIR" == /* && "$ROLLBACK_DIR" == /* ]] \
    || { echo "STOP: TARGET_DIR и ROLLBACK_DIR должны быть абсолютными путями" >&2; exit 26; }

PREV_RELEASE_FILE="${ROLLBACK_DIR}/prev_release.env"
[[ -f "$PREV_RELEASE_FILE" ]] \
    || { echo "STOP: не найден файл предыдущего релиза '$PREV_RELEASE_FILE'" >&2; exit 1; }

PREV_IMAGE_TAG="$(
    python3 - "$PREV_RELEASE_FILE" <<'PY'
import re, sys
from pathlib import Path

kv_re = re.compile(r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
val = ""
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    m = kv_re.match(s)
    if m and m.group(1) == "PREV_IMAGE_TAG":
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        val = v
sys.stdout.write(val)
PY
)"

[[ -n "$PREV_IMAGE_TAG" ]] \
    || { echo "STOP: PREV_IMAGE_TAG не задан или пуст в '$PREV_RELEASE_FILE'" >&2; exit 1; }

cd "$TARGET_DIR"

cc_cmd=(
    env
    -u DB_NAME -u DB_USER -u DB_PASSWORD -u DB_HOST
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD
    -u COMPOSE_ENV_FILES -u COMPOSE_FILE
    ./scripts/cc.sh
)

# 1. Остановка и удаление контейнеров отклонённой версии
STOP_SERVICES=(web)
if [[ "$ENABLE_WORKER" == "1" ]]; then
    STOP_SERVICES+=(worker)
fi
APP_ENV="$APP_ENV" APP_IMAGE_TAG="$PREV_IMAGE_TAG" "${cc_cmd[@]}" stop "${STOP_SERVICES[@]}" || true
APP_ENV="$APP_ENV" APP_IMAGE_TAG="$PREV_IMAGE_TAG" "${cc_cmd[@]}" rm -f "${STOP_SERVICES[@]}" || true

# 2. Запуск предыдущей версии (PREV_IMAGE_TAG) и перечитывание апстримов в nginx
APP_ENV="$APP_ENV" APP_IMAGE_TAG="$PREV_IMAGE_TAG" "${cc_cmd[@]}" up -d --no-deps "${STOP_SERVICES[@]}"
APP_ENV="$APP_ENV" APP_IMAGE_TAG="$PREV_IMAGE_TAG" "${cc_cmd[@]}" reload-nginx

for svc in "${STOP_SERVICES[@]}"; do
    ready=0
    for _ in $(seq 1 60); do
        cid="$(APP_ENV="$APP_ENV" APP_IMAGE_TAG="$PREV_IMAGE_TAG" "${cc_cmd[@]}" ps -q "$svc" | head -n 1)"
        if [[ -n "$cid" ]]; then
            running="$(docker inspect --format '{{.State.Running}}' "$cid")"
            health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
            if [[ "$running" == "true" && "$health" == "healthy" ]]; then
                ready=1
                break
            fi
        fi
        sleep 2
    done
    [[ "$ready" -eq 1 ]] \
        || { echo "STOP 8.2: сервис '$svc' на теге '$PREV_IMAGE_TAG' не перешёл в healthy" >&2; exit 1; }
done

STEP=8.2
DATE_UTC="$(date -u +%FT%T)"
NOTE="Релиз отклонён; выполнен возврат на предыдущий тег образа"
OUTPUT="decision=rejected; env=${APP_ENV}; restored_tag=${PREV_IMAGE_TAG}; worker=${ENABLE_WORKER}"
printf '%s | %s | %s | %s\n' "$STEP" "$DATE_UTC" "$OUTPUT" "$NOTE"
)
```

**Ожидаемый результат:** Контейнеры отклонённой версии остановлены; сервисы `web` (и `worker` при `ENABLE_WORKER=1`) запущены на теге `PREV_IMAGE_TAG` и перешли в статус `healthy`; конфигурация `nginx` перечитана без перезапуска контейнера; при необходимости повторите проверки шагов `7.1` и `7.2`.

**Условия остановки:** Неподставленные параметры, запуск при `MIGRATION_MODE != update`, отсутствие файла `prev_release.env` или пустой `PREV_IMAGE_TAG`, либо непереход `web`/`worker` на старом теге в статус `healthy`.