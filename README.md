# HomeRadar

Scraper diario de [fincaraiz.com.co](https://www.fincaraiz.com.co) que envía las propiedades encontradas a los suscriptores de un bot de Telegram, ordenadas por mejor valor por metro cuadrado.

Cualquiera que escanee el **QR del bot** (o abra el enlace de Telegram del bot) y envíe `/start` queda suscrito y recibe el listado diario. `/stop` lo da de baja.

Corre automáticamente todos los días a las **9:00 AM hora Colombia** vía GitHub Actions.

## Arquitectura

| Componente | Rol |
|---|---|
| `homeradar.py` | Scrapea fincaraiz, limpia datos y genera `propiedades_limpias.csv` |
| `notify_telegram.py` | Lee el CSV y difunde el listado a **todos los suscriptores** |
| `bot.py` | Webhook del bot de Telegram: gestiona `/start`, `/stop`, `/help` |
| `utils_gist.py` | Persiste la lista de `chat_id` suscritos en un gist privado de GitHub |
| `.github/workflows/daily.yml` | Cron de GitHub Actions (14:00 UTC = 9:00 COL) |
| `requirements.txt` | Dependencias |

Los `chat_id` de los suscriptores se guardan en un **gist privado de GitHub** (`subscribers.json`), compartido entre el bot (escribe) y el notifier (lee). Ningún token se versiona: todo vive en GitHub Secrets / variables de entorno.

## Setup inicial (una sola vez)

### 1. Crear el bot en Telegram

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot`.
2. Guarda el **token** que te entrega.

### 2. Crear el gist privado de suscriptores

1. Ve a [gist.github.com](https://gist.github.com) y crea un gist **privado** (Secret gist).
   - Nombre del archivo: `subscribers.json`
   - Contenido inicial: `{"chat_ids": []}`
2. Copia el **id** del gist (la parte final de su URL) → `GIST_ID`.
3. Crea un **Personal Access Token** (GitHub → Settings → Developer settings → Tokens (classic)) con scope **`gist`** → `GIST_TOKEN`.

> Importante: usa un PAT dedicado (no tu token personal principal) con el scope mínimo `gist`. Se usará tanto en el deploy del bot como en GitHub Actions.

### 3. Configurar GitHub Secrets

En tu repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token de @BotFather |
| `GIST_TOKEN` | PAT con scope `gist` |
| `GIST_ID` | id del gist privado |

> Opcional: `TELEGRAM_CHAT_ID` para mantener un destinatario fijo además de los suscriptores (legacy).

### 4. Desplegar el bot (host siempre arriba)

El bot necesita un servidor escuchando webhooks de Telegram. Opciones recomendadas (planes gratuitos):

- **Railway** / **Render** / **fly.io**: usa el `Procfile` incluido.
- Cualquier VPS con `python bot.py --url https://tu-dominio`.

Pasos genéricos:

1. Conecta el repo a la plataforma elegida.
2. Define las variables de entorno: `TELEGRAM_BOT_TOKEN`, `GIST_TOKEN`, `GIST_ID` y `WEBHOOK_URL` (la URL pública del servicio, ej. `https://homeradar-bot.up.railway.app`).
3. Despliega. El `Procfile` ejecuta `python bot.py --url $WEBHOOK_URL`, que registra el webhook con Telegram.
4. Verifica: abre `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` y confirma `"url"` apunta a tu servicio.

**Modo local (sin exponer puertos):**

```powershell
$env:TELEGRAM_BOT_TOKEN = "tu_token"
$env:GIST_TOKEN = "tu_pat"
$env:GIST_ID = "tu_gist_id"
python bot.py --poll
```

### 5. Generar el QR del bot

El QR debe abrir el enlace del bot: `https://t.me/<tu_nombre_de_bot>`. Genera el QR con cualquier herramienta (ej. `qrencode -o qr.png https://t.me/<bot>` o un generador web). El archivo `qr*.png`/`qr*.svg` ya está ignorado por git.

Quien escanee el QR abre el bot → toca **Iniciar** → Telegram envía `/start` → queda suscrito.

### 6. Verificar el workflow

1. En GitHub → **Actions** → **HomeRadar Daily** → **Run workflow** (manual).
2. En pocos minutos llega el listado a todos los suscriptores.

## Ejecución local (debug)

```powershell
pip install -r requirements.txt
python homeradar.py

# Probar el envío a Telegram en local:
$env:TELEGRAM_BOT_TOKEN = "tu_token"
$env:GIST_TOKEN = "tu_pat"
$env:GIST_ID = "tu_gist_id"
python notify_telegram.py
```

## Personalizar la búsqueda

Edita `START_URL` en `homeradar.py:24`. Es la URL de fincaraiz con los filtros que quieras (zona, habitaciones, baños, etc.). Lo más fácil es hacer la búsqueda en la web y copiar la URL.

## Cambiar el horario

Edita el cron en `.github/workflows/daily.yml`. GitHub Actions usa **UTC**:

| Hora Colombia | UTC | Cron |
|---|---|---|
| 6:00 AM | 11:00 | `0 11 * * *` |
| **9:00 AM** | **14:00** | **`0 14 * * *`** |
| 12:00 PM | 17:00 | `0 17 * * *` |
| 6:00 PM | 23:00 | `0 23 * * *` |

> GitHub Actions puede tener delays de 5-15 minutos en horas pico. No es un cron de precisión.

## Comandos del bot

| Comando | Acción |
|---|---|
| `/start` | Suscribirse al listado diario |
| `/stop` | Dejar de recibir el listado |
| `/help` | Mostrar ayuda |

## Notas

- Los CSVs generados se suben como artifact del workflow (retención 30 días).
- El scraper respeta al servidor con `time.sleep(1-2.5s)` aleatorio entre requests.
- Si fincaraiz cambia el HTML, los selectores en `homeradar.py` (`parse_property`) hay que ajustarlos.
- Los `chat_id` de suscriptores son identificadores numéricos públicos de Telegram; no exponen datos personales sensibles, pero igual el gist debe ser privado.
