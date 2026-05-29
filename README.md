# HomeRadar

Scraper diario de [fincaraiz.com.co](https://www.fincaraiz.com.co) que envía las propiedades encontradas a un chat de Telegram, ordenadas por mejor valor por metro cuadrado.

Corre automáticamente todos los días a las **9:00 AM hora Colombia** vía GitHub Actions.

## Estructura

| Archivo | Rol |
|---|---|
| `homeradar.py` | Scrapea fincaraiz, limpia datos y genera `propiedades_limpias.csv` |
| `notify_telegram.py` | Lee el CSV y envía el listado al bot de Telegram |
| `HomeRadar.ipynb` | Notebook para análisis exploratorio (opcional) |
| `.github/workflows/daily.yml` | Cron de GitHub Actions (14:00 UTC = 9:00 COL) |
| `requirements.txt` | Dependencias |

## Setup inicial (una sola vez)

### 1. Conseguir el chat_id de Telegram

El bot ya existe (`@HomeRadarBog_Bot`) pero necesitas saber el `chat_id` del destino.

**Si vas a recibir los mensajes en un chat privado:**
1. Abre Telegram y envía cualquier mensaje al bot `@HomeRadarBog_Bot`.
2. Visita en el navegador:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
3. Busca en la respuesta JSON el campo `"chat":{"id": <numero>, ...}`. Ese número es tu `chat_id`.

**Si vas a recibir en un grupo:**
1. Agrega el bot al grupo.
2. Envía cualquier mensaje en el grupo.
3. Misma URL `getUpdates` y busca el `chat.id` (será negativo, ej. `-1001234567890`).

### 2. Configurar GitHub Secrets

En tu repo `https://github.com/icgwilliam/HomeRadar`:

1. Ve a **Settings → Secrets and variables → Actions → New repository secret**.
2. Crea estos dos secrets:
   - `TELEGRAM_BOT_TOKEN` → el token que te dio @BotFather al crear `@HomeRadarBog_Bot`
   - `TELEGRAM_CHAT_ID` → el número que obtuviste arriba

### 3. Push al repo

```powershell
git init
git add .
git commit -m "Initial: HomeRadar scraper + Telegram notifier"
git branch -M main
git remote add origin https://github.com/icgwilliam/HomeRadar.git
git push -u origin main
```

### 4. Verificar que el workflow funciona

1. En GitHub abre la pestaña **Actions**.
2. Selecciona el workflow **HomeRadar Daily**.
3. Click en **Run workflow** → **Run workflow** (manual).
4. Si todo está bien, en pocos minutos te llega el listado a Telegram.

## Ejecución local (debug)

```powershell
pip install -r requirements.txt
python homeradar.py

# Para probar el envío a Telegram en local:
$env:TELEGRAM_BOT_TOKEN = "tu_token"
$env:TELEGRAM_CHAT_ID = "tu_chat_id"
python notify_telegram.py
```

## Personalizar la búsqueda

Edita `START_URL` en `homeradar.py:24`. Es la URL de fincaraiz con los filtros que quieras (zona, habitaciones, baños, etc.). Lo más fácil es hacer la búsqueda en la web y copiar la URL.

## Cambiar el horario

Edita el cron en `.github/workflows/daily.yml`. Recuerda que GitHub Actions usa **UTC**:

| Hora Colombia | UTC | Cron |
|---|---|---|
| 6:00 AM | 11:00 | `0 11 * * *` |
| **9:00 AM** | **14:00** | **`0 14 * * *`** |
| 12:00 PM | 17:00 | `0 17 * * *` |
| 6:00 PM | 23:00 | `0 23 * * *` |

> Nota: GitHub Actions puede tener delays de 5-15 minutos en horas pico. No es un cron de precisión.

## Notas

- Los CSVs generados se suben como artifact del workflow (retención 30 días). Puedes descargarlos desde la pestaña Actions.
- El scraper respeta al servidor con `time.sleep(1-2.5s)` aleatorio entre requests.
- Si fincaraiz cambia el HTML, los selectores en `homeradar.py` (`parse_property`) hay que ajustarlos.
