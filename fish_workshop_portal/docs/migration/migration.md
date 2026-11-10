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

### Журнал оператора. 

- Ручные записи о ходе миграции, не привязанные к автоматическим шагам, ведутся в файле migration-operator.log на машине оператора. 
- Файл создаётся до шага 2.1, ведётся сквозным образом до завершения миграции или отката, на исходный и целевой серверы не передаётся и артефактом отката не является. 
- Формат строки: <Шаг>\<Время>\<Сервер>\<Запись>. 
- Журнал оператора не заменяет `journal.path` на целевом сервере и не дублирует его.

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
cd ⚠️**<source.project_dir>**
ls -la docker-compose.yml
docker compose config --images
```

**Ожидаемый результат:** Выведен атрибут файла `docker-compose.yml` и список используемых образов. Директория существует и содержит валидную конфигурацию.

**КРИТИЧНО:** Для каждого сервиса с `build:` в `docker-compose.yml` должен быть явно задан стабильный `image:`, либо в самом файле должен быть зафиксирован верхнеуровневый `name:`. Использование автоматически сгенерированных Compose-имён образов недопустимо: при несовпадении имён директорий на исходном и целевом серверах шаг 4.4.В завершится ошибкой (exit 27), так как целевой сервер будет ожидать другие имена образов.

### 2.6. Проверка базового ПО целевого сервера

**Место выполнения:** целевой сервер, Bash.

```bash
docker --version
docker compose version
```

**Ожидаемый результат:** Установлен Docker и плагин docker-compose. Выведены их версии.

**Дополнительно (только при `migration.config.yaml: migration.mode` — `update`):** проверить наличие текущей конфигурации и зафиксировать тег образа СУБД целевого сервера до обновления (проверка `pg_dump`-совместимости для отката выполняется в 3.2.3/8.3). При `mode = initial` блок пропускается (конфигурация ещё не доставлена).

```bash
(
test -f ⚠️**<target.project_dir>**/docker-compose.yml || { echo "STOP: нет docker-compose.yml при mode=update" >&2; exit 1; }
cd ⚠️**<target.project_dir>**
docker compose config --images | grep -i postgres
)
```

### 2.7. Подготовка целевой директории

**Место выполнения:** целевой сервер, Bash.

```bash
mkdir -p ⚠️**<target.project_dir>**
mkdir -p ⚠️**<journal.rollback_dir>** "$(dirname -- ⚠️**<journal.path>**)"
cd ⚠️**<target.project_dir>**
pwd
```

**Ожидаемый результат:** Директории проекта, отката и каталога журнала созданы (или существуют), осуществлен переход в целевую директорию, вывод `pwd` совпадает с `target.project_dir`.

### 2.8. Обнаружение активных источников записи (writers)

**Место выполнения:** исходный сервер, Bash.

```bash
cd ⚠️**<source.project_dir>**
docker compose ps
# Пользовательский crontab и crontab root; диагностику не скрывать.
crontab -l || printf '%s\n' 'Проверьте диагностику выше: допустимо только «no crontab for ...».' >&2
sudo -u root crontab -l || printf '%s\n' 'Проверьте диагностику выше: допустимо только «no crontab for ...».' >&2
sudo cat /etc/crontab
sudo sh -c '
    for f in /etc/cron.d/*; do
        [ -f "$f" ] || continue
        printf "\n--- %s ---\n" "$f"
        cat "$f" || exit 1
    done
'
systemctl list-timers --all --no-pager

# Активные соединения к СУБД — это и есть фактические writers
docker compose exec -T ⚠️**<database.service>** sh -c 'psql \
    -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" \
    -c "select usename, client_addr, state, backend_type from pg_stat_activity \
        where pid <> pg_backend_pid() order by state, usename"'

# Долгие транзакции: снимок при них возможен, но WAL-хвост нельзя усечь
docker compose exec -T ⚠️**<database.service>** sh -c 'psql \
    -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" \
    -c "select pid, state, now()-xact_start as age, left(query,60) \
        from pg_stat_activity where xact_start is not null and pid <> pg_backend_pid() \
        order by age desc limit 10"'
```

**Ожидаемый результат**: Выведены запущенные контейнеры, cron-задачи, systemd-таймеры и список соединений к СУБД. На этом этапе ничего не останавливается.

**Проверка cron:** `no crontab for ...` означает отсутствие crontab соответствующего пользователя и допустимо. Любая другая ошибка, включая ошибку `sudo` или чтения системных файлов, означает незавершённую проверку: устранить причину до перехода дальше. Отсутствие файлов в `/etc/cron.d/` допустимо. Просмотреть выведенные команды и вызываемые ими скрипты; учитывать только задачи проекта.

**Фиксация результата (обязательно)**: По окончании операции выполняется запись в журнал оператора (§1, «Журнал оператора») формата:
```text
2.8\<Время>\source\обнаружено: <N>
````
Далее — по одной строке на каждого писателя: 
```text
<тип>: <идентификатор> (<источник обнаружения>); остановлен: нет
```
тип — container | cron | systemd-timer | external-db-client;
идентификатор — имя сервиса Compose, команда cron, имя unit, client_addr;
источник обнаружения — docker compose ps | crontab -l | sudo -u root crontab -l | /etc/crontab | /etc/cron.d/<имя файла> | systemctl list-timers | pg_stat_activity.client_addr;
остановлен — изначально нет.

Без итоговой записи 2.8 source шаг 2.8 не считается выполненным, и переход к шагу 5.1 запрещён.

Связь с другими шагами: записи 2.8 source — входной чек-лист для шага 5.1 (остановка writers исходного сервера). На этом шаге по каждому писателю вносится запись `<тип>: <идентификатор> (<источник обнаружения>); остановлен: да`, либо обоснование, почему он неактивен. 

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

#### 2.10.1. Проверка sudo для rsync на исходном сервере

**Место выполнения:** целевой сервер, Bash, пользователь `target.ssh.user`.

Выполняется, если хотя бы у одного элемента `storage.items` задано `transfer = true`.
Проверка использует SSH без TTY, как в 5.3.2. Флаг `-k` исключает использование
кэшированной аутентификации sudo: проверяется запуск `rsync` без ввода пароля.

```bash
(
set -Eeuo pipefail
ssh -T -p ⚠️**<source.ssh.port>** -o BatchMode=yes -o ConnectTimeout=5 \
  ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>** \
  'sudo -k -n rsync --version'
echo "SOURCE_RSYNC_SUDO_OK"
)
```

**Ожидаемый результат:** версия `rsync` и `SOURCE_RSYNC_SUDO_OK`.
Для `source.ssh.user` политика sudo на исходном сервере должна разрешать
запуск `rsync` от root без пароля, включая аргументы `--server --sender`,
которые rsync формирует при скачивании. Проверка `--version` подтверждает запуск,
но не проверяет разрешение всех аргументов при ограничениях в sudoers.

**Условия остановки:** ненулевой код завершения SSH/sudo/rsync или отсутствие
`SOURCE_RSYNC_SUDO_OK`. До устранения причины к переносу не переходить.
Проверка `sudo -n true` на целевом сервере это предусловие не покрывает.

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
-U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" \
-tAc "select pg_size_pretty(pg_database_size(current_database())), \
            pg_database_size(current_database())"'
df -Ph            
``` 
 
Целевой сервер: 
 
```bash
df -Ph "$(docker info --format '{{.DockerRootDir}}')" \
  ⚠️**<target.project_dir>** \
  ⚠️**<journal.rollback_dir>**
du -sh ⚠️**<target.project_dir>**  
``` 
 
**Ожидаемый результат:** свободное место на ФС исходного сервера — достаточно для размещения дампа БД и архива образов (при 4.4.В); свободное место на ФС `DockerRootDir` — не менее 3× размера БД; свободное место на ФС `journal.rollback_dir` — не менее суммы 1× размера БД и 2× размера каталога проекта.
 
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

#### 3.0.1. Остановка внешних источников записи на уровне ОС

Выявите и остановите на целевом сервере все хостовые задачи (`cron`, `systemd`-таймеры, внешние воркеры), взаимодействующие с проектом или его БД, зафиксировав их список для последующего включения на шаге 7.3 / 8.4:

```bash
# Пользовательский crontab и crontab root; диагностику не скрывать.
crontab -l || printf '%s\n' 'Проверьте диагностику выше: допустимо только «no crontab for ...».' >&2
sudo -u root crontab -l || printf '%s\n' 'Проверьте диагностику выше: допустимо только «no crontab for ...».' >&2
sudo cat /etc/crontab
sudo sh -c '
    for f in /etc/cron.d/*; do
        [ -f "$f" ] || continue
        printf "\n--- %s ---\n" "$f"
        cat "$f" || exit 1
    done
'
systemctl list-timers --all --no-pager

# Остановить выявленные таймеры/сервисы проекта на уровне ОС (при наличии):
# sudo systemctl stop <project_timer_or_service>
# Для cron — закомментировать только проектные задачи в месте их обнаружения:
# crontab -e — текущий пользователь; sudo -u root crontab -e — root;
# sudoedit /etc/crontab или sudoedit /etc/cron.d/<имя файла> — системные задачи.
# Зафиксировать источник и отключённые строки для включения на шаге 7.3 / 8.4.
```

**Проверка cron:** `no crontab for ...` означает отсутствие crontab соответствующего пользователя и допустимо. Любая другая ошибка, включая ошибку `sudo` или чтения системных файлов, означает незавершённую проверку: устранить причину до перехода дальше. Отсутствие файлов в `/etc/cron.d/` допустимо. Просмотреть выведенные команды и вызываемые ими скрипты; учитывать только задачи проекта.

**Ожидаемый результат:** Хостовые планировщики и внешние скрипты целевого сервера не инициируют новых обращений к контейнерам и БД.

#### 3.0.2. Остановка всех контейнеров перед файловым бэкапом

Перед продолжением остановить внешние клиенты целевой БД, включая запущенные с других хостов, либо заблокировать их доступ. Хостовые задачи из 3.0.1 и внешние клиенты должны оставаться отключёнными до разрешённого включения на шаге 7.3 / 8.4. Однократный сброс соединений не запрещает повторное подключение.

```bash
(
cd ⚠️**<target.project_dir>** || exit 1
docker compose stop || { echo "STOP: не удалось остановить контейнеры проекта" >&2; exit 1; }

# Не запускать СУБД до завершения файлового бэкапа и сверки в 3.1.
# Только СУБД будет запущена в 3.2.2 для снятия дампа.
)
```

**Ожидаемый результат:** Все контейнеры проекта, включая СУБД, остановлены. При ошибке остановки переход к 3.1 запрещён.

### 3.1. Создание локальной резервной копии (точка отката)

**Место выполнения:** целевой сервер, Bash.

Предусловия: выполнены шаги 2.9–2.13 (обратный SSH, привилегии, место, тулчейн). Каталог `journal.rollback_dir` существует, находится вне `<target.project_dir>` и доступен на запись. `journal.path` — абсолютный путь журнала, общий для всех шагов файла.

**Дополнительное предусловие для `update`:** выполнен 3.0.2; все контейнеры проекта, включая СУБД, остаются остановленными до завершения копирования и сверки в 3.1. Никакие внешние процессы не должны изменять `target.project_dir` в этот период. Это относится и к PGDATA, если он размещён внутри каталога проекта через bind-mount.

**Роль артефакта**: файловая точка отката (files_backup_*). Откат файлов проекта выполняется в 8.2. Точка отката БД (дамп) создаётся отдельно в 3.2. Артефакты 3.1 и 3.2 регистрируются в журнале независимо: 8.2 ищет файловую запись 3.1 ok, 8.3 — запись 3.2.3 ok.

Применимость по режиму: при migration.config: migration.mode = initial файловый бэкап не создаётся (откатывать нечего) — скрипт пишет в журнал 3.1 <ts> skipped mode=initial, после чего выполняется переход к 3.2.1 (для регистрации пропуска дампа БД). При update — выполняется обязательно.

#### 3.1.1. Создать файл
```bash
sudo nano /usr/local/bin/backup-project.sh
```
Запись в /usr/local/bin требует root — выполняется через sudo (проверено в 2.10). Альтернатива без root: каталог `journal.artifacts_dir`/bin/backup-project.sh, если он на отдельной ФС от восстанавливаемых данных.

#### 3.1.2. Вставить код (весь скрипт целиком)
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
trap 'rm -f -- "${DIFF_FILE:-}"' EXIT
trap 'rc=$?; rm -f -- "${DIFF_FILE:-}"; echo "FAIL 3.1 rc=$rc line=$LINENO" >&2' ERR

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


require_value TARGET_DIR     "$TARGET_DIR"     path || exit 26
require_value ROLLBACK_DIR   "$ROLLBACK_DIR"   path || exit 26
require_value JOURNAL        "$JOURNAL"        path || exit 26
require_value MIGRATION_MODE "$MIGRATION_MODE" plain || exit 26

TARGET_DIR="${TARGET_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"

# ============================================================================
# Guard: артефакты и журнал не внутри цели (до любых записей на ФС)
# ============================================================================
[[ "$TARGET_DIR" != "$ROLLBACK_DIR" ]] \
    || { echo "STOP: target_dir и rollback_dir совпадают: $TARGET_DIR" >&2; exit 23; }

case "$ROLLBACK_DIR/" in
    "$TARGET_DIR"/*) echo "STOP: rollback_dir внутри target_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac
case "$TARGET_DIR/" in
    "$ROLLBACK_DIR"/*) echo "STOP: target_dir внутри rollback_dir: $TARGET_DIR" >&2; exit 23 ;;
esac
case "$JOURNAL" in
    "$TARGET_DIR"|"$TARGET_DIR"/*) echo "STOP: journal.path внутри target_dir: $JOURNAL" >&2; exit 23 ;;
esac

# ============================================================================
# Каталог журнала нужен обеим веткам (initial и update) до первого jlog
# ============================================================================
JOURNAL_DIR="$(dirname -- "$JOURNAL")"
mkdir -p -- "$JOURNAL_DIR" \
    || { echo "STOP: не создан каталог журнала: $JOURNAL_DIR" >&2; exit 24; }

touch -- "$JOURNAL"
chown "${SUDO_USER:-root}:" "$JOURNAL_DIR" "$JOURNAL" "$ROLLBACK_DIR" 2>/dev/null || true    

jlog() { printf '%s\t%s\t%s\t%b\n' "$1" "$(date -u +%FT%TZ)" "$2" "$3" >> "$JOURNAL"; }

# ============================================================================
# 1. Гейт по режиму (единый источник истины — migration.mode, не наличие файлов)
# ============================================================================
case "$MIGRATION_MODE" in

update) : ;;
initial) 
    jlog "3.1" "skipped" "mode=initial"
    echo "3.1: mode=initial — точка отката по файлам не создаётся. Переход к 3.2.1."
    exit 0 ;;
*)
   echo "STOP: MIGRATION_MODE='$MIGRATION_MODE', ожидается 'update' или 'initial'" >&2
   exit 25 
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
rsync -aHAXnc --numeric-ids -n -i \
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

FILES_COUNT="$(wc -l < "$BACKUP_DIR.manifest.sha256" | awk '{print $1}')"

# ============================================================================
# 5. Регистрация точки отката в журнале (единственный источник для 8.2)
# ============================================================================
RUN_ID="${TS}_$$"
echo "RUN_ID=\"${RUN_ID}\"" > "${ROLLBACK_DIR}/rollback_point.env"
jlog "3.1" "ok" "run_id=${RUN_ID}\tbackup=${BACKUP_DIR}\tfiles=${FILES_COUNT}\tsrc_kb=${SRC_KB}"
chown "${SUDO_USER:-root}:" "${ROLLBACK_DIR}/rollback_point.env" "$BACKUP_DIR.manifest.sha256" "$JOURNAL" 2>/dev/null || true

echo "OK 3.1"
echo "  run_id : $RUN_ID"
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

*(Шаг 3.2.1 выполняется в любом режиме; шаги 3.2.2 и 3.2.3 выполняются только при `migration.mode = update`)*

**Место выполнения:** целевой сервер, Bash.

**Предусловия:**
- Шаг 3.2.1 обязателен для всех режимов. При `migration.mode = initial` шаги 3.2.2 и 3.2.3 не выполняются (после 3.2.1 осуществляется переход к §4).
- Каталог `journal.rollback_dir` существует, находится вне `target.project_dir` и доступен на запись.
- Утилита `sha256sum` установлена.

#### 3.2.1 Проверка предусловия (не пропускать)

Каталог отката не должен лежать внутри каталога проекта — иначе шаг 8.2 (`rsync --delete`) уничтожит дамп до того, как 8.3 его прочитает.

```bash
(
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
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
[[ -n "$MIGRATION_MODE" && "$MIGRATION_MODE" != *'⚠️'* && "$MIGRATION_MODE" != *'<'* && "$MIGRATION_MODE" != *'>'* && "$MIGRATION_MODE" != *'['* && "$MIGRATION_MODE" != *']'* && "$MIGRATION_MODE" != *'**'* ]] \
    || { echo "STOP: MIGRATION_MODE не подставлена: '$MIGRATION_MODE'" >&2; exit 22; }

# ── 2. нормализация и guard (до записи в JOURNAL/ROLLBACK_DIR) ──
TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"

case "$ROLLBACK_DIR/" in
    "$TARGET_PROJECT_DIR"/*|"$TARGET_PROJECT_DIR"/)
        echo "STOP: rollback_dir внутри project_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac

case "$JOURNAL" in
    "$TARGET_PROJECT_DIR"|"$TARGET_PROJECT_DIR"/*)
        echo "STOP: journal.path внутри project_dir: $JOURNAL" >&2; exit 23 ;;
esac

# ── 3. ГЕЙТ РЕЖИМА ──
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

# ── 4. предусловия ФС ──
[[ -d "$ROLLBACK_DIR" && -w "$ROLLBACK_DIR" ]] \
    || { echo "STOP: rollback_dir недоступен на запись: $ROLLBACK_DIR" >&2; exit 24; }
[[ -f "$TARGET_PROJECT_DIR/docker-compose.yml" ]] \
    || { echo "STOP: нет docker-compose.yml в $TARGET_PROJECT_DIR" >&2; exit 25; }

cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }
)
```

#### 3.2.2 Основной шаг

```bash
(
# Коды завершения:
#   0  — дамп снят и подтверждён спутником .sha256
#  22  — плейсхолдер не подставлен
#  23  — rollback_dir внутри project_dir
#  24  — rollback_dir недоступен / нет каталога журнала
#  26  — cd в target.project_dir не выполнен
#  27  — контейнер database.service отсутствует или не running
#  28  — pg_isready: СУБД не принимает соединения
#  29  — дамп подозрительно мал (пустая/чужая БД)
#  31  — не удалось получить корректный pg_database_size текущей БД цели
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
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
for v in DB_SERVICE DB_USER DB_NAME; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
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

RUN_ID="$(awk -F'\t' '$1=="3.1" && $3=="ok" {for(i=4;i<=NF;i++) if($i~/^run_id=/) {sub(/^run_id=/,"",$i); print $i}}' "$JOURNAL" | tail -1)"
[[ -n "$RUN_ID" ]] || { echo "STOP: в журнале нет подтверждённого run_id от шага 3.1" >&2; exit 24; }

# ── предикат: состояние контейнера БД, а не наличие файлов ──
CID="$(docker compose ps -aq "$DB_SERVICE" 2>/dev/null || true)"
if [[ -z "$CID" ]]; then
    echo "STOP: контейнер $DB_SERVICE отсутствует при mode=update ($TARGET_PROJECT_DIR)" >&2
    exit 27
fi

# Файловый бэкап 3.1 завершён и сверен; внешние источники записи отключены.
# Запустить только СУБД, не контейнеры приложения.
docker compose start "$DB_SERVICE" \
    || { echo "STOP: не удалось запустить контейнер $DB_SERVICE" >&2; exit 27; }

DB_STATE="$(docker inspect -f '{{.State.Status}}' "$CID")"
if [[ "$DB_STATE" != "running" ]]; then
    echo "STOP: контейнер $DB_SERVICE в состоянии '$DB_STATE', а не running. Разберись до дампа." >&2
    exit 27
fi

for _ in $(seq 1 30); do
    docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -h 127.0.0.1 -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" -q" && break
    sleep 1
done

docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -h 127.0.0.1 -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" -q" \
    || { echo "STOP: СУБД не принимает соединения" >&2; exit 28; }

# Физический размер БД для оценки места при восстановлении (не размер дампа).
# Размер текущей БД цели, дамп которой создаётся ниже для точки отката.
# Используется в 3.2.3 только для оценки восстановления этого rollback-дампа.
DB_SIZE_BYTES="$(docker compose exec -T "$DB_SERVICE" \
     sh -c "psql -X -A -t -v ON_ERROR_STOP=1 -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" -c 'SELECT pg_database_size(current_database())'")" \
        || { echo "STOP: не удалось получить pg_database_size текущей БД цели" >&2; exit 31; }
[[ "$DB_SIZE_BYTES" =~ ^[1-9][0-9]*$ ]] \
    || { echo "STOP: некорректный pg_database_size текущей БД цели: '$DB_SIZE_BYTES'" >&2; exit 31; }

AVAIL_KB="$(df -Pk -- "$ROLLBACK_DIR" | awk 'NR==2{print $4}')"
NEED_KB=$(( (DB_SIZE_BYTES + 1023) / 1024 ))
[[ -n "${AVAIL_KB:-}" && "$AVAIL_KB" -ge "$NEED_KB" ]] \
    || { echo "STOP: на ФС rollback_dir свободно ${AVAIL_KB:-0}K, для дампа нужно ≈${NEED_KB}K" >&2; exit 24; }

# ── снимок ──
# pg_dump фиксирует MVCC-снимок на момент старта: записи живой версии после старта в дамп не попадут.
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="${ROLLBACK_DIR}/db_rollback_${TS}.dump"
PG_MAJOR="$(docker compose exec -T "$DB_SERVICE" postgres --version \
    | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"

docker compose exec -T "$DB_SERVICE" \
    sh -c "pg_dump -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" -Fc -Z 6 --no-owner --no-acl" \
    > "${DUMP}.tmp"

mv -- "${DUMP}.tmp" "$DUMP"
BYTES="$(stat -c %s "$DUMP")"
[[ "$BYTES" -gt 1000 ]] || { echo "STOP: дамп подозрительно мал ($BYTES байт)" >&2; exit 29; }

# ── спутник артефакта и файл состояния для 3.2.3 ──
sha256sum "$DUMP" > "${DUMP}.sha256"
SHA="$(cut -d' ' -f1 "${DUMP}.sha256")"

ACTUAL_DB_NAME="$(docker compose exec -T "$DB_SERVICE" sh -c "printf '%s' \"\${$DB_NAME:-\$$DB_USER}\"")"

cat <<EOF > "${ROLLBACK_DIR}/rollback_point.env"
STATUS=ok
RUN_ID="${RUN_ID}"
DUMP="${DUMP}"
DUMP_BYTES="${BYTES}"
DB_SIZE_BYTES="${DB_SIZE_BYTES}"
DUMP_SHA256="${SHA}"
DB_NAME="${ACTUAL_DB_NAME}"
PG_MAJOR="${PG_MAJOR}"
EOF

printf '3.2.2\t%s\tok\trun_id=%s\tdb=%s\tdump=%s\tsha256=%s\tbytes=%s\tpg=%s\n' \
    "$TS" "$RUN_ID" "$ACTUAL_DB_NAME" "$DUMP" "$SHA" "$BYTES" "$PG_MAJOR" >> "$JOURNAL"

echo "OK 3.2.2"
echo "  run_id : $RUN_ID"
echo "  dump   : $DUMP"
echo "  bytes  : $BYTES"
echo "  sha256 : $SHA"
echo "  pg     : $PG_MAJOR"
)
```

#### 3.2.3 Проверка результата

```bash
(
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
#  50  — отсутствует или некорректен DB_SIZE_BYTES в rollback_point.env
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
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
[[ -n "$DB_SERVICE" && "$DB_SERVICE" != *'⚠️'* && "$DB_SERVICE" != *'<'* && "$DB_SERVICE" != *'>'* && "$DB_SERVICE" != *'['* && "$DB_SERVICE" != *']'* && "$DB_SERVICE" != *'**'* ]] \
    || { echo "STOP: DB_SERVICE не подставлена: '$DB_SERVICE'" >&2; exit 22; }

TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"
RESULTS="${ROLLBACK_DIR}/rollback_point.env"

# ── 1. файл результата предыдущего шага ──
[[ -f "$RESULTS" ]] || { echo "STOP: нет $RESULTS — шаг 3.2.2 не выполнялся" >&2; exit 40; }
DB_SIZE_BYTES=""
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
AVAIL_KB="$(df -Pk "$(docker info --format '{{.DockerRootDir}}')" | awk 'NR==2{print $4}')"
# Старые метаданные без физического размера БД требуют повторения 3.2.2.
[[ "$DB_SIZE_BYTES" =~ ^[1-9][0-9]*$ ]] \
    || { echo "STOP: нет корректного DB_SIZE_BYTES в $RESULTS — повторить 3.2.2" >&2; exit 50; }
# Как в 2.12: 3× физический размер БД, с округлением вверх до KiB.
NEED_KB=$(( (DB_SIZE_BYTES * 3 + 1023) / 1024 ))
[[ "$AVAIL_KB" -ge "$NEED_KB" ]] \
    || { echo "STOP: свободно ${AVAIL_KB}K, для восстановления нужно ≈${NEED_KB}K" >&2; exit 49; }

printf '3.2.3\t%s\tok\trun_id=%s\tdump=%s\tsha256=%s\ttoc=%s\tpg=%s\n' \
    "$(date -u +%FT%TZ)" "$RUN_ID" "$DUMP" "$DUMP_SHA256" "$ENTRIES" "$PG_MAJOR" >> "$JOURNAL"

echo "OK 3.2.3"
echo "  run_id  : $RUN_ID"
echo "  dump    : $DUMP"
echo "  bytes   : $SIZE_NOW"
echo "  sha256  : OK"
echo "  toc     : $ENTRIES объектов"
echo "  dbname  : $DB_IN_DUMP"
echo "  pg_major: $PG_MAJOR (цель должна быть ≥)"
)
```

**Ожидаемый результат:**
- В `journal.rollback_dir` создан файл `db_rollback_<TS>.dump` в custom-формате, ненулевого размера, с валидным оглавлением.
- Создан `rollback_point.env` с путём, контрольной суммой и мажором PG.
- В `journal.path` добавлена строка выполнения.
- В `target.project_dir` не создано ни одного нового файла.

**Условия остановки:**
- `journal.rollback_dir` внутри `target.project_dir` или недоступен;
- контейнер `database.service` находится в статусе `restarting`/`exited` — это отдельный дефект, а не «нет БД»;
- `pg_dump` завершился с ненулевым кодом;
- `pg_restore -l` не читает созданный файл.

**Запись в журнал:** `3.2`, метка времени UTC, `ok`/`skipped`/`fail`, путь к дампу, `sha256`, `src_pg_major`, размер.

### 3.3. Резервирование Docker-образов (гарантия детерминированного отката)

**Место выполнения:** целевой сервер, Bash.

*(Выполняется обязательно при `migration.config.yaml: migration.mode` — `update` независимо от выбранного способа доставки образов на шаге 4.4. При `mode = initial` шаг пропускается)*

Сохранение текущего продуктивного образа должно выполняться строго до шагов 4.2 и 4.3, пока `docker-compose.yml` и `.env` в `target.project_dir` ссылаются на тег предыдущей версии.

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 3.3 rc=$rc line=$LINENO" >&2' ERR

if [[ "⚠️**<migration.mode>**" == "update" ]]; then
    cd -- "⚠️**<target.project_dir>**"

    ROLLBACK_IMAGE_ARCHIVE="⚠️**<journal.rollback_dir>**/images_rollback.tar"
    mapfile -t ROLLBACK_IMAGES < <(docker compose config --images | sort -u)

    ((${#ROLLBACK_IMAGES[@]} > 0)) \
        || { echo "STOP: не удалось определить образы Compose-проекта" >&2; exit 22; }

    for image in "${ROLLBACK_IMAGES[@]}"; do
        [[ -n "$image" ]] || continue
        docker image inspect "$image" >/dev/null 2>&1 \
            || { echo "STOP: образ '$image' отсутствует в локальном кэше Docker" >&2; exit 27; }
    done

    docker save -o "$ROLLBACK_IMAGE_ARCHIVE" "${ROLLBACK_IMAGES[@]}"
    [[ -s "$ROLLBACK_IMAGE_ARCHIVE" ]] \
        || { echo "STOP: архив образов отката пуст или не создан" >&2; exit 24; }

    printf '%s\n' "${ROLLBACK_IMAGES[@]}" \
        > "${ROLLBACK_IMAGE_ARCHIVE}.images"

    echo "OK 3.3: сохранены образы отката -> $ROLLBACK_IMAGE_ARCHIVE"
    printf '  image: %s\n' "${ROLLBACK_IMAGES[@]}"
fi
)
```

**Ожидаемый результат:** В `journal.rollback_dir` созданы архив `images_rollback.tar` и текстовый список образов `images_rollback.tar.images`.

## 4. Доставка и сборка кода

### 4.1. Проверка Git и доступа к репозиторию

**Место выполнения:** целевой сервер, Bash.
*(Выполняется, если `migration.config:code_delivery.method` — `remote_git` или `local_git`)*

```bash
git --version
# Только для remote_git:
git ls-remote ⚠️**<code_delivery.remote_git.url>**
```

**Ожидаемый результат:** Утилита `git` установлена. Команда `ls-remote` вывела список веток удаленного репозитория без интерактивного запроса пароля.

### 4.2. Доставка кода

*(Оператор выбирает и выполняет только один из вариантов А, Б или В согласно `migration.config:code_delivery.method`)*

*(КРИТИЧНО: все относительные пути `secrets.target_relative_path`, `storage.items[*].target_relative_path` и `code_delivery.exclude_paths` должны указываться строго от корня `target.project_dir` без ведущего префикса `./` или `/` — например, `.env`, `storage/media`. При наличии `./` фильтры `git clean -e` и `rsync --exclude` не сработают, что приведёт к удалению продуктивных данных)*

**Вариант А (remote_git)**

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 4.2.A rc=$rc line=$LINENO" >&2' ERR

cd ⚠️**<target.project_dir>**
git init
git remote add origin ⚠️**<code_delivery.remote_git.url>** 2>/dev/null || git remote set-url origin ⚠️**<code_delivery.remote_git.url>**
git fetch origin ⚠️**<code_delivery.remote_git.ref>**
git checkout -f FETCH_HEAD
sudo git -c safe.directory="*" clean -fd -e '⚠️**<secrets.target_relative_path>**' -e '⚠️**<storage.items[*].target_relative_path>**' -e '⚠️**<code_delivery.exclude_paths[*]>**'
)
```

**Вариант Б (local_git)**

**Место 1 (исходный сервер):**

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 4.2.B/source rc=$rc line=$LINENO" >&2' ERR

cd ⚠️**<source.project_dir>**
git update-ref refs/bundle/target ⚠️**<code_delivery.local_git.ref>**
git bundle create ⚠️**<source.project_dir>**/repo.bundle refs/bundle/target
git update-ref -d refs/bundle/target
)
```

**Место 2 (целевой сервер):**

```bash
cd ⚠️**<target.project_dir>**
rsync -avP -e "ssh -p ⚠️**<source.ssh.port>**" ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/repo.bundle ⚠️**<journal.rollback_dir>**/repo.bundle
git init
git fetch ⚠️**<journal.rollback_dir>**/repo.bundle refs/bundle/target
git checkout -f FETCH_HEAD
sudo git -c safe.directory="*" clean -fd -e '⚠️**<secrets.target_relative_path>**' -e '⚠️**<storage.items[*].target_relative_path>**' -e '⚠️**<code_delivery.exclude_paths[*]>**'
rm ⚠️**<journal.rollback_dir>**/repo.bundle
```
*(Примечание: каждый исключаемый путь передается отдельным флагом, например: `-e 'media' -e 'logs'`. Если список `exclude_paths` пуст — соответствующие флаги `-e` опускаются во избежание ошибки пустого паттерна. Для файлов, уже учтенных в `.gitignore`, флаг `-e` избыточен, так как `git clean -fd` без ключа `-x` их не удаляет.)*

**Место 3 (исходный сервер):**

```bash
rm ⚠️**<source.project_dir>**/repo.bundle
```

**Вариант В (no_git)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
# Очистка кэша, созданного контейнером, во избежание Permission denied при синхронизации
sudo find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
rsync -avz --delete -e "ssh -p ⚠️**<source.ssh.port>**" --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='⚠️**<secrets.target_relative_path>**' --exclude='⚠️**<storage.items[*].target_relative_path>**' ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/ .
```
*(Оператор обязательно дополняет команду ключами `--exclude` из `code_delivery.exclude_paths`, иначе флаг `--delete` удалит не учтенные директории)*

**Ожидаемый результат (для всех вариантов 4.2):** Исходный код приложения успешно доставлен в директорию `target.project_dir` на целевом сервере.

### 4.3. Доставка файла переменных окружения

*(КРИТИЧНО: `secrets.source_path` должен указывать на заранее подготовленный файл с production-конфигурацией (ALLOWED_HOSTS, пароли БД, DEBUG=False). Прямое копирование активного тестового .env приведет к отказу приложения на шаге 7.2)*

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 4.3 rc=$rc line=$LINENO" >&2' ERR

TARGET_PROJECT_DIR="⚠️**<target.project_dir>**"
SECRETS_SRC="⚠️**<secrets.source_path>**"
SECRETS_REL="⚠️**<secrets.target_relative_path>**"

for v in TARGET_PROJECT_DIR SECRETS_SRC SECRETS_REL; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done

TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
SECRETS_REL="${SECRETS_REL#./}"
case "$SECRETS_REL" in
    ""|/*|*'..'*) echo "STOP: secrets.target_relative_path ($SECRETS_REL) должен быть относительным путём внутри target.project_dir без '..' и ведущего '/'" >&2; exit 23 ;;
esac
SECRETS_DST="${TARGET_PROJECT_DIR}/${SECRETS_REL}"
mkdir -p -- "$(dirname -- "$SECRETS_DST")"

rsync -avz -e "ssh -p ⚠️**<source.ssh.port>**" "⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:$SECRETS_SRC" "$SECRETS_DST"
chmod 0600 "$SECRETS_DST"
)
```

**Ожидаемый результат:** Файл секретов доставлен по целевому пути внутри `target.project_dir` (при `mode=update` предыдущая версия `.env` предварительно сохранена в точке отката 3.1 для восстановления на шаге 8.2/8.4).

**Проверка совместимости образа СУБД доставленной конфигурации:** зафиксировать целевой тег образа PostgreSQL после доставки `docker-compose.yml` и `.env` — при `database.mode = restore` мажорная версия должна быть не ниже исходной (зафиксированной в 2.13); при `database.mode = keep` мажорная версия должна строго совпадать с версией целевого сервера (зафиксированной в 2.6 и 3.2.2).

```bash
cd ⚠️**<target.project_dir>**
docker compose config --images | grep -i postgres
```
### 4.4. Доставка и подготовка Docker-образов

*(Оператор выбирает и выполняет только один из вариантов)*

**Вариант А (Сборка из исходников на целевом сервере)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
docker compose pull
docker compose build
```

**Ожидаемый результат:** Скачаны базовые образы, локальная сборка завершена без ошибок.

**Вариант Б (Registry: Push / Pull)**

**Место 1 (исходный сервер):**

```bash
cd ⚠️**<source.project_dir>**
docker compose build
docker compose push
```

**Место 2 (целевой сервер):**

```bash
cd ⚠️**<target.project_dir>**
# При необходимости авторизации в закрытом Registry предварительно выполните: docker login
docker compose pull
```

**Ожидаемый результат:** Образы загружены в хранилище и успешно стянуты на целевой сервер.

**Вариант В (Прямой перенос: Save / Load)**

**Место 1 (исходный сервер):**

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 4.4.B/source rc=$rc line=$LINENO" >&2' ERR

cd ⚠️**<source.project_dir>**

mapfile -t TRANSFER_IMAGES < <(docker compose config --images | sort -u)
((${#TRANSFER_IMAGES[@]} > 0)) \
    || { echo "STOP: docker compose config --images не вернул ни одного образа" >&2; exit 22; }

# Сборка выполняется для всех сервисов с build:, а не только для application.service.
docker compose build

for image in "${TRANSFER_IMAGES[@]}"; do
    [[ -n "$image" ]] || continue
    docker image inspect "$image" >/dev/null 2>&1 \
        || { echo "STOP: после сборки отсутствует образ '$image'" >&2; exit 27; }
done

docker save -o ⚠️**<source.project_dir>**/compose_images.tar "${TRANSFER_IMAGES[@]}"
printf '%s\n' "${TRANSFER_IMAGES[@]}" > ⚠️**<source.project_dir>**/compose_images.tar.images
[[ -s ⚠️**<source.project_dir>**/compose_images.tar && -s ⚠️**<source.project_dir>**/compose_images.tar.images ]] \
    || { echo "STOP: архив образов или список образов не создан" >&2; exit 24; }
)
```

**Место 2 (целевой сервер):**

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 4.4.B/target rc=$rc line=$LINENO" >&2' ERR

cd ⚠️**<target.project_dir>**

rsync -avP -e "ssh -p ⚠️**<source.ssh.port>**" \
    ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/compose_images.tar \
    ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/compose_images.tar.images \
    ⚠️**<journal.rollback_dir>**/

[[ -s ⚠️**<journal.rollback_dir>**/compose_images.tar && -s ⚠️**<journal.rollback_dir>**/compose_images.tar.images ]] \
    || { echo "STOP: архив образов или список образов не доставлен" >&2; exit 24; }

docker load -i ⚠️**<journal.rollback_dir>**/compose_images.tar

mapfile -t TARGET_IMAGES < <(docker compose config --images | sort -u)
((${#TARGET_IMAGES[@]} > 0)) \
    || { echo "STOP: docker compose config --images на целевом сервере не вернул ни одного образа" >&2; exit 22; }

for image in "${TARGET_IMAGES[@]}"; do
    [[ -n "$image" ]] || continue
    docker image inspect "$image" >/dev/null 2>&1 \
        || { echo "STOP: после загрузки отсутствует целевой образ '$image'" >&2; exit 27; }
done

rm -f ⚠️**<journal.rollback_dir>**/compose_images.tar ⚠️**<journal.rollback_dir>**/compose_images.tar.images
)
```

