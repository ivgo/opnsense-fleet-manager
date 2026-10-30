# pgBackRest PostgreSQL Backup

Резервное копирование PostgreSQL с использованием pgBackRest 2.54.2.

## Архитектура

- **postgres контейнер**: PostgreSQL 16 + pgBackRest CLI
- **worker контейнер**: Инициирует backup через `docker exec`
- **Хранилище**: локальная файловая система (posix)

## Конфигурация

### postgres.Dockerfile
- База: `postgres:16-bookworm` (Debian)
- pgBackRest собирается из исходников (release/2.54.2)
- Зависимости для сборки удаляются после компиляции

### pgbackrest.conf
```ini
[global]
repo1-path=/var/lib/pgbackrest
spool-path=/var/spool/pgbackrest
repo1-retention-full=2
repo1-retention-diff=7
repo1-type=posix
compress-type=gz
compress-level=3

[ofme]
pg1-path=/var/lib/postgresql/data
pg1-port=5432
pg1-user=ofme
pg1-database=ofme
```

### docker-compose.yml
PostgreSQL service:
- `archive_mode=on`
- `archive_command=pgbackrest --stanza=ofme archive-push %p`

Worker service:
- Подключен к `/var/run/docker.sock` для выполнения команд в postgres контейнере
- Запускается от root для доступа к docker socket

## Использование

### Инициализация (после первого запуска)
```bash
# Создать stanza
docker compose exec postgres pgbackrest --stanza=ofme stanza-create

# Исправить права на archive директорию
docker compose exec -u root postgres chown -R postgres:postgres /var/lib/pgbackrest/archive
```

### Запуск backup
```bash
# Полный backup
docker compose exec postgres pgbackrest --stanza=ofme --type=full backup

# Инкрементальный backup
docker compose exec postgres pgbackrest --stanza=ofme --type=incr backup

# Через worker (из Python)
from app.workers.pgbackrest import _run_backup
result = _run_backup("full")  # или "diff", "incr"
```

### Проверка статуса
```bash
docker compose exec postgres pgbackrest --stanza=ofme info
```

## Worker Integration

Python worker вызывает pgBackRest через docker exec:

```python
def _run_pgbackrest(*args: str) -> dict[str, Any]:
    cmd = ["docker", "exec", "-u", "root", "ofme-postgres-1", "pgbackrest", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    ...
```

## Retention Policy

- **2 полных backup** сохраняются
- **7 дифференциальных backup** между полными
- Старые backup удаляются автоматически после каждого backup

## Восстановление

```bash
# Stop PostgreSQL
docker compose stop postgres

# Восстановить на момент полного backup
docker compose run --rm postgres pgbackrest --stanza=ofme --type=full restore

# Или на момент инкрементального backup
docker compose run --rm postgres pgbackrest --stanza=ofme --set=20261030-074917F_20261030-074957I restore

# Запустить PostgreSQL
docker compose up -d postgres
```

## Troubleshooting

### Archive permission errors
```bash
docker compose exec -u root postgres chown -R postgres:postgres /var/lib/pgbackrest/archive
```

### Проверка WAL архивирования
```bash
docker compose exec postgres ls -la /var/lib/pgbackrest/archive/ofme/
docker compose exec postgres pgbackrest --stanza=ofme info
```

### Backup без проверки archive (для тестирования)
```bash
docker compose exec postgres pgbackrest --stanza=ofme --type=full --no-archive-check backup
```
