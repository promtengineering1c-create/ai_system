#!/usr/bin/env python3
"""L2: санити compose-рендера (ADR-011).

Post-L0 postgres и все app-сервисы получают DB_* из одного интерполяционного источника
(базовый .env  shell). Расхождение пар POSTGRES_* <-> DB_* в рендере — регрессия
compose-файла (правка маппинга у одного сервиса, возврат DB_* в env_file, кривая обвязка
нового сервиса), а не проблема .env: содержимое .env структурно согласовано по определению.

Вход: docker compose config --format json на stdin. Коды: 0 ok / 1 diverged / 2 render.
Self-test: tests/test_render_check.py.
"""
import json
import sys

PAIRS = [
    ("POSTGRES_DB", "DB_NAME"),
    ("POSTGRES_USER", "DB_USER"),
    ("POSTGRES_PASSWORD", "DB_PASSWORD"),
]
CONSUMERS = ["web", "worker", "migrate-job"]


def main() -> int:
    try:
        cfg = json.load(sys.stdin)
        pg = cfg["services"]["postgres"]["environment"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"render_check: unexpected compose render: {exc}", file=sys.stderr)
        return 2
    bad = []
    for svc in CONSUMERS:
        env = cfg["services"].get(svc, {}).get("environment", {})
        for p, a in PAIRS:
            if env.get(a) != pg.get(p):
                bad.append(f"mapping diverged in compose: postgres.{p} != {svc}.{a}")
    for line in bad:
        print(line, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())