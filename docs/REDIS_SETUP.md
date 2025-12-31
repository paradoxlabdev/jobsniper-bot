# 🔧 Redis Configuration Guide

## Quick Setup

Dodaj te linie do swojego pliku `.env`:

```bash
# =============================================================================
# REDIS CACHE CONFIGURATION
# =============================================================================
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_ENABLED=true
```

---

## Pełna Konfiguracja .env

Jeśli chcesz zobaczyć pełną konfigurację, oto wszystkie zmienne środowiskowe:

```bash
# =============================================================================
# DATABASE
# =============================================================================
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=jobsniper
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://postgres:your_password@db:5432/jobsniper

# =============================================================================
# REDIS CACHE (NOWE!)
# =============================================================================
REDIS_HOST=redis          # Hostname Redis w docker-compose
REDIS_PORT=6379           # Domyślny port Redis
REDIS_DB=0                # Numer bazy danych (0-15)
REDIS_ENABLED=true        # Włącz/wyłącz Redis

# =============================================================================
# OPENAI
# =============================================================================
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini

# =============================================================================
# TELEGRAM
# =============================================================================
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# =============================================================================
# JUST JOIN IT
# =============================================================================
JJIT_API_URL=https://api.justjoin.it/v2/user-panel/offers/by-cursor
JJIT_CATEGORY_IDS=5
JJIT_FETCH_INTERVAL=300
JJIT_SEARCH_KEYWORDS=Python,Remote
JJIT_LOCATIONS=

# =============================================================================
# MATCHER
# =============================================================================
MATCH_THRESHOLD=80
CV_PATH=/app/data/cv.pdf

# =============================================================================
# APPLICATION
# =============================================================================
LOG_LEVEL=INFO
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_FACTOR=2
```

---

## Domyślne Wartości

**Nie musisz dodawać tych zmiennych do .env** - mają wartości domyślne w `core/config.py`:

```python
redis_host: str = Field(default="redis")
redis_port: int = Field(default=6379)
redis_db: int = Field(default=0)
redis_enabled: bool = Field(default=True)
```

---

## Scenariusze Użycia

### 1. ✅ Domyślna Konfiguracja (Zalecane)

**Nie dodawaj niczego do .env** - użyje domyślnych wartości:
- Redis włączony
- Host: `redis` (z docker-compose)
- Port: 6379
- Database: 0

### 2. 🔧 Niestandardowa Konfiguracja

Dodaj do `.env` tylko jeśli chcesz zmienić domyślne:

```bash
# Przykład: Inny port
REDIS_PORT=6380

# Przykład: Inna baza danych
REDIS_DB=1
```

### 3. ❌ Wyłączenie Redis

Jeśli z jakiegoś powodu chcesz wyłączyć Redis:

```bash
REDIS_ENABLED=false
```

Bot będzie działał normalnie z cache tylko w pamięci RAM.

### 4. 🌐 Zewnętrzny Redis

Jeśli masz zewnętrzny serwer Redis:

```bash
REDIS_HOST=redis.example.com
REDIS_PORT=6379
REDIS_DB=0
```

---

## Weryfikacja Konfiguracji

### 1. Sprawdź czy Redis działa:

```bash
docker-compose ps redis
```

Powinno pokazać:
```
NAME                IMAGE           STATUS
jobsniper_redis    redis:7-alpine   Up
```

### 2. Przetestuj połączenie:

```bash
docker-compose exec redis redis-cli ping
```

Powinno odpowiedzieć: `PONG`

### 3. Sprawdź cache w Redis:

```bash
# Podłącz się do Redis
docker-compose exec redis redis-cli

# Zobacz ile kluczy cache
127.0.0.1:6379> KEYS ai_cache:*

# Zobacz przykładowy klucz
127.0.0.1:6379> GET ai_cache:abc123...

# Sprawdź TTL (czas do wygaśnięcia)
127.0.0.1:6379> TTL ai_cache:abc123...
(integer) 86234    # ~24h w sekundach
```

### 4. Sprawdź logi aplikacji:

```bash
docker-compose logs -f jobsniper_app | grep -i redis
```

Powinno pokazać:
```
Redis cache connected successfully
```

Lub jeśli Redis niedostępny:
```
Failed to connect to Redis: ... Using in-memory cache only.
```

---

## Migracja ze Starej Wersji

### Jeśli aktualizujesz z wersji bez Redis:

**Opcja 1: Automatyczna (Zalecane)**

Nic nie rób - Redis użyje domyślnych wartości automatycznie.

