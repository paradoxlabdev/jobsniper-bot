# Deployment Guide

## Wdrożenie na serwer

### 1. Przygotowanie serwera

```bash
# Zainstaluj Docker i Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Zainstaluj Docker Compose (jeśli nie ma)
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. Skopiuj projekt na serwer

```bash
# Na swoim komputerze
git clone https://github.com/paradoxlabdev/jobsniper-bot.git
cd jobsniper-bot

# Skopiuj na serwer (przez SCP lub git clone na serwerze)
scp -r . user@your-server:/opt/jobsniper/
# LUB na serwerze:
# git clone https://github.com/paradoxlabdev/jobsniper-bot.git
```

### 3. Konfiguracja na serwerze

```bash
# Na serwerze
cd /opt/jobsniper  # lub gdzie skopiowałeś projekt

# Skonfiguruj .env
cp .env.example .env
nano .env  # Dodaj swoje API keys

# Dodaj CV (jeśli masz)
mkdir -p data
# Skopiuj cv.pdf do data/
```

### 4. Uruchomienie

```bash
# Uruchom wszystkie serwisy
docker-compose up -d

# Sprawdź status
docker-compose ps

# Zobacz logi
docker-compose logs -f app
```

## Dostęp do Grafany i Prometheusa

### Opcja 1: Bezpośredni dostęp (proste, ale mniej bezpieczne)

**Porty są już otwarte w docker-compose.yml:**
- Grafana: `http://YOUR_SERVER_IP:3001` (admin/admin)
- Prometheus: `http://YOUR_SERVER_IP:9090`
- Health Check: `http://YOUR_SERVER_IP:8080/health`

**Otwórz porty w firewall:**
```bash
# UFW (Ubuntu)
sudo ufw allow 3001/tcp
sudo ufw allow 9090/tcp
sudo ufw allow 8080/tcp

# Firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-port=3001/tcp
sudo firewall-cmd --permanent --add-port=9090/tcp
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload
```

### Opcja 2: SSH Tunnel (najbezpieczniejsze)

**Zamiast otwierać porty, użyj SSH tunnel:**

```bash
# Na swoim komputerze
ssh -L 3001:localhost:3001 -L 9090:localhost:9090 -L 8080:localhost:8080 user@your-server

# Teraz możesz otworzyć w przeglądarce:
# Grafana: http://localhost:3001
# Prometheus: http://localhost:9090
# Health: http://localhost:8080/health
```

### Opcja 3: Reverse Proxy (Nginx) - zalecane dla produkcji

**1. Zainstaluj Nginx:**
```bash
sudo apt install nginx
```

**2. Utwórz konfigurację `/etc/nginx/sites-available/jobsniper`:**
```nginx
server {
    listen 80;
    server_name your-domain.com;  # lub IP

    # Grafana
    location /grafana/ {
        proxy_pass http://localhost:3001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Prometheus
    location /prometheus/ {
        proxy_pass http://localhost:9090/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Health Check
    location /health {
        proxy_pass http://localhost:8080/health;
    }
}
```

**3. Aktywuj konfigurację:**
```bash
sudo ln -s /etc/nginx/sites-available/jobsniper /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**4. Zmień porty w docker-compose.yml (opcjonalne - dla bezpieczeństwa):**
```yaml
grafana:
  ports:
    - "127.0.0.1:3001:3000"  # Tylko localhost

prometheus:
  ports:
    - "127.0.0.1:9090:9090"  # Tylko localhost
```

**5. Dostęp:**
- Grafana: `http://your-domain.com/grafana`
- Prometheus: `http://your-domain.com/prometheus`

## Bezpieczeństwo

### Zmień domyślne hasła Grafana

```bash
# Edytuj docker-compose.yml
nano docker-compose.yml

# Zmień:
environment:
  - GF_SECURITY_ADMIN_PASSWORD=twoje_silne_haslo

# Restart
docker-compose restart grafana
```

### Dodaj Basic Auth do Nginx (opcjonalne)

```bash
# Utwórz plik z hasłami
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin

# Dodaj do konfiguracji Nginx:
auth_basic "Restricted Access";
auth_basic_user_file /etc/nginx/.htpasswd;
```

## Sprawdzenie działania

```bash
# 1. Sprawdź czy wszystkie kontenery działają
docker-compose ps

# 2. Sprawdź health check
curl http://localhost:8080/health

# 3. Sprawdź Prometheus
curl http://localhost:9090/-/healthy

# 4. Sprawdź Grafana
curl http://localhost:3001/api/health

# 5. Zobacz logi
docker-compose logs -f
```

## Aktualizacja

```bash
# Zatrzymaj serwisy
docker-compose down

# Pobierz najnowszy kod
git pull

# Zbuduj ponownie (jeśli były zmiany w kodzie)
docker-compose build

# Uruchom ponownie
docker-compose up -d
```

## Uwagi

- **Porty**: Grafana (3001), Prometheus (9090), App (8080) są dostępne z zewnątrz
- **Baza danych i Redis**: Tylko localhost (bezpieczne)
- **Dane**: Wszystkie dane są w folderach `db_data/`, `redis_data/`, `grafana_data/`, `prometheus_data/`
- **Backup**: Regularnie kopiuj te foldery!

## Troubleshooting

```bash
# Sprawdź logi
docker-compose logs app
docker-compose logs grafana
docker-compose logs prometheus

# Restart serwisu
docker-compose restart grafana

# Sprawdź porty
sudo netstat -tulpn | grep -E '3001|9090|8080'

# Sprawdź firewall
sudo ufw status
```
