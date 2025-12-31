# 🔧 Troubleshooting Guide

## Problem: Port already in use / Container conflict

### Solution 1: Stop old containers

```bash
# Stop all JobSniper containers
docker-compose down
 
# Check for old containers
docker ps -a | grep jobsniper

# Remove old containers (if any)
docker rm -f $(docker ps -a | grep jobsniper | awk '{print $1}')

# Check if ports are free
sudo netstat -tulpn | grep -E '5433|6380|8080|9090|3001'
```

### Solution 2: Change ports in docker-compose.yml

If port 5433 is occupied by another service, change the ports:

```yaml
# In docker-compose.yml change:
db:
  ports:
    - "127.0.0.1:5434:5432"  # Change from 5433 to 5434

redis:
  ports:
    - "127.0.0.1:6381:6379"  # Change from 6380 to 6381
```

### Solution 3: Remove all containers and networks

```bash
# Stop everything
docker-compose down

# Remove all JobSniper containers
docker ps -a --filter "name=jobsniper" -q | xargs docker rm -f

# Remove network (if exists)
docker network ls | grep jobsniper
docker network rm jobsniper_network 2>/dev/null || true

# Check if ports are free
sudo lsof -i :5433
sudo lsof -i :6380
sudo lsof -i :8080
sudo lsof -i :9090
sudo lsof -i :3001

# If something is using the ports, kill the process:
sudo kill -9 <PID>
```

### Solution 4: Full reset (if nothing else works)

```bash
# 1. Stop everything
docker-compose down -v

# 2. Remove all JobSniper containers
docker container prune -f --filter "name=jobsniper"

# 3. Remove networks
docker network prune -f

# 4. Check ports
sudo ss -tulpn | grep -E '5433|6380|8080|9090|3001'

# 5. Start again
docker-compose up -d
```

## Other common problems

### Problem: Cannot connect to database

```bash
# Check if database is running
docker-compose ps db

# View logs
docker-compose logs db

# Restart database
docker-compose restart db
```

### Problem: Grafana not loading

```bash
# Check logs
docker-compose logs grafana

# Check if port 3001 is free
sudo lsof -i :3001

# Restart Grafana
docker-compose restart grafana
```

### Problem: Prometheus not collecting metrics

```bash
# Check logs
docker-compose logs prometheus
docker-compose logs prometheus_exporter

# Check if exporter is running
curl http://localhost:9092/metrics

# Check in Prometheus UI
curl http://localhost:9090/api/v1/targets
```

### Problem: Application not starting

```bash
# View logs
docker-compose logs -f app

# Check .env
cat .env | grep -v PASSWORD

# Check health
curl http://localhost:8080/health
```

### Problem: Docker build error - "can't stat '/path/to/db_data'"

This error occurs when Docker's legacy builder tries to check data directories during build, even though they're in `.dockerignore`.

**Solution 1: Use DOCKER_BUILDKIT (recommended)**

```bash
cd ~/jobsniper-bot
DOCKER_BUILDKIT=1 docker-compose build --no-cache app
docker-compose up -d
```

**Solution 2: Temporarily move data directory before build**

```bash
cd ~/jobsniper-bot
sudo mv db_data db_data_backup
docker-compose build --no-cache app
sudo mv db_data_backup db_data
docker-compose up -d
```

**Solution 3: Change directory ownership**

```bash
cd ~/jobsniper-bot
sudo chown -R ubuntu:ubuntu db_data
docker-compose build --no-cache app
docker-compose up -d
```

## Quick diagnostic commands

```bash
# Status of all containers
docker-compose ps

# Logs of all services
docker-compose logs --tail=50

# Restart all services
docker-compose restart

# Check resource usage
docker stats

# Check free space
df -h
docker system df
``


