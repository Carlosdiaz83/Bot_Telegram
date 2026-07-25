# Backups — Sofía Comercial AI

Guía para realizar backups de la base de datos.

## SQLite (desarrollo)

### Backup manual

```bash
# Copiar el archivo de base de datos
cp health_advisor.db backups/health_advisor_$(date +%Y%m%d_%H%M%S).db
```

### Backup con sqlite3 CLI

```bash
sqlite3 health_advisor.db ".backup 'backups/health_advisor_$(date +%Y%m%d).db'"
```

### Script de backup automático

```bash
#!/bin/bash
# backup.sh — Ejecutar con cron o manualmente
BACKUP_DIR="./backups"
DB_FILE="./health_advisor.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/backup_$TIMESTAMP.db'"

# Mantener solo los últimos 7 backups
ls -t "$BACKUP_DIR"/backup_*.db | tail -n +8 | xargs rm -f 2>/dev/null

echo "Backup completado: backup_$TIMESTAMP.db"
```

### Cron job (Linux/Mac)

```bash
# Editar crontab
crontab -e

# Backup diario a las 3 AM
0 3 * * * /ruta/al/proyecto/backup.sh >> /ruta/al/proyecto/logs/backup.log 2>&1
```

## Docker

### Backup del volumen de datos

```bash
# Crear backup del directorio data/
docker run --rm \
  -v sofia-comercial-bot_data:/data \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/backup_$(date +%Y%m%d).tar.gz -C /data .
```

### Restaurar backup

```bash
# Detener el bot
docker compose down

# Restaurar datos
docker run --rm \
  -v sofia-comercial-bot_data:/data \
  -v $(pwd)/backups:/backups \
  alpine tar xzf /backups/backup_20260101.tar.gz -C /data

# Reiniciar
docker compose up -d
```

## PostgreSQL (producción)

### Backup con pg_dump

```bash
# Backup completo
pg_dump -U sofia -d sofia_comercial -F c -f backups/backup_$(date +%Y%m%d).dump

# Backup en SQL plano
pg_dump -U sofia -d sofia_comercial -f backups/backup_$(date +%Y%m%d).sql
```

### Restaurar con pg_restore

```bash
pg_restore -U sofia -d sofia_comercial -c backups/backup_20260101.dump
```

### Cron job para PostgreSQL

```bash
# Backup diario a las 3 AM
0 3 * * * pg_dump -U sofia -d sofia_comercial -F c -f /backups/backup_$(date +\%Y\%m\%d).dump
```

## Qué respaldar

| Componente | Ubicación | Frecuencia |
|---|---|---|
| Base de datos | `health_advisor.db` o PostgreSQL | Diario |
| Archivos `.env` | Raíz del proyecto | Manual (antes de cambios) |
| Knowledge base | `app/knowledge/` | Con cada deploy |
| Logs | `logs/` | Rotación automática |

## Verificar integridad

```bash
# SQLite: verificar integridad
sqlite3 health_advisor.db "PRAGMA integrity_check;"

# PostgreSQL: verificar
pg_dump -U sofia -d sofia_comercial | head -5
```