**Место 3 (исходный сервер):**

```bash
rm -f ⚠️**<source.project_dir>**/compose_images.tar ⚠️**<source.project_dir>**/compose_images.tar.images
```

**Ожидаемый результат:** Все образы Compose-проекта перенесены, загружены и проверены в локальном хранилище Docker на целевом сервере.

## 5. Согласованное резервирование

### 5.1. Блокировка изменения данных (остановка writers)

*(Оператор выбирает вариант согласно `migration.config:consistency.capture_method`)*

**Вариант А (stop_writers)**

**Место выполнения:** исходный сервер, Bash.

#### 5.1.1. Остановка внешних источников записи на уровне ОС

Остановите все хостовые источники записи (`cron`, `systemd`-таймеры, внешние сервисы), выявленные на шаге 2.8 и перечисленные в "Журнале оператора":

```bash
# Остановить все внешние таймеры/сервисы проекта, зафиксированные в 2.8:
# sudo systemctl stop <project_timer_or_service>
# Для cron — временно отключить задачи проекта в crontab -e
systemctl list-timers --all --no-pager
```

**Ожидаемый результат:** Внешние планировщики на уровне ОС исходного сервера остановлены и не создают новых подключений к СУБД.

#### 5.1.2. Остановка контейнеров приложения и сброс соединений СУБД

