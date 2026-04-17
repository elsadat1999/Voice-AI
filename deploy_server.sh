#!/bin/bash
# deploy_server.sh - Automated deployment for Linux Server

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_RESET='\033[0m'

print_info() { echo -e "${COLOR_BLUE}INFO: $1${COLOR_RESET}"; }
print_success() { echo -e "${COLOR_GREEN}SUCCESS: $1${COLOR_RESET}"; }

# Guard: Ensure we are on Linux (the deployment target)
if [ "$(uname)" != "Linux" ]; then
    echo -e "${COLOR_RED}ERROR: This script is intended for the REMOTE LINUX SERVER, not your local Mac.${COLOR_RESET}"
    echo "Please rsync the files to the server and run this script there via SSH."
    exit 1
fi

# 1. Ensure preflight checks pass (Install Docker/Compose)
print_info "Running preflight checks and installing dependencies..."
chmod +x preflight.sh install.sh
./preflight.sh --apply-fixes

# 2. Detect Public IP
print_info "Detecting Public IP..."
# Try curl first, then fall back to hostname
PUBLIC_IP=$(curl -s ifconfig.me || curl -s icanhazip.com || hostname -I | awk '{print $1}')
if [ -z "$PUBLIC_IP" ]; then
    echo -e "${COLOR_RED}ERROR: Could not detect Public IP.${COLOR_RESET}"
    exit 1
fi
print_success "Detected IP: $PUBLIC_IP"

# 3. Prepare .env
if [ ! -f .env ]; then
    cp .env.example .env
fi

# Update IP-related variables in .env (using GNU sed syntax for Linux)
sed -i "s|^EXTERNAL_MEDIA_ADVERTISE_HOST=.*|EXTERNAL_MEDIA_ADVERTISE_HOST=$PUBLIC_IP|" .env
# Also add it if it doesn't exist
if ! grep -q "EXTERNAL_MEDIA_ADVERTISE_HOST" .env; then
    echo "EXTERNAL_MEDIA_ADVERTISE_HOST=$PUBLIC_IP" >> .env
fi

# 4. Start Services
print_info "Starting containers..."
docker compose up -d

# 5. Post-launch FreePBX Config
print_info "Waiting for FreePBX to initialize (30s)..."
sleep 30

print_info "Configuring FreePBX Signaling/Media IP..."
docker exec freepbx mysql -u root -D asterisk -e "update kvstore_Sipsettings set val='$PUBLIC_IP' where \`key\`='externip';"
docker exec freepbx mysql -u root -D asterisk -e "update kvstore_Sipsettings set val='public' where \`key\`='nat.mode';"
docker exec freepbx fwconsole reload

print_success "Deployment Complete!"
print_info "Zoiper Connection: $PUBLIC_IP"
print_info "Admin UI: http://$PUBLIC_IP:3003"
print_info "FreePBX: http://$PUBLIC_IP:8080"
