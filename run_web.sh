#!/usr/bin/env bash
# Sobe a interface web do gerador de etiquetas.
# Cria o ambiente virtual e instala as dependências quando necessário.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
MARCA="$VENV/.deps-instaladas"

if [ ! -d "$VENV" ]; then
  echo "Criando ambiente virtual em $VENV..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Reinstala só se requirements.txt mudou desde a última instalação.
if [ ! -f "$MARCA" ] || [ requirements.txt -nt "$MARCA" ]; then
  echo "Instalando dependências..."
  pip install --quiet -r requirements.txt
  touch "$MARCA"
fi

echo "Abra http://127.0.0.1:5000 no navegador (Ctrl+C para parar)."
exec python -m labels.web