```bash
cd ⚠️**<source.project_dir>**
docker compose stop
docker compose start ⚠️**<database.service>**

# Дождаться готовности СУБД после запуска контейнера:
for _ in $(seq 1 30); do
    docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' && break
    sleep 1
done
docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' \
    || { echo "STOP: СУБД не принимает соединения" >&2; exit 1; }

# Сбросить внешние подключения к БД (если обнаружены в 2.8), чтобы изолировать дамп:
docker compose exec -T ⚠️**<database.service>** sh -c 'psql -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname = current_database();"'
```

**Ожидаемый результат:** Источники записи остановлены. Контейнер СУБД продолжает работать.

**Вариант Б (coordinated)**

*(Допускается к выбору в `migration.config.yaml` только если в текущей версии кода на исходном сервере фактически реализована management-команда `set_maintenance_mode`. Если команда ещё не реализована, в конфигурации должен использоваться вариант `stop_writers`)*

**Место выполнения:** исходный сервер, Bash.

#### 5.1.Б.1. Остановка внешних и фоновых источников записи

HTTP-режим обслуживания блокирует только веб-запросы. До включения режима обслуживания остановите все хостовые планировщики (`cron`, `systemd`-таймеры) и фоновые воркеры, выявленные на шаге 2.8 и перечисленные в "Журнале оператора":

 ```bash
# Остановить внешние таймеры/сервисы проекта на уровне ОС (при наличии):
# sudo systemctl stop <project_timer_or_service>
# Для cron — временно отключить задачи проекта в crontab -e
systemctl list-timers --all --no-pager
```

