#!/usr/bin/env bash
# cc.sh — единственный санкционированный вход к docker compose (ADR-011).
# L1: снимает shell-export DB_*/POSTGRES_*; инвариант "креды БД только в базовом .env".
# L2: санити рендера (scripts/render_check.py) — гард против регрессий маппинга в compose-файле.
# L3: диагностика migrate-job — cli/preflight_migrate.py (выполняется в контейнере, не здесь).
# Teardown/диагностика (down/stop/kill/rm/logs/ps/top/images/version) идут в compose напрямую, до env-чеков и L2: иначе санкционированный teardown невозможен при битом .env (интерполяция ${VAR:?} абортит любой compose-вызов — свойство compose, не wrapper) и оператор уходит в raw docker в обход unset/preflight.
# Использование: scripts/cc.sh <docker compose args>   # напр.: scripts/cc.sh up -d

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

[ "$#" -ge 1 ] || { echo "usage: scripts/cc.sh <docker compose args>" >&2; exit 2; }

# --- L1: --env-file = второй источник интерполяции, обходит инвариант (ADR-011 п.2) ---
for arg in "$@"; do
  case "${arg}" in
    --env-file|--env-file=*)
      echo "cc.sh: ${arg} forbidden — interpolation source must be base .env only" >&2
      exit 1
      ;;
  esac
done

# --- L1: shell-override снимается — интерполяция обязана читать только базовый .env ---
unset DB_NAME DB_USER DB_PASSWORD DB_HOST
unset POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
unset COMPOSE_ENV_FILES COMPOSE_FILE

# --- Извлечение глобальных флагов compose (--profile, -f, -p) для консистентного config и определение подкоманды ---
GLOBAL_ARGS=()
SUBCMD=""
i=1
while [ "$i" -le "$#" ]; do
  arg="${!i}"
  case "${arg}" in
    -f|--file|-p|--project-name|--project-directory|--profile|--progress|--ansi)
      GLOBAL_ARGS+=("${arg}")
      i=$((i + 1))
      if [ "$i" -le "$#" ]; then
        GLOBAL_ARGS+=("${!i}")
      fi
      ;;
    -f=*|--file=*|-p=*|--project-name=*|--project-directory=*|--profile=*|--progress=*|--ansi=*)
      GLOBAL_ARGS+=("${arg}")
      ;;
    -*)
      GLOBAL_ARGS+=("${arg}")
      ;;
    *)
      SUBCMD="${arg}"
      break
      ;;
  esac
  i=$((i + 1))
done

# --- Teardown/диагностика и флаги без подкоманды (--version/--help): напрямую в compose до L1/L2 ---
case "${SUBCMD}" in
  ""|down|stop|kill|rm|logs|ps|top|images|version)
    exec docker compose "$@"
    ;;
esac

# --- APP_ENV: валидация символов, зеркало config/env.py (Path Traversal, ADR-008) ---
APP_ENV="${APP_ENV:?APP_ENV is required}"
[[ "${APP_ENV}" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "cc.sh: invalid APP_ENV '${APP_ENV}'" >&2; exit 1; }

# --- preflight: env-файлы существуют (compose long-form env_file, required:true) ---
[ -f .env ] || { echo "cc.sh: .env missing" >&2; exit 1; }
ENV_FILE=".env.${APP_ENV}"
[ -f "${ENV_FILE}" ] || { echo "cc.sh: ${ENV_FILE} missing" >&2; exit 1; }

# --- L1: запрет POSTGRES_* в базовом .env (compose маппит POSTGRES_* из DB_*) ---
if grep -qE '^[[:space:]]*(export[[:space:]]+)?POSTGRES_[A-Za-z0-9_]+=' .env; then
  echo "cc.sh: POSTGRES_* must not be defined in .env (use DB_NAME/DB_USER/DB_PASSWORD)" >&2
  exit 1
fi

# --- L1: запрет кредов БД в .env.${APP_ENV} (не-кредовые DB_* вроде DB_CONN_MAX_AGE разрешены) ---
if grep -qE '^[[:space:]]*(export[[:space:]]+)?(DB_(NAME|USER|PASSWORD|HOST)|POSTGRES_[A-Za-z0-9_]+)=' "${ENV_FILE}"; then
  echo "cc.sh: DB_NAME/DB_USER/DB_PASSWORD/DB_HOST and POSTGRES_* must live in base .env only (found in ${ENV_FILE})" >&2
  exit 1
fi

# --- Шорткат для эксплуатации: безопасный reload nginx (обертка над exec) ---
if [ "${SUBCMD}" = "reload-nginx" ]; then
    docker compose "${GLOBAL_ARGS[@]}" exec -T nginx nginx -t
    exec docker compose "${GLOBAL_ARGS[@]}" exec -T nginx nginx -s reload
fi

# --- P5 preflight: файловые bind-маунты (пропускаем для read-only команд диагностики) ---
case "${SUBCMD}" in
  config|exec) ;;
  *)
     [ -d data/nginx-dynamic ] || { echo "cc.sh: bind-mount directory missing: data/nginx-dynamic" >&2; exit 1; }
    for f in nginx/nginx.conf data/nginx-dynamic/.htpasswd data/nginx-dynamic/cloudflare-ips.conf certbot/cli.ini scripts/certbot_deploy_hook.sh; do
      [ -f "${f}" ] || { echo "cc.sh: bind-mount file missing: ${f}" >&2; exit 1; }
    done
    ;;
esac

# --- L2: оба консюмера в одном рендере; расхождение = регрессия compose-файла ---
case "${SUBCMD}" in
  exec) ;; # Пропускаем L2 для exec: контейнер уже запущен, конфиг проверен при старте
  *) docker compose "${GLOBAL_ARGS[@]}" config --format json | python3 scripts/render_check.py ;;
esac

exec docker compose "$@"