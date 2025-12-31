# 🔧 Troubleshooting Guide

## Problem: Port already in use / Container conflict

### Rozwiązanie 1: Zatrzymaj stare kontenery

```bash
# Zatrzymaj wszystkie kontenery JobSniper
docker-compose down

# Sprawdź czy są stare kontenery
docker ps -a | grep jobsniper

# Usuń stare kontenery (jeśli są)
docker rm -f $(docker ps -a | grep jobsniper | awk '{print $1}')

# Sprawdź czy porty są wolne
sudo netstat -tulpn | grep -E '5433|6380|8080|9090|3001'
```

### Rozwiązanie 2: Zmień porty w docker-compose.yml

Jeśli port 5433 jest zajęty przez inny serwis, zmień porty:

```yaml
# W docker-compose.yml zmień:
db:
  ports:
    - "127.0.0.1:5434:5432"  # Zmień z 5433 na 5434

redis:
  ports:
    - "127.0.0.1:6381:6379"  # Zmień z 6380 na 6381
```

### Rozwiązanie 3: Usuń wszystkie kontenery i sieci

```bash
# Zatrzymaj wszystko
docker-compose down

# Usuń wszystkie kontenery JobSniper
docker ps -a --filter "name=jobsniper" -q | xargs docker rm -f

# Usuń sieć (jeśli istnieje)
docker network ls | grep jobsniper
docker network rm jobsniper_network 2>/dev/null || true

# Sprawdź czy porty są wolne
sudo lsof -i :5433
sudo lsof -i :6380
sudo lsof -i :8080
sudo lsof -i :9090
sudo lsof -i :3001

# Jeśli coś zajmuje porty, zabij proces:
sudo kill -9 <PID>
```

### Rozwiązanie 4: Pełny reset (jeśli nic nie pomaga)

```bash
# 1. Zatrzymaj wszystko
docker-compose down -v

# 2. Usuń wszystkie kontenery JobSniper
docker container prune -f --filter "name=jobsniper"

# 3. Usuń sieci
docker network prune -f

# 4. Sprawdź porty
sudo ss -tulpn | grep -E '5433|6380|8080|9090|3001'

# 5. Uruchom ponownie
docker-compose up -d
```

## Inne częste problemy

### Problem: Cannot connect to database

```bash
# Sprawdź czy baza działa
docker-compose ps db

# Zobacz logi
docker-compose logs db

# Restart bazy
docker-compose restart db
```

### Problem: Grafana nie ładuje się

```bash
# Sprawdź logi
docker-compose logs grafana

# Sprawdź czy port 3001 jest wolny
sudo lsof -i :3001

# Restart Grafana
docker-compose restart grafana
```

### Problem: Prometheus nie zbiera metryk

```bash
# Sprawdź logi
docker-compose logs prometheus
docker-compose logs prometheus_exporter

# Sprawdź czy exporter działa
curl http://localhost:9092/metrics

# Sprawdź w Prometheus UI
curl http://localhost:9090/api/v1/targets
```

### Problem: Aplikacja nie startuje

```bash
# Zobacz logi
docker-compose logs -f app

# Sprawdź .env
cat .env | grep -v PASSWORD

# Sprawdź health
curl http://localhost:8080/health
```

## Szybkie komendy diagnostyczne

```bash
# Status wszystkich kontenerów
docker-compose ps

# Logi wszystkich serwisów
docker-compose logs --tail=50

# Restart wszystkich serwisów
docker-compose restart

# Sprawdź użycie zasobów
docker stats

# Sprawdź wolne miejsce
df -h
docker system df
```