#### 5.1.Б.2. Включение режима обслуживания в приложении и проверка транзакций

```bash
(
set -Eeuo pipefail
cd ⚠️**<source.project_dir>**

docker compose exec -T ⚠️**<application.service>** python manage.py help set_maintenance_mode >/dev/null 2>&1 \
    || { echo "STOP: команда set_maintenance_mode не реализована в приложении. Используйте capture_method=stop_writers (Вариант А)" >&2; exit 1; }

docker compose exec -T ⚠️**<application.service>** python manage.py set_maintenance_mode on

# Проверка отсутствия активных пишущих транзакций после включения режима обслуживания:
docker compose exec -T ⚠️**<database.service>** sh -c 'psql -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -c "SELECT pid, usename, state, left(query,60) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname = current_database() AND state <> '\''idle'\'';"'
)
```

**Ожидаемый результат:** Фоновые писатели остановлены, приложение переведено в режим обслуживания, активные транзакции в СУБД отсутствуют.

**Вариант В (not_needed)**

Действия не требуются.

### 5.2. Резервирование базы данных (логический дамп)

*(Выполняется только при `migration.config:database.mode` — `restore`. При `keep` или `fresh` шаг пропускается)*

**Место выполнения:** исходный сервер, Bash.

```bash
(
set -Eeuo pipefail
cd ⚠️**<source.project_dir>**
DUMP_FILE="db_dump_$(date +%Y%m%d_%H%M%S).dump"

docker compose exec -T ⚠️**<database.service>** sh -c 'pg_dump -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -Fc -Z 6 --no-owner --no-acl' > "$DUMP_FILE"

echo ""
echo "ИМЯ ФАЙЛА ДАМПА ДЛЯ ШАГА 5.3.1:"
echo "$DUMP_FILE"
echo ""
ls -lh "$DUMP_FILE"
)
```

