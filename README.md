# ⚠️ ATENCIÓN: SOLO PARA PRUEBAS ⚠️

Este bot de Discord es una implementación de desarrollo y está destinado **exclusivamente para uso local y pruebas**. No se recomienda su uso en servidores grandes o de producción.

# Bot de Música para Discord

Bot de música para Discord desarrollado en Python que permite reproducir música desde YouTube en tu servidor de Discord.

## Características

- 🎵 Reproducir música desde YouTube (por nombre o URL)
- ⏭️ Controlar la reproducción (saltar, detener)
- 📋 Sistema de colas para organizar la música
- 🧹 Limpiar la cola de reproducción
- ❌ Eliminar canciones específicas de la cola

## Requisitos previos

- Python 3.8 o superior
- Un token de Discord (instrucciones más abajo)
- ffmpeg instalado y disponible en PATH

### Nota sobre ffmpeg

El bot ahora detecta ffmpeg automáticamente en este orden:

1. Variable `BOT_FFMPEG_PATH` (ruta completa al ejecutable)
2. Variable `BOT_FFMPEG_DIR` (carpeta que contiene ffmpeg)
3. `ffmpeg` en PATH (recomendado para Linux/Termux)

## Instalación

1. Clona este repositorio:
   ```
   git clone https://github.com/tu-usuario/bot-discord-yt.git
   cd bot-discord-yt
   ```

2. Crea un entorno virtual e instala las dependencias:
   ```
   python -m venv .venv
   # source .venv/bin/activate  # Linux/Mac/Termux
   pip install -r requirements.txt
   ```

### Instalación en Termux (Android)

1. Instala paquetes del sistema:
   ```bash
   pkg update && pkg upgrade -y
   pkg install -y python ffmpeg git libffi openssl
   ```

2. Clona el proyecto y entra al directorio:
   ```bash
   git clone https://github.com/tu-usuario/bot-discord-yt.git
   cd bot-discord-yt
   ```

3. Crea y activa entorno virtual:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

4. Instala dependencias:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Crea un archivo `.env` en la raíz del proyecto con tu token de Discord:
   ```
   DISCORD_TOKEN=tu_token_aquí
   ```

## Cómo conseguir un token de Discord

1. Ve a [Discord Developer Portal](https://discord.com/developers/applications)
2. Haz clic en "New Application" y elige un nombre para tu aplicación
3. Ve a la sección "Bot" en el menú lateral
4. Haz clic en "Add Bot" y confirma
5. Bajo la sección "TOKEN", haz clic en "Copy" para copiar tu token
6. Pega este token en tu archivo `.env` como se mostró anteriormente

> ⚠️ **Importante**: Nunca compartas tu token de Discord. Es como una contraseña y otorga acceso a tu bot.

## Añadir el bot a tu servidor

1. En el [Discord Developer Portal](https://discord.com/developers/applications), selecciona tu aplicación
2. Ve a "OAuth2" → "URL Generator" en el menú lateral
3. En "Scopes", selecciona "bot"
4. En "Bot Permissions", selecciona:
   - Send Messages
   - Embed Links
   - Read Message History
   - Connect
   - Speak
5. Copia la URL generada y ábrela en tu navegador
6. Selecciona el servidor al que quieres añadir el bot y confirma

## Uso

1. Activa el entorno virtual:
   ```
   source .venv/bin/activate  # Linux/Mac/Termux
   ```

2. Ejecuta el bot:
   ```
   python bot_yt.py
   ```

En Termux:
```bash
source .venv/bin/activate
python bot_yt.py
```

También puedes usar el script:
```bash
bash iniciar_bot_termux.sh
```

3. En Discord, usa los siguientes comandos:

| Comando | Descripción |
|---------|-------------|
| `!youtube <nombre o link>` | Busca y reproduce música desde YouTube |
| `!skip` | Salta la canción actual |
| `!lista` | Muestra la lista de canciones en cola |
| `!eliminar <nombre>` | Elimina una canción específica de la cola |
| `!limpiar` | Limpia completamente la cola de canciones |
| `!stop` | Detiene la reproducción |
| `!leave` | Sale del canal de voz |
| `!comandos` | Muestra la lista de comandos disponibles |

## Configuración

Si quieres forzar una ruta de ffmpeg concreta, puedes usar variables de entorno:

```bash
export BOT_FFMPEG_PATH=/ruta/completa/a/ffmpeg
# o
export BOT_FFMPEG_DIR=/ruta/a/carpeta/que/contiene/ffmpeg
```

## Solución de problemas

- **El bot no reproduce audio**: Asegúrate de que ffmpeg esté correctamente instalado y configurado.
- **El bot no responde**: Verifica que el token de Discord sea correcto y que el bot tenga los permisos necesarios.
- **Errores de yt-dlp**: Si hay errores al obtener videos de YouTube, puede ser necesario actualizar yt-dlp:
  ```
  pip install --upgrade yt-dlp
  ```

## Licencia

Este proyecto está bajo licencia de código abierto. Consulta el archivo LICENSE para más detalles. 
