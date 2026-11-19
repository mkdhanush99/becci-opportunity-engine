#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"
cd "$SCRIPT_DIR"

# Ensure persistent data directory exists on Azure /home
mkdir -p /home/data
if [ ! -f /home/data/becci.db ] && [ -f ./data/becci.db ]; then
  echo "Initialising persistent database at /home/data/becci.db from bundle..."
  cp ./data/becci.db /home/data/becci.db
fi

python -m uvicorn main:app --host 0.0.0.0 --port 8000