**Ожидаемый результат:** Создан архив дампа БД. Файл существует и имеет ненулевой размер.

### 5.3. Перенос дампа БД и файловых хранилищ

**Место выполнения:** целевой сервер, Bash.

#### 5.3.1. Перенос дампа БД
*(Выполняется только при `migration.config:database.mode` — `restore`. При `keep` или `fresh` шаг пропускается)*

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 5.3.1 rc=$rc line=$LINENO" >&2' ERR    
cd ⚠️**<target.project_dir>**

DUMP_FILE="⚠️**<dump_file_name_from_step_5.2>**"

[[ -n "$DUMP_FILE" && "$DUMP_FILE" != *'⚠️'* && "$DUMP_FILE" != *'<'* && "$DUMP_FILE" != *'>'* && "$DUMP_FILE" != *'['* && "$DUMP_FILE" != *']'* && "$DUMP_FILE" != *'**'* ]] \
    || { echo "STOP: Имя файла дампа не подставлено: '$DUMP_FILE'" >&2; exit 22; }
echo "$DUMP_FILE" > ⚠️**<journal.rollback_dir>**/latest_db_dump.name

rsync -avP -e "ssh -p ⚠️**<source.ssh.port>**" ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/"$DUMP_FILE" ⚠️**<journal.rollback_dir>**/

[[ -s "⚠️**<journal.rollback_dir>**/$DUMP_FILE" ]] || { echo "STOP: доставленный дамп ⚠️**<journal.rollback_dir>**/$DUMP_FILE пуст или отсутствует" >&2; exit 23; }

# Очистка временного дампа на исходном сервере после успешного копирования
ssh -p ⚠️**<source.ssh.port>** -o BatchMode=yes ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>** "rm -f ⚠️**<source.project_dir>**/'$DUMP_FILE'"
)
```

#### 5.3.2. Перенос файловых хранилищ
*(Выполняется только для элементов `storage.items`, у которых `transfer` — `true`. При `mode = update` продуктивные хранилища с `transfer = false` не перезаписываются)*

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 5.3.2 rc=$rc line=$LINENO" >&2' ERR    
cd ⚠️**<target.project_dir>**
# Копирование файловых хранилищ (выполнить для каждого каталога из storage.items с transfer=true)
# Пример для каталога storage/cache:
mkdir -p ⚠️**<storage.items[*].target_relative_path>**
sudo chown -R "$(id -un):$(id -gn)" ⚠️**<storage.items[*].target_relative_path>**
rsync -avP --delete --rsync-path="sudo -k -n rsync" -e "ssh -p ⚠️**<source.ssh.port>**" ⚠️**<source.ssh.user>**@⚠️**<source.ssh.host>**:⚠️**<source.project_dir>**/⚠️**<storage.items[*].source_relative_path>**/ ⚠️**<storage.items[*].target_relative_path>**/
)
```

**Ожидаемый результат:** Файлы хранилищ (и, при необходимости, архив дампа БД) скопированы на целевой сервер.

## 6. Восстановление БД и запуск

### 6.1. Настройка прав доступа к файловым хранилищам

**Место выполнения:** целевой сервер, Bash.

*(Внимание: для корректного резервирования в 3.1 и отката в 8.2 все пути `target_relative_path` должны располагаться строго внутри директории `target.project_dir`. Внешние docker-тома или пути вне проекта текущей процедурой отката не покрываются)*

```bash
cd ⚠️**<target.project_dir>**

# Выполнить команду для каждого каталога из списка storage.items:
mkdir -p ⚠️**<storage.items[*].target_relative_path>**
sudo chown -R ⚠️**<storage.items[*].uid>**:⚠️**<storage.items[*].gid>** ⚠️**<storage.items[*].target_relative_path>**
```

**Ожидаемый результат:** Права на целевые директории хранилищ изменены для корректного доступа на запись изнутри контейнеров приложения.

### 6.2. Инициализация и восстановление базы данных

*(Оператор выбирает вариант согласно `migration.config:database.mode`)*

**Вариант А (restore)**

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail    
cd ⚠️**<target.project_dir>**

# Проверка наличия файла дампа до запуска/пересоздания тома СУБД:
[[ -f ⚠️**<journal.rollback_dir>**/latest_db_dump.name ]] || { echo "STOP: Файл-указатель ⚠️**<journal.rollback_dir>**/latest_db_dump.name не найден" >&2; exit 1; }
DUMP_FILE=$(cat ⚠️**<journal.rollback_dir>**/latest_db_dump.name)
[[ -f "⚠️**<journal.rollback_dir>**/$DUMP_FILE" ]] || { echo "STOP: Дамп ⚠️**<journal.rollback_dir>**/$DUMP_FILE не найден" >&2; exit 1; }

docker compose up -d ⚠️**<database.service>**

# Дождаться TCP-готовности: временный сервер initdb работает только через Unix-сокет.
# Исчерпание попыток не подтверждает конфликт версий и не разрешает удаление тома.
for _ in $(seq 1 120); do
    docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' 2>/dev/null && break
    sleep 1
done
if ! docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' 2>/dev/null; then
    docker compose ps -a ⚠️**<database.service>** >&2 || true
    docker compose logs --no-color --tail=100 ⚠️**<database.service>** >&2 || true
    echo "STOP: СУБД пока не принимает TCP-соединения. Контейнер и тома сохранены." >&2
    echo "Проверить логи: конфликт версий подтверждается сообщением PostgreSQL 'database files are incompatible with server' и DETAIL с версиями." >&2
    echo "Инициализация и docker-entrypoint-initdb.d могут занимать минуты; если они продолжаются — дождаться завершения и повторить 6.2 (Вариант А)." >&2
    echo "При подтверждённом конфликте версий выполнить процедуру 6.2.1; автоматически тома не удалять." >&2
    exit 1
fi

docker compose exec -T ⚠️**<database.service>** pg_restore -l < "⚠️**<journal.rollback_dir>**/$DUMP_FILE" >/dev/null \
    || { echo "STOP: Архив дампа ⚠️**<journal.rollback_dir>**/$DUMP_FILE повреждён" >&2; exit 1; }

# Очистка целевой БД перед восстановлением (гарантия идемпотентности):
docker compose exec -T ⚠️**<database.service>** sh -c 'dropdb --maintenance-db=template1 -U "$⚠️**<database.environment_keys.user>**" --if-exists --force "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}"'
docker compose exec -T ⚠️**<database.service>** sh -c 'createdb --maintenance-db=template1 -T template0 -U "$⚠️**<database.environment_keys.user>**" -O "$⚠️**<database.environment_keys.user>**" "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}"'

# Восстановление дампа (строгая остановка при первой ошибке):
docker compose exec -T ⚠️**<database.service>** sh -c 'pg_restore -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" --clean --if-exists --no-owner --no-acl --exit-on-error -1' < "⚠️**<journal.rollback_dir>**/$DUMP_FILE"
```

**Ожидаемый результат:** Контейнер СУБД запущен. Логический дамп успешно развернут без критических ошибок.

**Вариант Б (fresh)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
docker compose up -d ⚠️**<database.service>**

for _ in $(seq 1 30); do
    docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' && break
    sleep 1
done
docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' \
    || { echo "STOP: СУБД не принимает соединения" >&2; exit 1; }
```

**Ожидаемый результат:** Запущен пустой контейнер СУБД, готовый к первичному накатыванию схемы.

**Вариант В (keep)**

*(Используется при `migration.mode = update`, когда продуктивная БД целевого сервера сохраняется и обновляется только миграциями на шаге 6.3)*

**Место выполнения:** целевой сервер, Bash.

```bash
(
set -Eeuo pipefail
cd ⚠️**<target.project_dir>**

if [[ -f "⚠️**<journal.rollback_dir>**/rollback_point.env" ]]; then
    . "⚠️**<journal.rollback_dir>**/rollback_point.env"
    DST_PG="$(docker compose run --rm --no-deps --entrypoint postgres ⚠️**<database.service>** --version | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
    [[ -z "${PG_MAJOR:-}" || "$DST_PG" == "$PG_MAJOR" ]] \
        || { echo "STOP: при database.mode=keep смена мажорной версии PG ($PG_MAJOR -> $DST_PG) запрещена (несовместимость PGDATA)" >&2; exit 1; }
fi

docker compose up -d ⚠️**<database.service>**

for _ in $(seq 1 30); do
    docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' 2>/dev/null && break
    sleep 1
done
docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' \
    || { echo "STOP: СУБД не принимает соединения" >&2; exit 1; }
)
```

**Ожидаемый результат:** Контейнер СУБД запущен с существующими продуктивными данными и готов к накатыванию миграций.

### 6.2.1. Очистка тома СУБД при конфликте мажорных версий (PGDATA)

**Место выполнения:** целевой сервер, Bash.

*(Выполняется строго в случае прерывания шага 6.2 (Вариант А) из-за ошибки `database files are incompatible with server` в логах PostgreSQL)*

```bash
(
set -Eeuo pipefail
cd ⚠️**<target.project_dir>**

echo "Удаление контейнера и связанных томов СУБД..."
CID="$(docker compose ps -aq ⚠️**<database.service>** 2>/dev/null || true)"
PG_MNT_TYPE=""
PG_MNT_SRC=""
if [[ -n "$CID" ]]; then
    PG_DEST="$(docker inspect -f '{{json .Config.Env}}' "$CID" 2>/dev/null | grep -o '"PGDATA=[^"]*"' | cut -d= -f2- | tr -d '"' | head -1 || true)"
    PG_DEST="${PG_DEST:-/var/lib/postgresql/data}"
    PG_MNT_TYPE="$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$PG_DEST\"}}{{.Type}}{{end}}{{end}}" "$CID" 2>/dev/null || true)"
    PG_MNT_SRC="$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$PG_DEST\"}}{{if eq .Type \"volume\"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}" "$CID" 2>/dev/null || true)"
fi

docker compose rm -f -s -v ⚠️**<database.service>**

if [[ "$PG_MNT_TYPE" == "volume" && -n "$PG_MNT_SRC" ]]; then
    docker volume rm -f "$PG_MNT_SRC" >/dev/null || true
    echo "Удален том: $PG_MNT_SRC"
elif [[ "$PG_MNT_TYPE" == "bind" && -n "$PG_MNT_SRC" && "$PG_MNT_SRC" == /* ]]; then
    sudo rm -rf -- "${PG_MNT_SRC:?}"/*
    echo "Очищена bind-директория: $PG_MNT_SRC"
fi

echo "Повторный запуск СУБД для инициализации пустого тома..."
docker compose up -d ⚠️**<database.service>**

for _ in $(seq 1 120); do
    docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' 2>/dev/null && break
    sleep 1
done

docker compose exec -T ⚠️**<database.service>** sh -c 'pg_isready -h 127.0.0.1 -U "$⚠️**<database.environment_keys.user>**" -d "${⚠️**<database.environment_keys.name>**:-$⚠️**<database.environment_keys.user>**}" -q' \
    || { echo "STOP: СУБД не поднялась после пересоздания тома" >&2; exit 1; }

echo "ОК. Том пересоздан. Выполните скрипт шага 6.2 (Вариант А) повторно для заливки дампа."
)
```

