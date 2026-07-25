# Migración a PostgreSQL

Guía para migrar de SQLite a PostgreSQL en producción.

## Por qué PostgreSQL

| Característica | SQLite | PostgreSQL |
|---|---|---|
| Concurrencia | 1 escritor a la vez | Múltiples lectores/escritores |
| Rendimiento | OK para desarrollo | Excelente en producción |
| Backup en caliente | Difícil | `pg_dump` nativo |
| Escalabilidad | Local | Remoto, clustering |
| Transacciones | Básicas | ACID completo |

## Pasos para migrar

### 1. Instalar PostgreSQL

```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-client

# Docker (alternativa)
docker run -d --name sofia-postgres \
  -e POSTGRES_USER=sofia \
  -e POSTGRES_PASSWORD=tu_password \
  -e POSTGRES_DB=sofia_comercial \
  -p 5432:5432 \
  postgres:16-alpine
```

### 2. Crear base de datos y usuario

```sql
CREATE USER sofia WITH PASSWORD 'tu_password';
CREATE DATABASE sofia_comercial OWNER sofia;
GRANT ALL PRIVILEGES ON DATABASE sofia_comercial TO sofia;
```

### 3. Instalar driver PostgreSQL

```bash
pip install psycopg2-binary>=2.9,<3.0
# o
pip install asyncpg>=0.29,<1.0
```

Agregar a `requirements.txt`:
```
psycopg2-binary>=2.9,<3.0
```

### 4. Actualizar .env

```ini
DATABASE_URL=postgresql://sofia:tu_password@localhost:5432/sofia_comercial
```

### 5. Ejecutar la aplicación

Las tablas se crean automáticamente con `Base.metadata.create_all()`.

### 6. Migrar datos existentes (opcional)

Si tenés datos en SQLite que querés conservar:

```python
# Script de migración
import sqlite3
import psycopg2

# Conectar a SQLite
sqlite_conn = sqlite3.connect("health_advisor.db")
sqlite_cursor = sqlite_conn.cursor()

# Conectar a PostgreSQL
pg_conn = psycopg2.connect(
    host="localhost", database="sofia_comercial",
    user="sofia", password="tu_password"
)
pg_cursor = pg_conn.cursor()

# Migrar leads
sqlite_cursor.execute("SELECT * FROM leads")
leads = sqlite_cursor.fetchall()

for lead in leads:
    pg_cursor.execute(
        "INSERT INTO leads (...) VALUES (...)",
        lead
    )

pg_conn.commit()
sqlite_conn.close()
pg_conn.close()
```

## Cambios en docker-compose.yml

```yaml
services:
  sofia-bot:
    environment:
      - DATABASE_URL=postgresql://sofia:tu_password@postgres:5432/sofia_comercial
    depends_on:
      - postgres

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sofia
      POSTGRES_PASSWORD: tu_password
      POSTGRES_DB:sofia_comercial
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  pgdata:
```

## Verificar la migración

```bash
# Conectar y verificar tablas
psql -U sofia -d sofia_comercial -c "\dt"

# Contar registros
psql -U sofia -d sofia_comercial -c "SELECT count(*) FROM leads;"
```
