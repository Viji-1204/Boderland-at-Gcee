#!/usr/bin/env bash
# setup.sh - writes the .env file Round 2 needs (secrets, passwords, how phones
# reach it), then optionally starts the game with Docker.
#
#   ./setup.sh                                      asks: server with a domain, or laptop on Wi-Fi?
#   ./setup.sh --public borderland-gcee.online      server: real certificate for that domain
#   ./setup.sh --lan                                laptop: self-signed HTTPS on port 8443 (Wi-Fi IP detected)
#   ./setup.sh --public borderland-gcee.online --yes --start   no questions, then docker compose up
#
# Options:
#   --public DOMAIN        the domain whose DNS A record points at this machine
#   --lan [IP]             this computer's Wi-Fi address (detected when omitted)
#   --admin-user NAME      coordinator login (default: admin)
#   --admin-password PASS  coordinator password (asked for; generated with --yes)
#   --yes                  no questions: generate whatever isn't given
#   --force                replace an existing .env (a dated backup is kept)
#   --start                run `docker compose up -d --build` when done
#
# Re-running keeps JWT_SECRET and POSTGRES_PASSWORD from the old .env, so an
# existing database and logins keep working. The coordinator password in .env
# only creates the FIRST admin; after that, change it from the console.
# Never commit .env - it holds the passwords.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MODE="" DOMAIN="" LAN_IP="" ADMIN_USER="admin" ADMIN_PASSWORD="" YES=0 FORCE=0 START=0
ADMIN_GENERATED=0

say()  { printf '%s\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31mx %s\033[0m\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
interactive() { [ "$YES" -eq 0 ] && [ -t 0 ]; }
usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --public)  MODE=public; DOMAIN="${2:-}"; [ -n "$DOMAIN" ] || die "--public needs the domain, e.g. --public borderland-gcee.online"; shift 2 ;;
    --lan)     MODE=lan; if [ $# -gt 1 ] && [[ "$2" != --* ]]; then LAN_IP="$2"; shift 2; else shift; fi ;;
    --admin-user)     ADMIN_USER="${2:-}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="${2:-}"; shift 2 ;;
    --yes|-y)   YES=1; shift ;;
    --force|-f) FORCE=1; shift ;;
    --start)    START=1; shift ;;
    -h|--help)  usage ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# ---- helpers ------------------------------------------------------------------------

random_hex() {  # $1 = bytes -> 2*$1 hex chars
  if have openssl; then openssl rand -hex "$1"
  elif have python3; then python3 -c 'import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))' "$1"
  else head -c 512 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c $(($1 * 2)); echo; fi
}

random_password() {  # $1 = length; letters and digits only, so it is safe in URLs and .env
  head -c 2048 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c "$1"; echo
}

detect_lan_ip() {  # this computer's address on the Wi-Fi / LAN, or nothing
  local ip="" os; os=$(uname -s 2>/dev/null || echo unknown)
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)  # Windows (Git Bash): the adapter that has a default gateway
      ip=$(powershell.exe -NoProfile -Command '(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1).IPv4Address.IPAddress' 2>/dev/null | tr -d '\r\n' || true)
      [ -n "$ip" ] || ip=$(ipconfig 2>/dev/null | tr -d '\r' | awk -F': ' '/IPv4/ {print $2; exit}' || true) ;;
    Darwin)
      ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true) ;;
    *)
      if have ip; then ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' || true); fi
      if [ -z "$ip" ] && have hostname; then ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true); fi ;;
  esac
  printf '%s' "$ip"
  return 0
}

public_ip() { { have curl && curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null; } || true; }

resolve() {  # IPv4 addresses of $1, one per line (empty if none)
  if have getent; then getent ahostsv4 "$1" 2>/dev/null | awk '{print $1}' | sort -u
  elif have dig; then dig +short A "$1" 2>/dev/null
  elif have python3; then python3 -c 'import socket,sys; print("\n".join(sorted({r[4][0] for r in socket.getaddrinfo(sys.argv[1], 443, socket.AF_INET)})))' "$1" 2>/dev/null
  elif have nslookup; then nslookup "$1" 2>/dev/null | tr -d '\r' | awk '/^Address/ && !/#/ {print $2}'
  fi
  return 0
}

ask() {  # ask VAR "prompt" "default"  (non-interactive: the default)
  local __var=$1 prompt=$2 default=${3:-} reply=""
  if interactive; then read -r -p "$prompt${default:+ [$default]}: " reply || true; fi
  printf -v "$__var" '%s' "${reply:-$default}"
}