### 6.3. Применение миграций и запуск приложения

*(Оператор выбирает вариант согласно `migration.config:application.migrations_on_web_start`)*

**Вариант А (true)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
docker compose up -d
```

**Ожидаемый результат:** Все контейнеры запущены. Приложение самостоятельно выполнило миграции (при необходимости) во время старта.

**Вариант Б (false)**

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**
# Ручное применение миграций до запуска основного пула
docker compose run --rm ⚠️**<application.service>** python manage.py migrate

# Запуск всех контейнеров проекта
docker compose up -d
```

**Ожидаемый результат:** Миграции успешно применены, все контейнеры проекта запущены и работают.

## 7. Проверка готовности

### 7.1. Проверка статуса контейнеров и логов

**Место выполнения:** целевой сервер, Bash.

```bash
cd ⚠️**<target.project_dir>**

# Проверка, что все контейнеры находятся в статусе "Up" и не перезагружаются
docker compose ps

# Проверка отсутствия критических ошибок (Traceback, FATAL) при старте веб-сервера
docker compose logs --tail=100 ⚠️**<application.service>**
```

**Ожидаемый результат:** Все сервисы запущены. В логах нет циклических перезагрузок (crashloop) или ошибок подключения к БД.

### 7.2. Проверка локальной доступности (Healthcheck)

**Место выполнения:** целевой сервер, Bash.

Дополнить существующую секцию `application` в `migration.config.yaml` следующими параметрами. Значения примера заменить фактическими; вторую секцию `application` не создавать:

<!-- ```yaml
application:
  host: app.example.com
  healthcheck:
    mode: container
    published_port: null
    container_port: 8000
    path: /health/

`application.host` — production-домен из Django `ALLOWED_HOSTS`, без схемы и порта. `healthcheck.mode` — `host` или `container`. Выполнить только соответствующий вариант ниже. `published_port` заполняется для `host` и означает порт хоста, доступный по `127.0.0.1`; `container_port` заполняется для `container` и означает внутренний HTTP-порт приложения. Например, при `ports: ["8080:8000"]` это `8080` и `8000` соответственно. `path` — существующий endpoint готовности, начинается с `/` и возвращает `200` только при готовности приложения.
``` -->

**Вариант А (`mode=host`, HTTP-порт опубликован на loopback хоста через `ports:`):**

```bash
(
set -Eeuo pipefail
cd -- '⚠️**<target.project_dir>**'

if ! STATUS="$(curl --silent --show-error --noproxy '*' \
    --connect-timeout 5 --max-time 10 \
    -H 'Host: ⚠️**<application.host>**' \
    --output /dev/null --write-out '%{http_code}' \
    'http://127.0.0.1:⚠️**<application.healthcheck.published_port>**⚠️**<application.healthcheck.path>**')"; then
    echo 'STOP: транспортная ошибка HTTP-проверки с хоста' >&2
    exit 70
fi

printf 'HTTP Status: %s\n' "$STATUS"
[[ "$STATUS" == 200 ]] \
    || { echo 'STOP: ожидался HTTP 200' >&2; exit 71; }
echo 'OK 7.2'
)
```

**Вариант Б (`mode=container`, проверка внутри контейнера приложения):**

`curl` внутри образа не требуется. Используется `python`, который уже применяется в командах приложения этого runbook. HTTP-процесс должен принимать подключения на `127.0.0.1:<container_port>` внутри контейнера; обычно он слушает `0.0.0.0:<container_port>`. Объявления `expose:` и `ports:` для этой проверки не требуются.

```bash
(
set -Eeuo pipefail
cd -- '⚠️**<target.project_dir>**'

docker compose exec -T '⚠️**<application.service>**' python - \
    'http://127.0.0.1:⚠️**<application.healthcheck.container_port>**⚠️**<application.healthcheck.path>**' \
    '⚠️**<application.host>**' <<'PY'
import sys
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

url, host = sys.argv[1:]
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect()
)
request = urllib.request.Request(url, headers={"Host": host})
try:
    with opener.open(request, timeout=5) as response:
        status = response.status
except urllib.error.HTTPError as exc:
    status = exc.code
    exc.close()
except (urllib.error.URLError, OSError, ValueError) as exc:
    print(f"STOP: transport error: {exc}", file=sys.stderr)
    sys.exit(70)

print(f"HTTP Status: {status}")
if status != 200:
    print("STOP: expected HTTP 200", file=sys.stderr)
    sys.exit(71)
print("OK 7.2")
PY
)
```

**Ожидаемый результат:** Выбранная команда завершилась с кодом `0`, выведены `HTTP Status: 200` и `OK 7.2`. Обе ветки передают production Host, не используют proxy из окружения и не следуют перенаправлениям. Ошибки `400`/`500` и любые другие статусы, отличные от `200`, приводят к ненулевому коду завершения.

При `SECURE_SSL_REDIRECT=True` прямой HTTP-запрос может вернуть `301`; такой ответ не подтверждает готовность endpoint. До выполнения проверки настроить исключение из redirect для endpoint готовности либо использовать отдельную проверку HTTPS-входа. Не подставлять `X-Forwarded-Proto` без учёта фактических настроек доверия к proxy. Для приложения, принимающего запросы только через Unix socket, требуется отдельная команда проверки. Проверка этого шага не подтверждает доступность reverse proxy, TLS и внешней маршрутизации. Значение curl `000` означает отсутствие HTTP-ответа; причину транспортного сбоя показывает stderr.

### 7.3. Включение фоновых источников записи (writers) на целевом сервере

**Место выполнения:** целевой сервер, Bash.
*(Выполняется только после успешного прохождения шагов 7.1 и 7.2)*

1. Запустите внешние источники записи (`worker`, `cron`, `systemd-таймеры`) на **целевом** сервере (остановленные на шаге 3.0 при `mode=update` или настраиваемые впервые при `mode=initial`).
2. **КРИТИЧНО (предотвращение Split-Brain):** Источники записи на **исходном** сервере, остановленные на шаге 5.1, при успешном завершении миграции **НЕ запускаются** (за исключением случаев, когда исходный сервер — независимый тестовый контур, не конкурирующий за внешние очереди/интеграции с целевым сервером).

3. **Очистка транзитных артефактов:** Если на шаге 5.3.1 переносился дамп БД, удалите его после подтверждения работоспособности приложения:
```bash
DUMP_FILE=$(cat ⚠️**<journal.rollback_dir>**/latest_db_dump.name 2>/dev/null || true)
[[ -n "$DUMP_FILE" ]] && rm -f -- "⚠️**<journal.rollback_dir>**/$DUMP_FILE" ⚠️**<journal.rollback_dir>**/latest_db_dump.name
```

**Ожидаемый результат:** Целевой сервер полностью введён в строй и готов к переключению внешнего трафика.

## 8. Процедура отката (Rollback)

*(Выполняется при сбое миграции для возврата целевого сервера в исходное состояние. Для раннего сбоя initial предусмотрена отдельная ветка в 8.1.)*

### 8.1. Остановка неисправной версии

**Место выполнения:** целевой сервер, Bash.

**Ранний откат initial после сбоя на 4.1–4.3**

Применять этот блок только при одновременном выполнении всех условий:

- `migration.mode=initial`.
- Каталог `target.project_dir` создан для текущей миграции и не содержит данных, которые требуется сохранить.
- На целевом сервере в рамках этой миграции, включая предыдущие попытки,
  не выполнялись команды создания контейнеров, томов или сетей
  (`docker compose up/run/create`, `docker volume create`, `docker network create` и аналогичные).
- Команды создания Docker-ресурсов не выполняются параллельно.

Отсутствие `docker-compose.yml` или пустой список контейнеров не заменяют эти условия.
Если хотя бы одно условие не подтверждено, использовать основной блок ниже.

```bash
(
set -Eeuo pipefail
MIGRATION_MODE="⚠️**<migration.mode>**"
TARGET_PROJECT_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
JOURNAL="⚠️**<journal.path>**"

[[ "$MIGRATION_MODE" == "initial" ]] \
    || { echo "STOP 8.1: ранний откат разрешён только для initial" >&2; exit 81; }

for var in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    value="${!var}"
    [[ "$value" == /* && "$value" != *'⚠️'* && "$value" != *'<'* && "$value" != *'>'* && "$value" != *'['* && "$value" != *']'* && "$value" != *'**'* ]] \
        || { echo "STOP 8.1: некорректное значение $var" >&2; exit 81; }
done

TARGET_PROJECT_DIR="$(realpath -m -- "$TARGET_PROJECT_DIR")"
ROLLBACK_DIR="$(realpath -m -- "$ROLLBACK_DIR")"
JOURNAL="$(realpath -m -- "$JOURNAL")"
[[ "$TARGET_PROJECT_DIR" == /*/* ]] \
    || { echo "STOP 8.1: недопустимый каталог проекта" >&2; exit 81; }

for protected in "$ROLLBACK_DIR" "$JOURNAL"; do
    case "$protected" in
        "$TARGET_PROJECT_DIR"|"$TARGET_PROJECT_DIR"/*)
            echo "STOP 8.1: журнал или rollback_dir находятся внутри project_dir" >&2
            exit 81 ;;
    esac
done

if ! ctrs="$(docker ps -aq \
    --filter "label=com.docker.compose.project.working_dir=$TARGET_PROJECT_DIR")"; then
    echo "STOP 8.1: не удалось проверить контейнеры проекта" >&2
    exit 81
fi
[[ -z "$ctrs" ]] \
    || { echo "STOP 8.1: обнаружены контейнеры; условия раннего отката не выполнены" >&2; exit 81; }

cd /
sudo rm -rf -- "$TARGET_PROJECT_DIR"
echo "OK 8.1: ранний откат initial выполнен; каталог проекта удалён."
echo "Основной блок 8.1, шаги 8.2, 8.3 и 8.4 «Место 1» пропустить."
echo "Перейдите к 8.4 «Место 2» для возврата исходного сервера в работу."
)
```

**Основной откат:** выполнять следующий блок, только если ранний откат выше не выполнялся.

