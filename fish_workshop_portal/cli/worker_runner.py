"""
Инфраструктурный исполнитель фоновых процессов (Этап 7, ADR-004):
- цикл опроса очереди BackgroundTask в PostgreSQL (SELECT FOR UPDATE SKIP LOCKED
  по locked_until с фильтрацией поддерживаемых task_type и schema_version);
- выполнение внешних I/O-вызовов вне транзакции БД, close_old_connections() между итерациями, экспоненциальный retry;
- координация поллинга /exchange/1c_to_web/ между репликами через pg_try_advisory_lock и обновление /tmp/worker_heartbeat.
"""