#!/usr/bin/env python3
"""
safari-mcp v0.2.0
Servidor MCP (stdio, sin dependencias) para que Claude controle Safari en macOS,
usando las sesiones que ya tienes iniciadas (Google Ads, Meta, etc.).

Funciona con AppleScript (osascript) + "do JavaScript" de Safari.
Requisitos en el Mac:
  - Safari > Ajustes > Avanzado > "Mostrar funciones para desarrolladores web"
  - Menú Desarrollo > "Permitir JavaScript desde Apple Events"
  - Para capturas: permiso de Grabación de pantalla para la app Claude.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

VERSION = "0.2.0"
OSA_TIMEOUT = 45


# ----------------------------------------------------------------------------
# Utilidades AppleScript
# ----------------------------------------------------------------------------
class SafariError(Exception):
    pass


def _friendly(err: str) -> str:
    e = err or ""
    if "Allow JavaScript from Apple Events" in e or "Permitir JavaScript" in e:
        return ("Safari no permite JavaScript desde Apple Events. Actívalo en el menú "
                "Desarrollo > 'Permitir JavaScript desde Apple Events' (si no ves el menú "
                "Desarrollo: Safari > Ajustes > Avanzado > 'Mostrar funciones para "
                "desarrolladores web').")
    if "-1743" in e or "Not authorized" in e or "no está autorizado" in e:
        return ("macOS no autorizó controlar Safari. Ve a Ajustes del Sistema > Privacidad y "
                "seguridad > Automatización y activa Safari para Claude (o para Terminal).")
    if "-1728" in e or "Invalid index" in e or "índice no válido" in e:
        return "Esa ventana o pestaña no existe. Usa safari_list_tabs para ver las actuales."
    return e.strip() or "Error desconocido de AppleScript."


def osa(script_lines, *args, timeout=OSA_TIMEOUT) -> str:
    """Ejecuta AppleScript. Los argumentos viajan por argv (sin problemas de escape)."""
    cmd = ["osascript"]
    for line in script_lines:
        cmd += ["-e", line]
    if args:
        cmd += ["--"] + [str(a) for a in args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise SafariError("No se encontró osascript: este servidor solo funciona en macOS.")
    except subprocess.TimeoutExpired:
        raise SafariError("Safari tardó demasiado en responder (timeout).")
    if p.returncode != 0:
        raise SafariError(_friendly(p.stderr))
    return p.stdout.rstrip("\n")


def tab_ref(window=None, tab=None) -> str:
    if window is not None and tab is not None:
        return f"tab {int(tab)} of window {int(window)}"
    if window is not None:
        return f"current tab of window {int(window)}"
    return "current tab of front window"


def ensure_window():
    n = osa(['tell application "Safari"', "activate", "count of windows", "end tell"])
    if n.strip() == "0":
        osa(['tell application "Safari" to make new document'])
        time.sleep(0.5)


def run_js_raw(code: str, window=None, tab=None) -> str:
    ref = tab_ref(window, tab)
    return osa([
        "on run argv",
        f'tell application "Safari" to do JavaScript (item 1 of argv) in {ref}',
        "end run",
    ], code)


def run_js(body: str, window=None, tab=None):
    """Ejecuta un cuerpo de función JS (debe usar return) y devuelve el valor decodificado."""
    wrapped = (
        "(function(){try{var __v=(function(){" + body + "\n})();"
        "return JSON.stringify({ok:true,v:(__v===undefined?null:__v)});}"
        "catch(e){return JSON.stringify({ok:false,e:String(e&&e.message||e)});}})()"
    )
    out = run_js_raw(wrapped, window, tab)
    if not out:
        return None
    try:
        r = json.loads(out)
    except json.JSONDecodeError:
        return out
    if not r.get("ok"):
        raise SafariError("Error de JavaScript en la página: " + str(r.get("e")))
    return r.get("v")


def js_str(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def wait_ready(window=None, tab=None, timeout=25.0):
    end = time.time() + timeout
    time.sleep(0.6)
    while time.time() < end:
        try:
            st = run_js("return document.readyState;", window, tab)
            if st == "complete":
                return True
        except SafariError:
            pass
        time.sleep(0.5)
    return False


# ----------------------------------------------------------------------------
# JavaScript auxiliar (se inyecta en la página)
# ----------------------------------------------------------------------------
JS_COMMON = r"""
function __vis(el){
  if(!el||!el.getBoundingClientRect) return false;
  var r=el.getBoundingClientRect();
  if(r.width<2||r.height<2) return false;
  var s=getComputedStyle(el);
  if(s.visibility==='hidden'||s.display==='none'||parseFloat(s.opacity)===0) return false;
  return true;
}
function __all(root, sel, acc){
  acc=acc||[];
  try{ root.querySelectorAll(sel).forEach(function(e){acc.push(e);}); }catch(x){}
  try{ root.querySelectorAll('*').forEach(function(e){ if(e.shadowRoot) __all(e.shadowRoot, sel, acc); }); }catch(x){}
  return acc;
}
function __label(el){
  var t=(el.getAttribute('aria-label')||'').trim();
  if(!t) t=(el.innerText||'').replace(/\s+/g,' ').trim();
  if(!t) t=(el.getAttribute('placeholder')||el.getAttribute('title')||el.getAttribute('name')||'').trim();
  if(!t && el.value!==undefined && typeof el.value==='string') t=el.value.trim();
  return t.slice(0,90);
}
function __find(ref){
  var el=document.querySelector('[data-mcpid="'+ref+'"]');
  if(!el){ var hs=__all(document,'[data-mcpid="'+ref+'"]'); el=hs[0]; }
  return el||null;
}
function __byText(txt){
  txt=txt.toLowerCase();
  var sel='a,button,input,select,textarea,label,[role],[onclick],[tabindex],material-button,material-checkbox,material-tab,mat-option,li,span,div,td';
  var c=__all(document,sel).filter(function(e){ return __vis(e) && __label(e).toLowerCase().indexOf(txt)>=0; });
  if(!c.length) return null;
  var exact=c.filter(function(e){ return __label(e).toLowerCase()===txt; });
  if(exact.length) c=exact;
  c.sort(function(a,b){ var ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect(); return ra.width*ra.height-rb.width*rb.height; });
  return c[0];
}
function __click(el){
  el.scrollIntoView({block:'center',inline:'center'});
  var r=el.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
  var o={bubbles:true,cancelable:true,composed:true,clientX:x,clientY:y,button:0,view:window};
  try{ el.dispatchEvent(new PointerEvent('pointerdown',o)); }catch(e){}
  el.dispatchEvent(new MouseEvent('mousedown',o));
  try{ el.dispatchEvent(new PointerEvent('pointerup',o)); }catch(e){}
  el.dispatchEvent(new MouseEvent('mouseup',o));
  if(typeof el.click==='function') el.click(); else el.dispatchEvent(new MouseEvent('click',o));
}
"""

JS_SNAPSHOT = JS_COMMON + r"""
var SEL='a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=menuitemcheckbox],[role=option],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=textbox],[role=gridcell],[contenteditable=true],[onclick],material-button,material-checkbox,material-tab,material-dropdown-select,material-input,mat-option';
var els=__all(document,SEL).filter(__vis);
var onlyView=__ONLYVIEW__, q=__QUERY__, max=__MAX__;
var vh=window.innerHeight, vw=window.innerWidth;
var out=[], n=0;
for(var i=0;i<els.length;i++){
  var el=els[i], r=el.getBoundingClientRect();
  if(onlyView && (r.bottom<0||r.top>vh||r.right<0||r.left>vw)) continue;
  var lab=__label(el);
  if(q && lab.toLowerCase().indexOf(q.toLowerCase())<0) continue;
  var id=el.getAttribute('data-mcpid');
  if(!id){ id='e'+Math.random().toString(36).slice(2,8); el.setAttribute('data-mcpid',id); }
  var tag=el.tagName.toLowerCase(), role=el.getAttribute('role')||'';
  var extra='';
  if(tag==='input'||tag==='textarea'||tag==='select'){ extra=' type='+(el.type||tag)+(el.value?(' valor="'+String(el.value).slice(0,40)+'"'):''); }
  if(el.getAttribute('aria-checked')) extra+=' checked='+el.getAttribute('aria-checked');
  if(el.getAttribute('aria-selected')==='true') extra+=' seleccionado';
  if(el.disabled||el.getAttribute('aria-disabled')==='true') extra+=' deshabilitado';
  out.push('['+id+'] '+tag+(role?('('+role+')'):'')+' "'+lab+'"'+extra);
  if(++n>=max) break;
}
return {url:location.href,title:document.title,scrollY:Math.round(scrollY),alto:document.documentElement.scrollHeight,elementos:out};
"""

JS_CLICK = JS_COMMON + r"""
var ref=__REF__, txt=__TEXT__, sel=__SEL__;
var el=null;
if(ref) el=__find(ref);
if(!el && sel){ el=document.querySelector(sel)||__all(document,sel)[0]; }
if(!el && txt) el=__byText(txt);
if(!el) throw new Error('No encontré el elemento. Usa safari_snapshot para ver los disponibles.');
__click(el);
return 'Clic en <'+el.tagName.toLowerCase()+'> "'+__label(el)+'"';
"""

JS_TYPE = JS_COMMON + r"""
var ref=__REF__, sel=__SEL__, text=__TEXT__, clear=__CLEAR__, submit=__SUBMIT__;
var el=null;
if(ref) el=__find(ref);
if(!el && sel) el=document.querySelector(sel)||__all(document,sel)[0];
if(!el) el=document.activeElement;
if(!el||el===document.body) throw new Error('No hay campo de texto. Indica ref o selector.');
el.scrollIntoView({block:'center'});
el.focus();
if(el.isContentEditable){
  if(clear){ document.execCommand('selectAll',false,null); document.execCommand('delete',false,null); }
  document.execCommand('insertText',false,text);
}else{
  var proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
  var setter=Object.getOwnPropertyDescriptor(proto,'value').set;
  setter.call(el,(clear?'':el.value)+text);
  el.dispatchEvent(new Event('input',{bubbles:true,composed:true}));
  el.dispatchEvent(new Event('change',{bubbles:true,composed:true}));
}
if(submit){
  ['keydown','keypress','keyup'].forEach(function(t){
    el.dispatchEvent(new KeyboardEvent(t,{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true}));
  });
  if(el.form && el.form.requestSubmit) { try{ el.form.requestSubmit(); }catch(e){} }
}
return 'Escrito en <'+el.tagName.toLowerCase()+'> "'+__label(el)+'"';
"""

JS_SELECT = JS_COMMON + r"""
var ref=__REF__, sel=__SEL__, opt=__OPT__;
var el=ref?__find(ref):(sel?document.querySelector(sel):null);
if(!el||el.tagName!=='SELECT') throw new Error('No es un <select> nativo. Para menús de Google usa safari_click sobre el menú y luego sobre la opción.');
var o=Array.from(el.options).find(function(x){return x.value===opt||x.text.trim().toLowerCase()===opt.toLowerCase();});
if(!o) throw new Error('Opción no encontrada. Opciones: '+Array.from(el.options).map(function(x){return x.text.trim();}).join(' | '));
el.value=o.value; el.dispatchEvent(new Event('change',{bubbles:true}));
return 'Seleccionado: '+o.text.trim();
"""

JS_TEXT = r"""
var t=(document.body?document.body.innerText:'')||'';
t=t.replace(/\n{3,}/g,'\n\n');
var off=__OFF__, max=__MAX__;
return {url:location.href,title:document.title,total:t.length,desde:off,texto:t.slice(off,off+max)};
"""

JS_SCROLL = JS_COMMON + r"""
var ref=__REF__, dir=__DIR__, amt=__AMT__;
if(ref){ var el=__find(ref); if(!el) throw new Error('ref no encontrada'); el.scrollIntoView({block:'center'}); return 'Elemento visible'; }
var dy=0,dx=0, h=window.innerHeight*0.8*amt;
if(dir==='down') dy=h; else if(dir==='up') dy=-h; else if(dir==='right') dx=h; else if(dir==='left') dx=-h;
else if(dir==='top'){ window.scrollTo(0,0); return 'Arriba'; } else if(dir==='bottom'){ window.scrollTo(0,document.documentElement.scrollHeight); return 'Abajo'; }
window.scrollBy(dx,dy);
return 'scrollY='+Math.round(scrollY)+' de '+document.documentElement.scrollHeight;
"""

JS_WAITCHECK = JS_COMMON + r"""
var sel=__SEL__, txt=__TEXT__;
if(sel){ var e=document.querySelector(sel)||__all(document,sel)[0]; return !!(e&&__vis(e)); }
if(txt){ return ((document.body&&document.body.innerText)||'').toLowerCase().indexOf(txt.toLowerCase())>=0; }
return document.readyState==='complete';
"""


def fill(tpl: str, **kw) -> str:
    for k, v in kw.items():
        tpl = tpl.replace(f"__{k}__", js_str(v))
    return tpl


# ----------------------------------------------------------------------------
# Herramientas
# ----------------------------------------------------------------------------
def t_list_tabs(a):
    out = osa([
        "set TB to ASCII character 9",
        'set res to ""',
        'tell application "Safari"',
        "repeat with w from 1 to count of windows",
        "set ci to 0",
        "try",
        "set ci to index of current tab of window w",
        "end try",
        "repeat with t from 1 to count of tabs of window w",
        'set nm to ""',
        'set u to ""',
        "try",
        "set nm to name of tab t of window w",
        "end try",
        "try",
        "set u to URL of tab t of window w",
        "end try",
        'set mk to ""',
        'if t = ci then set mk to "*"',
        "set res to res & w & TB & t & TB & mk & TB & nm & TB & u & linefeed",
        "end repeat",
        "end repeat",
        "end tell",
        "return res",
    ])
    lines = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) >= 5:
            cur = " (actual)" if p[2] == "*" else ""
            lines.append(f"ventana {p[0]} · pestaña {p[1]}{cur}: {p[3]} — {p[4]}")
    return "\n".join(lines) or "Safari no tiene ventanas abiertas."


def t_open(a):
    url = a["url"]
    if "://" not in url and not url.startswith("about:"):
        url = "https://" + url
    ensure_window()
    if a.get("new_tab"):
        osa([
            "on run argv",
            'tell application "Safari"',
            "tell front window to set current tab to (make new tab with properties {URL:(item 1 of argv)})",
            "end tell",
            "end run",
        ], url)
        w, t = None, None
    else:
        w, t = a.get("window"), a.get("tab")
        osa([
            "on run argv",
            f'tell application "Safari" to set URL of {tab_ref(w, t)} to (item 1 of argv)',
            "end run",
        ], url)
    ok = wait_ready(w, t)
    info = run_js("return {url:location.href,title:document.title};", w, t)
    return f"{'Cargada' if ok else 'Sigue cargando'}: {info.get('title')} — {info.get('url')}"


def t_switch(a):
    w, t = int(a["window"]), int(a["tab"])
    osa(['tell application "Safari"', "activate",
         f"set index of window {w} to 1",
         f"tell front window to set current tab to tab {t}", "end tell"])
    return "Pestaña activada.\n" + t_list_tabs({})


def t_close(a):
    osa([f'tell application "Safari" to close {tab_ref(a.get("window"), a.get("tab"))}'])
    return "Pestaña cerrada."


def t_nav(a):
    act = a["action"]
    w, t = a.get("window"), a.get("tab")
    js = {"back": "history.back();", "forward": "history.forward();",
          "reload": "location.reload();"}.get(act)
    if not js:
        raise SafariError("action debe ser back, forward o reload")
    run_js(js + " return true;", w, t)
    wait_ready(w, t)
    info = run_js("return {url:location.href,title:document.title};", w, t)
    return f"{info.get('title')} — {info.get('url')}"


def t_get_text(a):
    r = run_js(fill(JS_TEXT, OFF=int(a.get("offset", 0)), MAX=int(a.get("max_chars", 20000))),
               a.get("window"), a.get("tab"))
    more = ""
    if r["desde"] + len(r["texto"]) < r["total"]:
        more = f"\n\n[... quedan más caracteres: usa offset={r['desde'] + len(r['texto'])}]"
    return f"{r['title']} — {r['url']}\n(caracteres {r['desde']}-{r['desde'] + len(r['texto'])} de {r['total']})\n\n{r['texto']}{more}"


def t_snapshot(a):
    r = run_js(fill(JS_SNAPSHOT, ONLYVIEW=bool(a.get("only_viewport", True)),
                    QUERY=a.get("query", "") or "", MAX=int(a.get("max", 150))),
               a.get("window"), a.get("tab"))
    head = f"{r['title']} — {r['url']}\nscroll {r['scrollY']} de {r['alto']}px · {len(r['elementos'])} elementos"
    return head + "\n" + "\n".join(r["elementos"]) + \
        "\n\nUsa el código entre corchetes como ref en safari_click / safari_type."


def t_click(a):
    if not (a.get("ref") or a.get("text") or a.get("selector")):
        raise SafariError("Indica ref, text o selector.")
    msg = run_js(fill(JS_CLICK, REF=a.get("ref") or "", TEXT=a.get("text") or "",
                      SEL=a.get("selector") or ""), a.get("window"), a.get("tab"))
    time.sleep(float(a.get("wait", 1.0)))
    return msg


def t_type(a):
    msg = run_js(fill(JS_TYPE, REF=a.get("ref") or "", SEL=a.get("selector") or "",
                      TEXT=a["text"], CLEAR=bool(a.get("clear", True)),
                      SUBMIT=bool(a.get("submit", False))), a.get("window"), a.get("tab"))
    time.sleep(0.5)
    return msg


def t_select(a):
    return run_js(fill(JS_SELECT, REF=a.get("ref") or "", SEL=a.get("selector") or "",
                       OPT=a["option"]), a.get("window"), a.get("tab"))


def t_scroll(a):
    return run_js(fill(JS_SCROLL, REF=a.get("ref") or "", DIR=a.get("direction", "down"),
                       AMT=float(a.get("amount", 1))), a.get("window"), a.get("tab"))


def t_wait(a):
    timeout = float(a.get("timeout", 15))
    sel, txt = a.get("selector") or "", a.get("text") or ""
    if not sel and not txt:
        time.sleep(min(timeout, 30))
        return f"Esperé {min(timeout, 30)} s."
    end = time.time() + timeout
    js = fill(JS_WAITCHECK, SEL=sel, TEXT=txt)
    while time.time() < end:
        try:
            if run_js(js, a.get("window"), a.get("tab")):
                return "Apareció."
        except SafariError:
            pass
        time.sleep(0.7)
    return f"No apareció en {timeout} s."


def t_run_js(a):
    code = a["code"].strip()
    if "return" not in code and "\n" not in code and ";" not in code.rstrip(";"):
        code = "return (" + code.rstrip(";") + ");"
    v = run_js(code, a.get("window"), a.get("tab"))
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1)


def t_screenshot(a):
    osa(['tell application "Safari" to activate'])
    time.sleep(0.4)
    wid = osa(['tell application "Safari" to get id of front window']).strip()
    tmp = tempfile.mkdtemp(prefix="safari-mcp-")
    png, jpg = os.path.join(tmp, "s.png"), os.path.join(tmp, "s.jpg")
    p = subprocess.run(["screencapture", "-x", "-o", "-l", wid, png], capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(png) or os.path.getsize(png) == 0:
        subprocess.run(["screencapture", "-x", png], capture_output=True)
    if not os.path.exists(png) or os.path.getsize(png) == 0:
        raise SafariError("No se pudo capturar. Da permiso de Grabación de pantalla a Claude en "
                          "Ajustes del Sistema > Privacidad y seguridad.")
    maxw = int(a.get("max_width", 1400))
    subprocess.run(["sips", "-Z", str(maxw), "-s", "format", "jpeg", "-s", "formatOptions", "70",
                    png, "--out", jpg], capture_output=True)
    path = jpg if os.path.exists(jpg) else png
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"__image__": data, "mime": "image/jpeg" if path == jpg else "image/png"}


def t_check(a):
    lines = [f"safari-mcp {VERSION}"]
    try:
        osa(['tell application "Safari" to count of windows'])
        lines.append("✓ Control de Safari autorizado")
    except SafariError as e:
        lines.append("✗ " + str(e))
        return "\n".join(lines)
    try:
        ensure_window()
        run_js("return 1+1;")
        lines.append("✓ JavaScript desde Apple Events activado")
    except SafariError as e:
        lines.append("✗ " + str(e))
    return "\n".join(lines)


W_T = {
    "window": {"type": "integer", "description": "Número de ventana (opcional; por defecto la del frente)"},
    "tab": {"type": "integer", "description": "Número de pestaña (opcional; por defecto la actual)"},
}

TOOLS = [
    ("safari_check_setup", "Verifica que Safari esté listo (permisos y JavaScript desde Apple Events).", {}, [], t_check),
    ("safari_list_tabs", "Lista las ventanas y pestañas abiertas en Safari con su título y URL.", {}, [], t_list_tabs),
    ("safari_open_url", "Abre una URL en Safari (en la pestaña actual o en una nueva) y espera a que cargue.",
     {"url": {"type": "string"}, "new_tab": {"type": "boolean", "description": "Abrir en pestaña nueva (recomendado)"}, **W_T}, ["url"], t_open),
    ("safari_switch_tab", "Pone al frente una pestaña concreta.",
     {"window": {"type": "integer"}, "tab": {"type": "integer"}}, ["window", "tab"], t_switch),
    ("safari_close_tab", "Cierra una pestaña (por defecto la actual).", {**W_T}, [], t_close),
    ("safari_navigate", "Atrás, adelante o recargar.",
     {"action": {"type": "string", "enum": ["back", "forward", "reload"]}, **W_T}, ["action"], t_nav),
    ("safari_get_text", "Lee el texto visible de la página (paginado con offset).",
     {"max_chars": {"type": "integer", "default": 20000}, "offset": {"type": "integer", "default": 0}, **W_T}, [], t_get_text),
    ("safari_snapshot", "Lista los elementos interactivos (botones, enlaces, campos, pestañas) con un código ref para hacer clic o escribir.",
     {"only_viewport": {"type": "boolean", "default": True, "description": "Solo lo visible en pantalla"},
      "query": {"type": "string", "description": "Filtrar por texto"}, "max": {"type": "integer", "default": 150}, **W_T}, [], t_snapshot),
    ("safari_click", "Hace clic en un elemento por ref (de safari_snapshot), por texto visible o por selector CSS.",
     {"ref": {"type": "string"}, "text": {"type": "string"}, "selector": {"type": "string"},
      "wait": {"type": "number", "default": 1.0, "description": "Segundos a esperar después"}, **W_T}, [], t_click),
    ("safari_type", "Escribe texto en un campo (por ref, selector o el campo enfocado).",
     {"text": {"type": "string"}, "ref": {"type": "string"}, "selector": {"type": "string"},
      "clear": {"type": "boolean", "default": True}, "submit": {"type": "boolean", "default": False}, **W_T}, ["text"], t_type),
    ("safari_select_option", "Elige una opción en un <select> nativo.",
     {"option": {"type": "string"}, "ref": {"type": "string"}, "selector": {"type": "string"}, **W_T}, ["option"], t_select),
    ("safari_scroll", "Desplaza la página (up/down/left/right/top/bottom) o lleva un elemento a la vista.",
     {"direction": {"type": "string", "enum": ["up", "down", "left", "right", "top", "bottom"]},
      "amount": {"type": "number", "default": 1}, "ref": {"type": "string"}, **W_T}, [], t_scroll),
    ("safari_wait_for", "Espera a que aparezca un texto o selector (o solo espera unos segundos).",
     {"text": {"type": "string"}, "selector": {"type": "string"}, "timeout": {"type": "number", "default": 15}, **W_T}, [], t_wait),
    ("safari_run_js", "Ejecuta JavaScript en la página y devuelve el resultado (usa return).",
     {"code": {"type": "string"}, **W_T}, ["code"], t_run_js),
    ("safari_screenshot", "Captura de pantalla de la ventana de Safari al frente.",
     {"max_width": {"type": "integer", "default": 1400}}, [], t_screenshot),
]
TOOL_MAP = {t[0]: t for t in TOOLS}


# ----------------------------------------------------------------------------
# Protocolo MCP (JSON-RPC 2.0 sobre stdio, una línea por mensaje)
# ----------------------------------------------------------------------------
def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    method, rid = req.get("method"), req.get("id")
    if method == "initialize":
        pv = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return {"protocolVersion": pv, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "safari-mcp", "version": VERSION},
                "instructions": "Controla Safari del usuario con sus sesiones iniciadas. Flujo típico: "
                                "safari_open_url (new_tab) -> safari_get_text / safari_snapshot -> safari_click / safari_type. "
                                "Pide confirmación al usuario antes de guardar cambios, publicar o gastar dinero."}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d,
                           "inputSchema": {"type": "object", "properties": p, "required": r}}
                          for n, d, p, r, _ in TOOLS]}
    if method == "tools/call":
        params = req.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOL_MAP:
            return {"content": [{"type": "text", "text": f"Herramienta desconocida: {name}"}], "isError": True}
        try:
            res = TOOL_MAP[name][4](args)
            if isinstance(res, dict) and "__image__" in res:
                return {"content": [{"type": "image", "data": res["__image__"], "mimeType": res["mime"]}]}
            return {"content": [{"type": "text", "text": str(res)}]}
        except SafariError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:  # noqa
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    if rid is None:
        return None  # notificación
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        rid = req.get("id")
        try:
            result = handle(req)
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "result": result if result is not None else {}})
        except LookupError as e:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Método no soportado: {e}"}})
        except Exception as e:  # noqa
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print(t_check({}))
    else:
        main()