```bash
(
set -Eeuo pipefail
MIGRATION_MODE="⚠️**<migration.mode>**"
TARGET_PROJECT_DIR="⚠️**<target.project_dir>**"
ROLLBACK_DIR="⚠️**<journal.rollback_dir>**"
JOURNAL="⚠️**<journal.path>**"

[[ -n "$MIGRATION_MODE" && "$MIGRATION_MODE" != *'⚠️'* && "$MIGRATION_MODE" != *'<'* && "$MIGRATION_MODE" != *'>'* && "$MIGRATION_MODE" != *'['* && "$MIGRATION_MODE" != *']'* && "$MIGRATION_MODE" != *'**'* ]] \
    || { echo "STOP: migration.mode не подставлена: '$MIGRATION_MODE'" >&2; exit 22; }
[[ -n "$TARGET_PROJECT_DIR" && "$TARGET_PROJECT_DIR" == /*/* && "$TARGET_PROJECT_DIR" != *'⚠️'* && "$TARGET_PROJECT_DIR" != *'<'* && "$TARGET_PROJECT_DIR" != *'>'* && "$TARGET_PROJECT_DIR" != *'['* && "$TARGET_PROJECT_DIR" != *']'* && "$TARGET_PROJECT_DIR" != *'**'* ]] \
    || { echo "STOP: некорректный путь TARGET_PROJECT_DIR: '$TARGET_PROJECT_DIR'" >&2; exit 22; }

TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"
case "$ROLLBACK_DIR/" in
    "$TARGET_PROJECT_DIR"/*|"$TARGET_PROJECT_DIR"/)
        echo "STOP: rollback_dir внутри project_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac
case "$JOURNAL" in
    "$TARGET_PROJECT_DIR"|"$TARGET_PROJECT_DIR"/*)
        echo "STOP: journal.path внутри project_dir: $JOURNAL" >&2; exit 23 ;;
esac

cd -- "$TARGET_PROJECT_DIR"

cleanup_containers() {
    local -a down_args=("$@")
    local -a cids=()
    local rc=0 ctrs left

    if ! ctrs="$(docker ps -aq --filter "label=com.docker.compose.project.working_dir=$TARGET_PROJECT_DIR")"; then
        echo "STOP 8.1: не удалось получить список контейнеров проекта" >&2
        exit 81
    fi

    if [[ -f "$TARGET_PROJECT_DIR/docker-compose.yml" ]]; then
        docker compose down "${down_args[@]}" || rc=$?
    else
        echo "WARN 8.1: docker-compose.yml отсутствует — compose down пропущен" >&2
        rc=1
    fi

    if (( rc != 0 )); then
        if [[ "$MIGRATION_MODE" == "initial" ]]; then
            echo "STOP 8.1: docker compose down rc=$rc; очистка initial не завершена" >&2
            exit 81
        fi
        echo "WARN 8.1: docker compose down rc=$rc; fallback по label working_dir" >&2
        ctrs="$(docker ps -aq --filter "label=com.docker.compose.project.working_dir=$TARGET_PROJECT_DIR")" || exit 81
        if [[ -n "$ctrs" ]]; then
            mapfile -t cids <<< "$ctrs"
            docker rm -f "${cids[@]}" || { echo "STOP 8.1: не удалось удалить контейнеры" >&2; exit 81; }
        fi
    fi

    left="$(docker ps -aq --filter "label=com.docker.compose.project.working_dir=$TARGET_PROJECT_DIR")" || exit 81
    if [[ -n "$left" ]]; then
        echo "STOP 8.1: остались контейнеры проекта: $left" >&2
        exit 81
    fi
}

if [[ "$MIGRATION_MODE" == "initial" ]]; then
    echo "8.1: mode=initial — удаление контейнеров, томов (БД) и директории проекта."
    cleanup_containers -v --remove-orphans
    cd /
    sudo rm -rf -- "$TARGET_PROJECT_DIR"
    echo "Откат initial завершен: compose down -v --remove-orphans выполнен, каталог проекта удалён."
    echo "External-тома и external-сети сохраняются согласно правилам Docker Compose."
    echo "Шаги 8.2, 8.3 и 8.4 «Место 1» ВЫПОЛНЯТЬ НЕ ТРЕБУЕТСЯ."
    echo "ВНИМАНИЕ: Перейдите к шагу 8.4 «Место 2» для возврата исходного сервера в работу."
else
    cleanup_containers --remove-orphans
fi
)
```

### 8.2. Восстановление файлов проекта

**Место выполнения:** целевой сервер, Bash.

```bash
(
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
MIGRATION_MODE='⚠️**<migration.mode>**'

[[ -n "$MIGRATION_MODE" && "$MIGRATION_MODE" != *'⚠️'* && "$MIGRATION_MODE" != *'<'* && "$MIGRATION_MODE" != *'>'* && "$MIGRATION_MODE" != *'['* && "$MIGRATION_MODE" != *']'* && "$MIGRATION_MODE" != *'**'* ]] \
    || { echo "STOP: MIGRATION_MODE не подставлена: '$MIGRATION_MODE'" >&2; exit 22; }
[[ "$MIGRATION_MODE" == "initial" ]] && { echo "8.2: mode=initial — откат файлов не требуется, пропускаем"; exit 0; }

# ── 1. проверка подстановки ──
for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
ROLLBACK_DIR="${ROLLBACK_DIR%/}"

# ── 2. guard: точка отката не внутри зоны --delete ──
case "$ROLLBACK_DIR/" in
    "$TARGET_PROJECT_DIR"/*|"$TARGET_PROJECT_DIR"/)
        echo "STOP: rollback_dir внутри project_dir: $ROLLBACK_DIR" >&2; exit 23 ;;
esac
case "$JOURNAL" in
    "$TARGET_PROJECT_DIR"|"$TARGET_PROJECT_DIR"/*)
        echo "STOP: journal.path внутри project_dir (будет затёрт rsync --delete): $JOURNAL" >&2; exit 23 ;;
esac
[[ -d "$TARGET_PROJECT_DIR" ]] || { echo "STOP: нет каталога $TARGET_PROJECT_DIR" >&2; exit 26; }
cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }

# ── 3. выбор точки: чтение последнего run_id, где подтверждены И 3.1 ok, И 3.2.3 ok ──
[[ -f "$JOURNAL" ]] || { echo "STOP: нет журнала $JOURNAL" >&2; exit 24; }
read -r RUN_ID BACKUP < <(awk -F'\t' '
    $1=="3.1" && $3=="ok" {
        r=""; b="";
        for(i=4;i<=NF;i++) {
            if($i~/^run_id=/) {sub(/^run_id=/,"",$i); r=$i}
            if($i~/^backup=/) {sub(/^backup=/,"",$i); b=$i}
        }
        if(r!="" && b!="") { f[r]=b; last_r=r }
    }
    $1=="3.2.3" && $3=="ok" {
        for(i=4;i<=NF;i++) if($i~/^run_id=/) {sub(/^run_id=/,"",$i); if($i in f) valid_r=$i}
    }
    END { if(valid_r!="" && valid_r==last_r) print valid_r, f[valid_r] }
' "$JOURNAL") || true

if [[ -z "$BACKUP" || ! -d "$BACKUP" || ! -f "$BACKUP/docker-compose.yml" ]]; then
    echo "STOP: в журнале для последнего запуска 3.1 нет подтверждённой пары (3.1 ok + 3.2.3 ok) с валидным каталогом. RUN_ID='${RUN_ID:-}' BACKUP='${BACKUP:-}'" >&2
    exit 24
fi
if [[ -f "${BACKUP}.manifest.sha256" ]]; then
    sudo sh -c "cd -- '$BACKUP' && sha256sum -c '${BACKUP}.manifest.sha256' >/dev/null" \
        || { echo "STOP: нарушена целостность файлов бэкапа по манифесту ${BACKUP}.manifest.sha256" >&2; exit 24; }
fi

# ── 4. подтверждение: rsync --delete уничтожит текущее содержимое ──
echo "project_dir : $TARGET_PROJECT_DIR"
echo "backup      : $BACKUP"
echo "содержимое project_dir будет заменено на backup --delete"
read -r -p 'Продолжить? [yes/NO] ' a
[[ "$a" == "yes" ]] || { echo "Отменено оператором."; exit 62; }

# ── 5. восстановление ──
sudo rsync -aHAX --numeric-ids --delete -- "$BACKUP/" "$TARGET_PROJECT_DIR/" \
    || { echo "STOP: rsync не выполнен" >&2; exit 63; }

# ── 6. сверка: пустой вывод = содержимое совпадает ──
DIFF_FILE="$(mktemp)"
sudo rsync -aHAXnc --numeric-ids -n -i --delete -- "$BACKUP/" "$TARGET_PROJECT_DIR/" > "$DIFF_FILE" \
    || { echo "STOP: сверка не выполнена" >&2; exit 63; }
if [[ -s "$DIFF_FILE" ]]; then
    echo "STOP: восстановлено не всё, расхождения:" >&2
    head -20 "$DIFF_FILE" >&2; rm -f "$DIFF_FILE"; exit 64
fi
rm -f "$DIFF_FILE"

# ── 7. восстановленный compose парсится ──
docker compose config --services >/dev/null 2>&1 \
    || { echo "STOP: docker-compose.yml восстановлен, но не парсится" >&2; exit 65; }

printf '8.2\t%s\tok\trun_id=%s\tbackup=%s\ttarget=%s\n' \
    "$(date -u +%FT%TZ)" "$RUN_ID" "$BACKUP" "$TARGET_PROJECT_DIR" >> "$JOURNAL"

echo "OK 8.2"
echo "  run_id : $RUN_ID"
echo "  backup : $BACKUP"
echo "  target : $TARGET_PROJECT_DIR"
echo "  next   : 8.3 (восстановление БД), затем 8.4"
)
```

**Ожидаемый результат:** Исходный код и переменные окружения возвращены к состоянию до миграции.

### 8.3. Восстановление базы данных

**Место выполнения:** целевой сервер, Bash.

