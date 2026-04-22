#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "== Guard Scheduler =="
echo "Project: $PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3 first."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if [ ! -f ".venv/.deps_installed" ] || [ requirements.txt -nt ".venv/.deps_installed" ]; then
  echo "Installing dependencies..."
  python3 -m pip install --upgrade pip
  python3 -m pip install -r requirements.txt
  touch .venv/.deps_installed
fi

echo "Starting web app at http://localhost:8501"
export STREAMLIT_CONFIG_DIR="$PROJECT_DIR/.streamlit"

PORT=8501
while lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do
  PORT=$((PORT + 1))
done

if [ "$PORT" -ne 8501 ]; then
  echo "Port 8501 is busy. Switching to port $PORT."
fi

echo "Open: http://localhost:$PORT"
exec python3 -m streamlit run app.py --server.port "$PORT"