old_value() {  # value of $1 in the existing .env, unquoted
  if [ -f .env ]; then sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r' | sed "s/^'\(.*\)'$/\1/"; fi
  return 0
}

# ---- which way do phones reach the game? -----------------------------------------------

if [ -z "$MODE" ]; then
  interactive || die "Say how phones reach the game: --public DOMAIN or --lan [IP] (see --help)."
  say "How will phones reach the game?"
  say "  1) A server on the internet with a domain name (real certificate, no warnings)"
  say "  2) This laptop, phones on the same Wi-Fi (self-signed certificate, port 8443)"
  ask choice "Choose 1 or 2" "1"
  case "$choice" in 1) MODE=public ;; 2) MODE=lan ;; *) die "Please choose 1 or 2." ;; esac
fi

if [ "$MODE" = public ]; then
  [ -n "$DOMAIN" ] || ask DOMAIN "Domain name (without https://)" ""
  DOMAIN=$(printf '%s' "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr 'A-Z' 'a-z')
  [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || die "That doesn't look like a domain name: '$DOMAIN'"
else
  [ -n "$LAN_IP" ] || LAN_IP=$(detect_lan_ip)
  [ -n "$LAN_IP" ] || ask LAN_IP "This computer's Wi-Fi address (ipconfig / ifconfig)" ""
  [[ "$LAN_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "That doesn't look like an IPv4 address: '$LAN_IP'"
fi

# ---- coordinator login ---------------------------------------------------------------------

[[ "$ADMIN_USER" =~ ^[A-Za-z0-9._-]{2,32}$ ]] || die "Admin username: 2-32 letters, digits, . _ -"
if [ -z "$ADMIN_PASSWORD" ]; then
  if interactive; then
    say "Coordinator password for '$ADMIN_USER' (press Enter to have one generated)."
    read -r -s -p "Password: " ADMIN_PASSWORD || true; echo
    if [ -n "$ADMIN_PASSWORD" ]; then
      read -r -s -p "Again: " again || true; echo
      [ "$ADMIN_PASSWORD" = "$again" ] || die "The passwords don't match."
    fi
  fi
  if [ -z "$ADMIN_PASSWORD" ]; then ADMIN_PASSWORD=$(random_password 12); ADMIN_GENERATED=1; fi
fi
[ "$ADMIN_PASSWORD" != "admin123" ] || die "'admin123' is the default and the server refuses it."
[[ "$ADMIN_PASSWORD" != *"'"* ]] || die "Please don't use a single quote (') in the password."
if [ "$MODE" = public ] && [ ${#ADMIN_PASSWORD} -lt 8 ]; then die "On a public server the coordinator password needs at least 8 characters."; fi

# ---- secrets: keep the old ones when re-running, so the database and logins survive ------

JWT_SECRET=$(old_value JWT_SECRET)
PG_PASSWORD=$(old_value POSTGRES_PASSWORD)
KEPT=""
if [ ${#JWT_SECRET} -ge 32 ] && [[ "$JWT_SECRET" != *REPLACE* ]]; then KEPT="JWT_SECRET"; else JWT_SECRET=$(random_hex 32); fi
if [ -n "$PG_PASSWORD" ]; then KEPT="${KEPT:+$KEPT and }POSTGRES_PASSWORD"; else PG_PASSWORD=$(random_password 24); fi

# ---- an existing .env ------------------------------------------------------------------------

if [ -f .env ]; then
  if [ "$FORCE" -eq 0 ]; then
    if interactive; then
      ask reply ".env already exists. Replace it (a backup is kept)? [y/N]" "N"
      [[ "$reply" =~ ^[Yy] ]] || die "Kept the existing .env. Re-run with --force to replace it."
    else
      die ".env already exists. Re-run with --force to replace it (a backup is kept)."
    fi
  fi
  backup=".env.bak.$(date +%Y%m%d-%H%M%S)"
  cp .env "$backup"
  say "Old .env saved as $backup"
fi

# ---- write it ---------------------------------------------------------------------------------

umask 077
SITE_DOMAIN=""; [ "$MODE" = public ] && SITE_DOMAIN="$DOMAIN"
[ "$MODE" = lan ] || LAN_IP=""
cat > .env <<EOF
# Borderland @ GCEE - Round 2 - written by setup.sh on $(date '+%Y-%m-%d %H:%M').
# Never commit this file. To change something, edit it and run: docker compose up -d
# (or run ./setup.sh --force for a new one; the secrets below are kept).

# Signing key for logins (64 hex chars). Changing it logs every phone out.
JWT_SECRET=$JWT_SECRET
# Coordinator login. The password here creates the FIRST admin only; once the
# database exists, change it from the console instead.
ADMIN_USERNAME=$ADMIN_USER
ADMIN_PASSWORD='$ADMIN_PASSWORD'
# Database password. Do not change once the database exists.
POSTGRES_PASSWORD=$PG_PASSWORD

# production refuses placeholder secrets. SEED_DEMO=true adds the demo game to an
# empty database (dry runs only).
ENVIRONMENT=production
SEED_DEMO=false

# How phones reach the game over HTTPS:
#   public = Caddy with a real certificate for SITE_DOMAIN on ports 80/443
#   lan    = self-signed certificate on port 8443 for LAN_IP (same Wi-Fi)
COMPOSE_PROFILES=$MODE
SITE_DOMAIN=$SITE_DOMAIN
LAN_IP=$LAN_IP
# Plain-HTTP port, this machine only (default 8000); ROUND2_BIND=0.0.0.0 opens it.
# ROUND2_PORT=8000
# ROUND2_HTTPS_PORT=8443
EOF
chmod 600 .env 2>/dev/null || true

# ---- summary --------------------------------------------------------------------------------

say
say "Wrote .env${KEPT:+ (kept $KEPT from the old one)}"
say "  Coordinator login : $ADMIN_USER"
if [ "$ADMIN_GENERATED" -eq 1 ]; then
  say "  Password          : $ADMIN_PASSWORD   <- generated: save it somewhere safe"
else
  say "  Password          : (the one you typed)"
fi
if [ "$MODE" = public ]; then
  URL="https://$DOMAIN"
  say "  Mode              : public server, domain $DOMAIN (Caddy, ports 80 + 443)"
  ips=$(resolve "$DOMAIN"); mine=$(public_ip)
  if [ -z "$ips" ]; then
    warn "DNS: $DOMAIN does not resolve yet. Add an A record for @ -> ${mine:-the public IP of this server} at the registrar; Caddy keeps retrying until it does."
  elif [ -n "$mine" ] && ! grep -qx "$mine" <<<"$ips"; then
    warn "DNS: $DOMAIN points to $(tr '\n' ' ' <<<"$ips")but this server's public IP is $mine. Fix the A record or the certificate can't be issued."
  else
    say "  DNS               : $DOMAIN -> $(tr '\n' ' ' <<<"$ips")ok"
  fi
  say "  Firewall          : open TCP 80 and 443 to the internet (nothing else)."
else
  URL="https://$LAN_IP:8443"
  say "  Mode              : laptop on Wi-Fi, $LAN_IP (self-signed, port 8443)"
fi
say
say "Coordinator console : $URL/admin-app/"
say "Team phone app      : $URL/team-app/"

# ---- start ---------------------------------------------------------------------------------------

if [ "$START" -eq 0 ]; then
  say
  say "Start it with:  docker compose up -d --build"
  [ "$MODE" = public ] && say "Watch the certificate arrive:  docker compose logs -f caddy"
  exit 0
fi

DOCKER="docker"
if ! have docker; then
  if [ "$(uname -s)" = Linux ]; then
    reply=Y
    if interactive; then ask reply "Docker isn't installed. Install it now with get.docker.com? [Y/n]" "Y"; fi
    [[ "$reply" =~ ^[Yy] ]] || die "Install Docker, then run: docker compose up -d --build"
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "${USER:-$(id -un)}" || true
    say "(Log out and in again for 'docker' to work without sudo; using sudo for now.)"
  else
    die "Docker isn't installed. Install Docker Desktop, then run: docker compose up -d --build"
  fi
fi
if ! $DOCKER info >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null || [ -t 0 ]; then DOCKER="sudo docker"; fi
  $DOCKER info >/dev/null 2>&1 || die "Docker isn't running (start Docker Desktop / the docker service), then: docker compose up -d --build"
fi
say
say "Starting: $DOCKER compose up -d --build"
$DOCKER compose up -d --build
say
$DOCKER compose ps
say
say "Open $URL/admin-app/ and log in as '$ADMIN_USER'."
if [ "$MODE" = public ]; then
  say "Certificate progress:  $DOCKER compose logs -f caddy   (look for 'certificate obtained successfully')"
else
  say "Phones: accept the certificate warning once, or scan the 'open the team app' QR on the QR Codes page."
fi