```bash
(
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
MIGRATION_MODE='⚠️**<migration.mode>**'

[[ -n "$MIGRATION_MODE" && "$MIGRATION_MODE" != *'⚠️'* && "$MIGRATION_MODE" != *'<'* && "$MIGRATION_MODE" != *'>'* && "$MIGRATION_MODE" != *'['* && "$MIGRATION_MODE" != *']'* && "$MIGRATION_MODE" != *'**'* ]] \
    || { echo "STOP: MIGRATION_MODE не подставлена: '$MIGRATION_MODE'" >&2; exit 22; }
[[ "$MIGRATION_MODE" == "initial" ]] && { echo "8.3: mode=initial — откат БД не требуется, пропускаем"; exit 0; }

# ── 1. проверка подстановки ──
for v in TARGET_PROJECT_DIR ROLLBACK_DIR JOURNAL; do
    val="${!v}"
    [[ -n "$val" && "$val" == /* && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
for v in DB_SERVICE DB_USER DB_NAME; do
    val="${!v}"
    [[ -n "$val" && "$val" != *'⚠️'* && "$val" != *'<'* && "$val" != *'>'* && "$val" != *'['* && "$val" != *']'* && "$val" != *'**'* ]] \
        || { echo "STOP: $v не подставлена: '$val'" >&2; exit 22; }
done
TARGET_PROJECT_DIR="${TARGET_PROJECT_DIR%/}"
cd -- "$TARGET_PROJECT_DIR" || { echo "STOP: cd не выполнен" >&2; exit 26; }

# ── 2. точка отката: строго тот же run_id, что и для файлов (или последняя полная пара 3.1+3.2.3) ──
[[ -f "$JOURNAL" ]] || { echo "STOP: нет журнала $JOURNAL" >&2; exit 70; }
read -r RUN_ID DUMP SRC_PG < <(awk -F'\t' '
    $1=="3.1" && $3=="ok" {
        for(i=4;i<=NF;i++) if($i~/^run_id=/) {sub(/^run_id=/,"",$i); has_31[$i]=1; last_r=$i}
    }
    $1=="3.2.2" && $3=="ok" {
        r=""; p="";
        for(i=4;i<=NF;i++) {
            if($i~/^run_id=/) {sub(/^run_id=/,"",$i); r=$i}
            if($i~/^pg=/)     {sub(/^pg=/,"",$i); p=$i}
        }
        if(r!="") pg[r]=p
    }
    $1=="3.2.3" && $3=="ok" {
        r=""; d="";
        for(i=4;i<=NF;i++) {
            if($i~/^run_id=/) {sub(/^run_id=/,"",$i); r=$i}
            if($i~/^dump=/)   {sub(/^dump=/,"",$i); d=$i}
        }
        if(r!="" && d!="" && (r in has_31)) { valid_r=r; dump[r]=d }
    }
    END { if(valid_r!="" && valid_r==last_r) print valid_r, dump[valid_r], (pg[valid_r] ? pg[valid_r] : "?") }
' "$JOURNAL") || true
[[ -n "${DUMP:-}" ]] || { echo "STOP: в журнале для последнего запуска 3.1 нет подтверждённой пары (3.1 ok + 3.2.3 ok)" >&2; exit 70; }
[[ -f "$DUMP" ]] || { echo "STOP: файл дампа отсутствует: $DUMP" >&2; exit 71; }
[[ -f "${DUMP}.sha256" ]] || { echo "STOP: нет спутника ${DUMP}.sha256" >&2; exit 72; }
sha256sum -c "${DUMP}.sha256" >/dev/null \
    || { echo "STOP: sha256 дампа не совпадает: $DUMP" >&2; exit 72; }

# ── 3. нормализация мажора источника ──
[[ "${SRC_PG:-?}" != "?" ]] || SRC_PG=""    

# ── 4. запрет downgrade (проверка по образу ДО монтирования PGDATA) ──
DST_PG="$(docker compose run --rm --no-deps --entrypoint postgres "$DB_SERVICE" --version | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
if [[ -n "$SRC_PG" && "$DST_PG" -lt "$SRC_PG" ]]; then
    echo "STOP: target PG $DST_PG < source PG $SRC_PG — дамп несовместим" >&2; exit 73
fi

# ── 5. поднять БД (при несовместимости тома от более новой версии PG — пересоздать том) ──
docker compose up -d "$DB_SERVICE" || { echo "STOP: не удалось поднять $DB_SERVICE" >&2; exit 74; }
for _ in $(seq 1 120); do
    docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -h 127.0.0.1 -U \"\$$DB_USER\" -d postgres -q" 2>/dev/null && break
    sleep 1
done
if ! docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -h 127.0.0.1 -U \"\$$DB_USER\" -d postgres -q" 2>/dev/null; then
    HAS_CONFLICT="$(docker compose logs "$DB_SERVICE" 2>&1 | grep -c "database files are incompatible with server" || true)"
    if [[ "$HAS_CONFLICT" -eq 0 ]]; then
        echo "STOP: СУБД не стартует по неизвестной причине (таймаут 120с). Откат прерван для защиты PGDATA." >&2
        docker compose logs --tail=50 "$DB_SERVICE" >&2 || true
        exit 74
    fi
    echo "WARN: Подтверждён конфликт версий PGDATA. Пересоздание тома БД под восстановление из проверенного дампа..." >&2
    CID="$(docker compose ps -aq "$DB_SERVICE" 2>/dev/null || true)"
    PG_VOLS=""
    [[ -n "$CID" ]] && PG_VOLS="$(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' "$CID" 2>/dev/null || true)"
    docker compose rm -f -s -v "$DB_SERVICE"
    for vol in $PG_VOLS; do docker volume rm -f "$vol" >/dev/null; done
    docker compose up -d "$DB_SERVICE" || { echo "STOP: не удалось поднять $DB_SERVICE после очистки тома" >&2; exit 74; }
    for _ in $(seq 1 120); do
        docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -h 127.0.0.1 -U \"\$$DB_USER\" -d postgres -q" 2>/dev/null && break
        sleep 1
    done
    docker compose exec -T "$DB_SERVICE" sh -c "pg_isready -h 127.0.0.1 -U \"\$$DB_USER\" -d postgres -q" \
        || { echo "STOP: СУБД не принимает соединения даже на чистом томе" >&2; exit 74; }
fi

# ── 6. атомарная замена БД (не DROP SCHEMA: сохраняет owner и права) ──
docker compose exec -T "$DB_SERVICE" sh -c "dropdb --maintenance-db=template1 -U \"\$$DB_USER\" --force --if-exists \"\${$DB_NAME:-\$$DB_USER}\"" \
     || { echo "STOP: dropdb не выполнен (есть активные соединения?)" >&2; exit 75; }
docker compose exec -T "$DB_SERVICE" sh -c "createdb --maintenance-db=template1 -T template0 -U \"\$$DB_USER\" -O \"\$$DB_USER\" \"\${$DB_NAME:-\$$DB_USER}\"" \
    || { echo "STOP: createdb не выполнен" >&2; exit 75; }

# ── 7. восстановление: одна транзакция, любая ошибка откатывает всё ──
docker compose exec -T "$DB_SERVICE" \
    sh -c "pg_restore -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" --clean --if-exists --no-owner --no-acl --exit-on-error -1" < "$DUMP" \
    || { echo "STOP: pg_restore упал, БД пуста. Дамп: $DUMP" >&2; exit 76; }

# ── 8. проверка: в схеме есть объекты ──
TABLES="$(docker compose exec -T "$DB_SERVICE" sh -c "psql -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" -tAc \
     \"select count(*) from pg_tables where schemaname not in ('pg_catalog','information_schema')\"")"
[[ "${TABLES:-0}" -gt 0 ]] \
    || { echo "STOP: после восстановления в схеме 0 таблиц" >&2; exit 77; }
docker compose exec -T "$DB_SERVICE" sh -c "psql -U \"\$$DB_USER\" -d \"\${$DB_NAME:-\$$DB_USER}\" -q -c 'ANALYZE'" >/dev/null

printf '8.3\t%s\tok\trun_id=%s\tdump=%s\ttables=%s\tsrc_pg=%s\tdst_pg=%s\n' \
    "$(date -u +%FT%TZ)" "$RUN_ID" "$DUMP" "$TABLES" "${SRC_PG:-?}" "$DST_PG" >> "$JOURNAL"

echo "OK 8.3"
echo "  run_id : $RUN_ID"
echo "  dump   : $DUMP"
echo "  tables : $TABLES"
echo "  pg     : src=${SRC_PG:-?} -> dst=$DST_PG"
echo "  next   : 8.4 (поднять образ, зафиксированный до миграции)"
)
```

**Ожидаемый результат:** Структура и данные СУБД возвращены к состоянию до миграции без конфликтов таблиц.

### 8.4. Запуск предыдущей версии

**Место выполнения:** целевой сервер, Bash.

*(Восстановление образов выполняется из локального архива, созданного на шаге 3.3.)*

```bash
(
set -Eeuo pipefail
trap 'rc=$?; echo "FAIL 8.4.B rc=$rc line=$LINENO" >&2' ERR

cd -- "⚠️**<target.project_dir>**"

ROLLBACK_IMAGE_ARCHIVE="⚠️**<journal.rollback_dir>**/images_rollback.tar"
[[ -s "$ROLLBACK_IMAGE_ARCHIVE" && -s "${ROLLBACK_IMAGE_ARCHIVE}.images" ]] \
    || { echo "STOP: отсутствует архив образов отката $ROLLBACK_IMAGE_ARCHIVE или список ${ROLLBACK_IMAGE_ARCHIVE}.images" >&2; exit 24; }

docker load -i "$ROLLBACK_IMAGE_ARCHIVE"

mapfile -t EXPECTED_IMAGES < "${ROLLBACK_IMAGE_ARCHIVE}.images"
((${#EXPECTED_IMAGES[@]} > 0)) \
    || { echo "STOP: список образов отката ${ROLLBACK_IMAGE_ARCHIVE}.images пуст" >&2; exit 22; }

for image in "${EXPECTED_IMAGES[@]}"; do
    [[ -n "$image" ]] || continue
    docker image inspect "$image" >/dev/null 2>&1 \
        || { echo "STOP: после загрузки отсутствует образ отката '$image'" >&2; exit 27; }
done

docker compose up -d --no-build
)
```

**Проверка и восстановление источников записи (для всех вариантов)**

**Место 1 (целевой сервер):**

```bash
cd ⚠️**<target.project_dir>**

# Проверка успешного старта всех контейнеров
docker compose ps
docker compose logs --tail=50 ⚠️**<application.service>**
```

Запустите внешние источники записи на **целевом** сервере (`worker`, `cron`, `systemd-таймеры`), которые были остановлены на шаге 3.0.

**Место 2 (исходный сервер — выполняется также сразу после шага 8.1 при `migration.mode = initial`):**

Если на шаге 5.1 выполнялась блокировка изменения данных на исходном сервере, верните весь стек исходного сервера в рабочее состояние согласно выбранному `migration.config:consistency.capture_method`:

- **При `capture_method = stop_writers` (Вариант А шага 5.1):**

```bash
cd ⚠️**<source.project_dir>**
# Запуск ВСЕХ остановленных сервисов Compose-стека.
# Если контейнеры на источнике были удалены (docker compose down), команда fallback поднимет их заново.
docker compose start || docker compose up -d
docker compose ps
```

После старта контейнеров включите внешние источники записи (`cron`, `systemd-таймеры`), остановленные на шаге 5.1.

- **При `capture_method = coordinated` (Вариант Б шага 5.1):**

```bash
cd ⚠️**<source.project_dir>**
# Гарантируем, что контейнер application работает до вызова exec (защита от остановки в период между 5.1 и 8.4)
docker compose start ⚠️**<application.service>** || docker compose up -d ⚠️**<application.service>**
docker compose exec -T ⚠️**<application.service>** python manage.py set_maintenance_mode off
```

После отключения режима обслуживания запустите остановленные в 5.1.Б.1 фоновые воркеры и внешние источники записи (`cron`, `systemd`-таймеры).

**Ожидаемый результат:** Предыдущая версия приложения на целевом сервере и все сервисы исходного сервера запущены, обрабатывают запросы, фоновые задачи активны.