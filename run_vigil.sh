#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# VIGIL — 24/7 Monitoring Launcher
# ═══════════════════════════════════════════════════════════════
#
# Usage:
#   ./run_vigil.sh          — Start VIGIL in foreground
#   ./run_vigil.sh bg       — Start VIGIL in background (survives terminal close)
#   ./run_vigil.sh stop     — Stop background VIGIL
#   ./run_vigil.sh status   — Check if VIGIL is running
#   ./run_vigil.sh logs     — Tail the log file
#
# Requirements:
#   pip install httpx python-dotenv
#   .env file with API keys configured
#
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/data/vigil.pid"
LOG_FILE="$SCRIPT_DIR/data/vigil.log"

# Ensure data directory exists
mkdir -p "$SCRIPT_DIR/data"

case "${1:-fg}" in
    bg|background)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "VIGIL is already running (PID: $(cat "$PID_FILE"))"
            exit 1
        fi

        echo "Starting VIGIL in background..."
        cd "$SCRIPT_DIR/src"
        nohup python3 -u vigil.py --scan-once >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "VIGIL started (PID: $(cat "$PID_FILE"))"
        echo "Logs: tail -f $LOG_FILE"
        ;;

    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "Stopping VIGIL (PID: $PID)..."
                kill "$PID"
                rm -f "$PID_FILE"
                echo "VIGIL stopped."
            else
                echo "VIGIL process not found. Cleaning up PID file."
                rm -f "$PID_FILE"
            fi
        else
            echo "VIGIL is not running (no PID file)."
        fi
        ;;

    status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "VIGIL is running (PID: $(cat "$PID_FILE"))"
        else
            echo "VIGIL is not running."
        fi
        ;;

    logs)
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "No log file found yet."
        fi
        ;;

    fg|foreground|"")
        echo "═══════════════════════════════════════════"
        echo "  VIGIL — Trust Intelligence Engine"
        echo "  Press Ctrl+C to stop"
        echo "═══════════════════════════════════════════"
        cd "$SCRIPT_DIR/src"
        python3 -u vigil.py
        ;;

    *)
        echo "Usage: $0 {bg|stop|status|logs|fg}"
        exit 1
        ;;
esac
