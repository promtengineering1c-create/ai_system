"""
+Тонкая Django management-команда запуска worker-процесса (Этап 7, ADR-004):
+обрабатывает сигналы SIGTERM/SIGINT (в рамках stop_grace_period) и делегирует цикл исполнения в cli.worker_runner.
"""

