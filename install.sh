#!/bin/bash
# Instalador de safari-mcp para Claude (app de escritorio en macOS)
set -e

DEST="$HOME/safari-mcp"
CFG_DIR="$HOME/Library/Application Support/Claude"
CFG="$CFG_DIR/claude_desktop_config.json"
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "== safari-mcp: instalación =="

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Esto solo funciona en macOS."; exit 1
fi

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
  echo "No encontré python3. Ejecuta: xcode-select --install  y vuelve a correr este instalador."; exit 1
fi
echo "python3: $PY"

mkdir -p "$DEST"
cp "$SRC/server.py" "$DEST/server.py"
chmod +x "$DEST/server.py"
echo "Servidor copiado a $DEST/server.py"

mkdir -p "$CFG_DIR"
if [[ -f "$CFG" ]]; then
  echo
  echo "Voy a AGREGAR la entrada \"safari\" a tu configuración de Claude:"
  echo "  $CFG"
  echo "Antes guardo una copia de respaldo. No toco tus otros conectores."
  read -r -p "¿Continuar? (s/n) " OK
  if [[ "$OK" != "s" && "$OK" != "S" ]]; then
    echo "Cancelado. El servidor quedó copiado, pero no se registró en Claude."; exit 0
  fi
  BK="$CFG.backup-$(date +%Y%m%d-%H%M%S)"
  cp "$CFG" "$BK"
  echo "Respaldo: $BK"
fi

"$PY" - "$CFG" "$PY" "$DEST/server.py" <<'EOF'
import json, os, sys
cfg, py, srv = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(cfg) and os.path.getsize(cfg) > 0:
    with open(cfg) as f:
        data = json.load(f)
data.setdefault("mcpServers", {})["safari"] = {"command": py, "args": [srv]}
with open(cfg, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print("Registrado en Claude como 'safari'.")
EOF

echo
echo "Comprobando Safari..."
"$PY" "$DEST/server.py" --check || true

cat <<'MSG'

Siguientes pasos:
 1. En Safari: Ajustes > Avanzado > activa "Mostrar funciones para desarrolladores web".
 2. Menú Desarrollo > activa "Permitir JavaScript desde Apple Events".
 3. Cierra Claude por completo (Cmd+Q) y vuelve a abrirlo.
 4. La primera vez, macOS te pedirá permiso para que Claude controle Safari: acepta.
 5. (Opcional, para capturas) Ajustes del Sistema > Privacidad y seguridad >
    Grabación de pantalla > activa Claude.
MSG
