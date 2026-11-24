# safari-mcp v0.2.0

Conector (servidor MCP) para que Claude trabaje en **tu Safari**, con las sesiones que ya tienes iniciadas (Google Ads, Meta Business, etc.). No necesita instalar nada extra: es un solo archivo de Python que usa AppleScript.

## Instalación (5 minutos)

1. Descomprime el zip (por ejemplo en Descargas).
2. Abre **Terminal** y escribe:
   ```bash
   cd ~/Downloads/safari-mcp
   bash install.sh
   ```
   El instalador copia el servidor a `~/safari-mcp`, hace un **respaldo** de tu configuración de Claude y te pide confirmación antes de agregar la entrada `safari`.
3. En Safari: **Ajustes > Avanzado > Mostrar funciones para desarrolladores web**.
4. Menú **Desarrollo > Permitir JavaScript desde Apple Events**.
5. Cierra Claude con **Cmd+Q** y ábrelo de nuevo. Cuando macOS pregunte si Claude puede controlar Safari, dale **Aceptar**.
6. Para capturas de pantalla (opcional): **Ajustes del Sistema > Privacidad y seguridad > Grabación de pantalla > Claude**.

Para probarlo, en un chat nuevo de Claude escribe: *"revisa la configuración de Safari con safari_check_setup"*.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `safari_check_setup` | Verifica permisos y JavaScript |
| `safari_list_tabs` | Lista ventanas y pestañas |
| `safari_open_url` | Abre una URL (mejor en pestaña nueva) y espera la carga |
| `safari_switch_tab` / `safari_close_tab` | Cambia o cierra pestañas |
| `safari_navigate` | Atrás, adelante, recargar |
| `safari_get_text` | Lee el texto de la página (paginado) |
| `safari_snapshot` | Lista botones, enlaces y campos con un código `ref` |
| `safari_click` | Clic por `ref`, texto visible o selector |
| `safari_type` | Escribe en un campo |
| `safari_select_option` | Elige opción de un `<select>` |
| `safari_scroll` | Desplaza la página |
| `safari_wait_for` | Espera un texto o elemento |
| `safari_run_js` | Ejecuta JavaScript en la página |
| `safari_screenshot` | Captura la ventana de Safari |

## Problemas comunes

- **"Safari no permite JavaScript desde Apple Events"**: falta el paso 4.
- **"macOS no autorizó controlar Safari"**: Ajustes del Sistema > Privacidad y seguridad > Automatización > activa Safari bajo Claude.
- **No aparece en Claude**: revisa que `~/Library/Application Support/Claude/claude_desktop_config.json` tenga la entrada `safari` y reinicia Claude con Cmd+Q.
- **Desinstalar**: borra la entrada `safari` de ese archivo (o restaura el respaldo `.backup-…`) y la carpeta `~/safari-mcp`.

## Seguridad

Claude actúa con tus sesiones reales. Igual que en Chrome, te pide confirmación antes de guardar cambios en campañas, publicar, enviar mensajes o mover dinero, y nunca escribe contraseñas.