```bash
docker-compose down
docker-compose build
docker-compose up -d
```

**Opcja 2: Jawna Konfiguracja**

Dodaj do `.env` przed uruchomieniem:

```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_ENABLED=true
```

Potem:

```bash
docker-compose down
docker-compose build
docker-compose up -d
```

---

## Troubleshooting

### Problem: "Failed to connect to Redis"

**Przyczyny:**
1. Redis nie uruchomiony
2. Zły hostname/port
3. Redis nie gotowy (healthcheck)

**Rozwiązanie:**

```bash
# 1. Sprawdź status
docker-compose ps redis

# 2. Sprawdź logi Redis
docker-compose logs redis

# 3. Zrestartuj Redis
docker-compose restart redis

# 4. Sprawdź healthcheck
docker-compose ps
# Redis powinien być "healthy" nie "starting"
```

### Problem: Cache nie działa

**Diagnoza:**

```bash
# Sprawdź czy klucze są tworzone
docker-compose exec redis redis-cli DBSIZE

# Jeśli (integer) 0, cache nie jest używany
```

**Rozwiązanie:**

```bash
# 1. Sprawdź logi aplikacji
docker-compose logs -f jobsniper_app | grep cache

# 2. Sprawdź czy REDIS_ENABLED=true
docker-compose exec jobsniper_app env | grep REDIS
```

### Problem: Wolne działanie po restarcie

**To normalne!** Cache jest pusty po restarcie, więc pierwsze analizy będą wolniejsze (wywołania OpenAI).

**Monitoruj:**

```bash
# Zobacz jak rośnie cache
watch -n 5 'docker-compose exec redis redis-cli DBSIZE'
```

Po kilku cyklach cache się zapełni i wszystko przyspieszy.

---

## Zaawansowana Konfiguracja

### Optymalizacja pamięci Redis

W `docker-compose.yml` Redis jest skonfigurowany z:

```yaml
command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

**Parametry:**
- `maxmemory 256mb` - maksymalna pamięć (zwiększ jeśli potrzebujesz więcej cache)
- `allkeys-lru` - usuwa najstarsze klucze gdy brakuje pamięci

**Zmiana limitu:**

Edytuj `docker-compose.yml`:

```yaml
# Dla większego cache (np. tysiące ofert)
command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru

# Dla mniejszego cache (oszczędność RAM)
command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
```

### Persystencja danych

Redis zapisuje dane do `./redis_data/`:

```bash
# Backup Redis
cp -r ./redis_data ./redis_data_backup

# Restore Redis
docker-compose down
rm -rf ./redis_data
cp -r ./redis_data_backup ./redis_data
docker-compose up -d
```

### Czyszczenie cache

```bash
# Wyczyść wszystkie cache AI
docker-compose exec redis redis-cli KEYS "ai_cache:*" | xargs docker-compose exec redis redis-cli DEL

# Wyczyść całą bazę Redis
docker-compose exec redis redis-cli FLUSHDB

# Wyczyść wszystkie bazy Redis (0-15)
docker-compose exec redis redis-cli FLUSHALL
```

---

## Monitoring Redis

### Statystyki w czasie rzeczywistym:

```bash
docker-compose exec redis redis-cli --stat
```

Pokaże:
```
------- data ------ --------------------- load -------------------- - child -
keys       mem      clients blocked requests            connections
42         1.2M     1       0       1234 (+0)           12
```

### Informacje o pamięci:

```bash
docker-compose exec redis redis-cli INFO memory
```

### Top kluczy (najwięcej miejsca):

```bash
docker-compose exec redis redis-cli --bigkeys
```

---

## Podsumowanie

### ✅ Minimalna Konfiguracja (Działa od razu)

**Nic nie dodawaj** - użyje domyślnych wartości

### ✅ Zalecana Konfiguracja (Dla przejrzystości)

Dodaj do `.env`:

```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_ENABLED=true
```

### ✅ Weryfikacja

```bash
# 1. Uruchom
docker-compose up -d

# 2. Sprawdź Redis
docker-compose exec redis redis-cli ping  # -> PONG

# 3. Sprawdź logi
docker-compose logs jobsniper_app | grep -i redis
# -> "Redis cache connected successfully"

# 4. Zobacz cache
docker-compose exec redis redis-cli DBSIZE
# Po kilku minutach powinno rosnąć
```

---

**Pytania?** Sprawdź logi:
```bash
docker-compose logs -f jobsniper_app
docker-compose logs -f redis
```
