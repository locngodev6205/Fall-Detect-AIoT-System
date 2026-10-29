#!/usr/bin/env bash
# AnNha launcher for macOS/Linux. Docker manages all application processes.
set -u

ANNHA_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1

compose() {
  docker compose --project-directory "$ANNHA_DIR" \
    --env-file "$ANNHA_DIR/.env" -f "$ANNHA_DIR/compose.yaml" "$@"
}

prepare() {
  command -v docker >/dev/null 2>&1 || { echo "[LOI] Chua cai Docker. Hay cai Docker Desktop hoac Docker Engine." >&2; return 1; }
  docker compose version >/dev/null 2>&1 || { echo "[LOI] Can Docker Compose v2 tro len (docker compose)." >&2; return 1; }
  docker info >/dev/null 2>&1 || { echo "[LOI] Docker chua chay. Hay mo Docker Desktop hoac khoi dong Docker Engine." >&2; return 1; }
  if [[ ! -f "$ANNHA_DIR/.env" ]]; then
    cp "$ANNHA_DIR/.env.example" "$ANNHA_DIR/.env" || return 1
    echo "[INFO] Da tao .env tu .env.example. File .env hien co se khong bi ghi de."
  fi
  compose config --quiet || return 1
}

service_url() {
  local address
  address="$(compose port "$1" "$2" 2>/dev/null)" || return 1
  [[ -n "$address" ]] || return 1
  printf 'http://%s\n' "$address"
}

show_urls() {
  local url
  if url="$(service_url frontend 80)"; then printf '\nUng dung AnNha: %s\n' "$url"; fi
  if url="$(service_url mailpit 8025)"; then printf 'Hop thu xac minh: %s\n' "$url"; fi
}

open_page() {
  local url
  url="$(service_url "$1" "$2")" || { echo "[LOI] Dich vu chua chay. Hay khoi dong ung dung truoc." >&2; return 1; }
  echo "$url"
  if [[ "$(uname -s)" == Darwin ]] && command -v open >/dev/null 2>&1; then
    open "$url"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url"
  else
    echo "Mo dia chi tren bang trinh duyet cua ban."
  fi
}

usage() {
  cat <<'HELP'
AnNha - Camera giam sat gia dinh

  ./run.sh                 Menu tuong tac
  ./run.sh up              Build va chay toan bo, cho dich vu san sang
  ./run.sh start           Chay nhanh, khong ep build lai image da co
  ./run.sh stop            Dung container, giu nguyen du lieu
  ./run.sh recreate        Tao lai container tu image hien co, nap lai .env
  ./run.sh status          Xem trang thai container
  ./run.sh logs [service]  Theo doi log; Ctrl+C de thoat, khong dung container
  ./run.sh web             Mo ung dung
  ./run.sh mail            Mo hop thu xac minh
  ./run.sh check           Kiem tra Docker va cau hinh Compose
  ./run.sh help            Huong dan

Service log: backend, frontend, mqtt, mailpit; bo trong de xem tat ca.
Cong mac dinh: web 8188, hop thu 8125. Doi trong .env truoc khi chay.
Script khong xoa volume, seed/reset du lieu, hoac chay AI tren may host.
HELP
}

run_action() {
  local action="${1:-help}" service="${2:-}"
  case "$action" in
    help|-h|--help) usage; return 0 ;;
    up|start|stop|recreate|status|logs|web|mail|check) ;;
    *) echo "[LOI] Lenh khong hop le. Dung ./run.sh help." >&2; return 2 ;;
  esac
  if [[ "$action" == logs && -n "$service" ]]; then
    case "$service" in
      backend|frontend|mqtt|mailpit) ;;
      *) echo "[LOI] Service log: backend, frontend, mqtt hoac mailpit." >&2; return 2 ;;
    esac
  fi
  prepare || return 1
  case "$action" in
    up) compose up --build -d --wait --wait-timeout 120 || return 1; show_urls ;;
    start) compose up -d --wait --wait-timeout 120 || return 1; show_urls ;;
    stop) compose stop ;;
    recreate) compose up -d --force-recreate --wait --wait-timeout 120 || return 1; show_urls ;;
    status) compose ps --all ;;
    logs)
      if [[ -n "$service" ]]; then compose logs --tail 100 --follow "$service"
      else compose logs --tail 100 --follow; fi ;;
    web) open_page frontend 80 ;;
    mail) open_page mailpit 8025 ;;
    check) echo "[OK] Docker dang chay; cau hinh Compose hop le." ;;
  esac
}

menu() {
  local choice action
  while true; do
    cat <<'MENU'

====================================================
  ANNHA - CAMERA GIAM SAT GIA DINH
====================================================
  [1] Build va chay toan bo (mac dinh)
  [2] Chay nhanh bang image hien co
  [3] Dung ung dung (giu du lieu)
  [4] Tao lai container / nap lai .env (giu du lieu)
  [5] Xem trang thai
  [6] Xem log (Ctrl+C de thoat)
  [7] Mo ung dung tren trinh duyet
  [8] Mo hop thu xac minh
  [9] Kiem tra Docker / Compose
  [0] Thoat
MENU
    read -r -p "Chon [0-9] (mac dinh: 1): " choice || return 0
    case "${choice:-1}" in
      1) action=up ;; 2) action=start ;; 3) action=stop ;; 4) action=recreate ;;
      5) action=status ;; 6) action=logs ;; 7) action=web ;; 8) action=mail ;;
      9) action=check ;; 0) return 0 ;;
      *) echo "Lua chon khong hop le."; continue ;;
    esac
    run_action "$action" || echo "[LOI] Thao tac chua hoan tat. Xem thong bao phia tren." >&2
    read -r -p "Nhan Enter de quay lai menu..." choice || return 0
  done
}

if [[ $# -gt 0 ]]; then
  run_action "$@"
else
  if [[ ! -t 0 ]]; then usage; exit 0; fi
  menu
fi
