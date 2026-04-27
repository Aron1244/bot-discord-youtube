import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import shutil
import sys
from collections import deque
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from dotenv import load_dotenv
from discord import FFmpegPCMAudio

# Cargar variables de entorno
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


def obtener_token_discord():
    token = os.getenv("DISCORD_TOKEN", "").strip().strip('"').strip("'")
    if not token or token.lower() in {"tu_token_aqui", "tu_token_aquí", "token"}:
        raise ValueError(
            "DISCORD_TOKEN no está configurado correctamente. "
            "Crea/edita el archivo .env en la raíz con: DISCORD_TOKEN=tu_token_real"
        )
    return token


TOKEN = obtener_token_discord()

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Ruta a ffmpeg
BASE_DIR = Path(__file__).resolve().parent
RUTA_FFMPEG = "ffmpeg"
RUTA_FFMPEG_DIR = None

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

colas_musica = {}  # Diccionario con una cola por servidor
reproduccion_actual = {}  # Titulo en reproduccion por servidor
cache_playlist_urls = {}  # URLs pendientes de resolver por servidor
tareas_precarga_playlist = {}  # Tarea de precarga activa por servidor
canal_voz_objetivo = {}  # Canal de voz objetivo por servidor
detener_reproduccion = {}  # Bandera para evitar auto-advance al detener


class YtDlpLoggerSilencioso:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def crear_opciones_base_yt_dlp():
    node_path = shutil.which("node")
    opciones = {
        'quiet': True,
        'no_warnings': True,
        'logger': YtDlpLoggerSilencioso(),
        'remote_components': ['ejs:github']
    }

    if node_path:
        opciones['js_runtimes'] = {'node': {'path': node_path}}

    if os.path.exists(RUTA_FFMPEG_DIR):
        opciones['ffmpeg_location'] = RUTA_FFMPEG_DIR

    return opciones


def construir_before_options(info):
    headers = info.get('http_headers') or {}
    before = ffmpeg_options['before_options']

    # Algunos hosts (HLS/CDN) exigen cabeceras de navegador para entregar segmentos.
    user_agent = headers.get('User-Agent')
    referer = headers.get('Referer')

    if user_agent:
        before += f' -user_agent "{user_agent.replace("\"", "")}"'
    if referer:
        before += f' -referer "{referer.replace("\"", "")}"'

    return before


def descomponer_item_cola(item):
    if isinstance(item, dict) and item.get('tipo') == 'youtube_pendiente':
        return item.get('url'), item.get('titulo', 'Desconocido'), None

    if isinstance(item, tuple):
        if len(item) == 3:
            return item[0], item[1], item[2]
        if len(item) == 2:
            return item[0], item[1], ffmpeg_options['before_options']
    return None, 'Desconocido', ffmpeg_options['before_options']


def construir_titulo_pendiente(url_video, indice):
    try:
        parsed = urlparse(url_video)
        video_id = (parse_qs(parsed.query).get('v') or [None])[0]
        if video_id:
            return f"YouTube {indice}: {video_id}"
    except Exception:
        pass
    return f"YouTube {indice}"


def crear_item_pendiente(url_video, indice):
    return {
        'tipo': 'youtube_pendiente',
        'url': url_video,
        'titulo': construir_titulo_pendiente(url_video, indice)
    }


def crear_opciones_yt_dlp(formato, busqueda_por_defecto=None):
    opciones = {
        'format': formato,
        'noplaylist': True,
        **crear_opciones_base_yt_dlp()
    }

    if busqueda_por_defecto:
        opciones['default_search'] = busqueda_por_defecto

    return opciones


def normalizar_url_youtube(url_texto):
    texto = (url_texto or '').strip()
    if not (texto.startswith('http://') or texto.startswith('https://')):
        return texto

    try:
        parsed = urlparse(texto)
        host = (parsed.netloc or '').lower()

        if 'youtu.be' in host:
            video_id = parsed.path.strip('/')
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
            return texto

        if 'youtube.com' in host and parsed.path == '/watch':
            params = parse_qs(parsed.query)
            video_id = (params.get('v') or [None])[0]
            if video_id:
                # Ignora list/index/start para evitar que yt-dlp intente tratarlo como playlist.
                return f"https://www.youtube.com/watch?v={video_id}"

        return texto
    except Exception:
        return texto


def es_url_playlist_youtube(url_texto):
    texto = (url_texto or '').strip()
    if not (texto.startswith('http://') or texto.startswith('https://')):
        return False

    try:
        parsed = urlparse(texto)
        host = (parsed.netloc or '').lower()
        if 'youtube.com' not in host and 'youtu.be' not in host:
            return False

        params = parse_qs(parsed.query)
        playlist_id = (params.get('list') or [None])[0]
        if not playlist_id:
            return False

        path = (parsed.path or '').lower()
        if path == '/playlist':
            return True

        # En /watch?v=...&list=... lo tratamos como video único en !youtube.
        if path == '/watch' and (params.get('v') or [None])[0]:
            return False

        return True
    except Exception:
        return False


def obtener_playlist_id_youtube(url_texto):
    texto = (url_texto or '').strip()
    if not texto:
        return None

    try:
        parsed = urlparse(texto)
        params = parse_qs(parsed.query)
        playlist_id = (params.get('list') or [None])[0]
        if playlist_id:
            return playlist_id

        # Fallback robusto para enlaces copiados desde Discord o navegadores.
        import re
        match = re.search(r'(?:[?&]|\?)list=([^&\s>]+)', texto)
        if match:
            return match.group(1)
    except Exception:
        pass

    return None


def normalizar_url_video_youtube(url_texto):
    texto = (url_texto or '').strip()
    if not texto:
        return None

    if texto.startswith('/'):
        texto = f"https://www.youtube.com{texto}"

    if texto.startswith('http://') or texto.startswith('https://'):
        return normalizar_url_youtube(texto)

    # Algunas entradas planas devuelven solo el id del video.
    return f"https://www.youtube.com/watch?v={texto}"


def extraer_urls_playlist_youtube(url_playlist):
    playlist_id = obtener_playlist_id_youtube(url_playlist)
    urls_candidatas = []
    if playlist_id:
        urls_candidatas.append(f"https://www.youtube.com/playlist?list={playlist_id}")
    urls_candidatas.append(url_playlist)

    vistos = set()
    urls = []

    for url_objetivo in urls_candidatas:
        for modo_plano in (True, False):
            ydl_opts = {
                'noplaylist': False,
                'extract_flat': modo_plano,
                'ignoreerrors': True,
                **crear_opciones_base_yt_dlp()
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url_objetivo, download=False)
            except Exception:
                continue

            entries = (info or {}).get('entries') or []
            for entry in entries:
                if not entry:
                    continue

                entry_url = entry.get('webpage_url') or entry.get('url') or entry.get('id')
                normalizada = normalizar_url_video_youtube(entry_url)
                if not normalizada or normalizada in vistos:
                    continue

                vistos.add(normalizada)
                urls.append(normalizada)

            if urls:
                return urls

    return urls


def preparar_items_playlist(urls_playlist):
    items = []
    errores = 0

    for url_video in urls_playlist:
        try:
            items.append(extraer_info_audio(url_video))
        except Exception:
            errores += 1

    return items, errores


def cancelar_precarga_playlist(guild_id):
    tarea = tareas_precarga_playlist.pop(guild_id, None)
    if tarea and not tarea.done():
        tarea.cancel()
    cache_playlist_urls.pop(guild_id, None)


async def procesar_cache_playlist(ctx, guild_id):
    agregadas = 0
    omitidas = 0

    try:
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client is None or not voice_client.is_connected():
            voice_client = await unirse_canal_voz(ctx)
            if voice_client is None:
                await ctx.send("No pude iniciar la playlist porque no hay conexión de voz disponible.")
                return

        while cache_playlist_urls.get(guild_id):
            url_video = cache_playlist_urls[guild_id].popleft()

            try:
                item = await asyncio.to_thread(extraer_info_audio, url_video)
            except Exception:
                omitidas += 1
                continue

            await colas_musica[guild_id].put(item)
            agregadas += 1

            voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
            if agregadas == 1 and not (voice_client and voice_client.is_playing()):
                await reproducir_siguiente(ctx, guild_id)

        if agregadas == 0:
            await ctx.send("No se pudo preparar ninguna canción reproducible de la playlist.")
            return

        mensaje = f"✅ Playlist procesada desde cache: {agregadas} canción(es) en cola."
        if omitidas:
            mensaje += f" Omitidas por error/bloqueo/privado: {omitidas}."
        await ctx.send(mensaje)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error en procesar_cache_playlist (guild {guild_id}): {e}")
        try:
            await ctx.send(f"❌ Error al procesar playlist en segundo plano: {type(e).__name__}: {e}")
        except Exception:
            pass
    finally:
        tareas_precarga_playlist.pop(guild_id, None)
        if cache_playlist_urls.get(guild_id) is not None and not cache_playlist_urls[guild_id]:
            cache_playlist_urls.pop(guild_id, None)


async def cargar_playlist_en_cola(ctx, guild_id, voice_client, nombre):
    await ctx.send("📚 Playlist detectada. Preparando canciones, esto puede tardar unos segundos...")

    urls_playlist = await asyncio.to_thread(extraer_urls_playlist_youtube, nombre)
    await ctx.send(f"🔎 URLs extraídas de la playlist: {len(urls_playlist)}")
    if not urls_playlist:
        await ctx.send("No se pudieron obtener canciones de la playlist.")
        return

    cancelar_precarga_playlist(guild_id)
    cache_playlist_urls[guild_id] = deque(urls_playlist)

    agregadas_inicial = 0
    omitidas_inicial = 0

    # Intenta iniciar reproducción aquí mismo con la primera canción reproducible.
    while cache_playlist_urls.get(guild_id):
        url_video = cache_playlist_urls[guild_id].popleft()
        try:
            item = await asyncio.to_thread(extraer_info_audio, url_video)
        except Exception:
            omitidas_inicial += 1
            continue

        await colas_musica[guild_id].put(item)
        agregadas_inicial += 1
        await ctx.send(f"➕ Primera canción en cola: {item[1]}")

        if not (voice_client and voice_client.is_playing()):
            await ctx.send("▶️ Intentando arrancar reproducción inicial...")
            await reproducir_siguiente(ctx, guild_id)
        break

    if agregadas_inicial == 0:
        await ctx.send("No se pudo preparar ninguna canción reproducible de la playlist.")
        return

    if cache_playlist_urls.get(guild_id):
        await ctx.send(f"🧵 Lanzando worker de cache con {len(cache_playlist_urls[guild_id])} URL(s) pendientes...")
        tarea = asyncio.create_task(procesar_cache_playlist(ctx, guild_id))
        tareas_precarga_playlist[guild_id] = tarea

    mensaje = (
        f"📦 Playlist enviada a cache: {len(urls_playlist)} URL(s). "
        "Iré pasándolas una por una al reproductor."
    )
    if omitidas_inicial:
        mensaje += f" Omitidas al iniciar: {omitidas_inicial}."
    await ctx.send(mensaje)


def extraer_info_audio(url):
    ultimo_error = None
    info = None

    # Algunos sitios no publican un formato "bestaudio" puro.
    for formato in ('bestaudio/best', 'best'):
        try:
            ydl_opts = crear_opciones_yt_dlp(formato)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            break
        except Exception as e:
            ultimo_error = e

    if info is None:
        raise ultimo_error if ultimo_error else RuntimeError("No se pudo extraer el audio")

    url_audio = info.get('url')
    if not url_audio and info.get('requested_formats'):
        # Si yt-dlp devuelve formato combinado, usamos el stream con audio.
        for fmt in info['requested_formats']:
            if fmt.get('acodec') and fmt.get('acodec') != 'none' and fmt.get('url'):
                url_audio = fmt['url']
                break

    if not url_audio:
        raise RuntimeError("No se encontró una URL de audio reproducible")

    titulo = info.get('title', 'Desconocido')
    before_options_track = construir_before_options(info)
    return url_audio, titulo, before_options_track


def voz_disponible():
    return bool(getattr(discord.voice_client, 'has_nacl', False))


def mensaje_error_voz():
    return (
        "❌ Falta soporte de voz (PyNaCl) para este proceso.\n"
        f"Python en uso: {sys.executable}\n"
        "Instala/reinstala con este comando y reinicia el bot:\n"
        f"{sys.executable} -m pip install --upgrade --force-reinstall pynacl"
    )

# Función para buscar en YouTube
def buscar_youtube_audio(query):
    ydl_opts = crear_opciones_yt_dlp('bestaudio/best', busqueda_por_defecto='ytsearch1')
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info and len(info['entries']) > 0:
            return f"https://www.youtube.com/watch?v={info['entries'][0]['id']}"
        elif 'webpage_url' in info:
            return info['webpage_url']
        return None

# Función para unirse al canal de voz
async def unirse_canal_voz(ctx):
    if not voz_disponible():
        await ctx.send(mensaje_error_voz())
        return None

    if ctx.author.voice:
        canal_voz = ctx.author.voice.channel
        canal_voz_objetivo[ctx.guild.id] = canal_voz.id
        return await canal_voz.connect()

    canal_id = canal_voz_objetivo.get(ctx.guild.id)
    if canal_id:
        canal_voz = bot.get_channel(canal_id)
        if canal_voz is not None:
            try:
                return await canal_voz.connect()
            except Exception:
                pass

    await ctx.send("¡Debes estar en un canal de voz!")
    return None

# Función para reproducir el siguiente audio en la cola
async def reproducir_siguiente(ctx, guild_id):
    if detener_reproduccion.get(guild_id):
        reproduccion_actual.pop(guild_id, None)
        return

    if colas_musica[guild_id].empty():
        reproduccion_actual.pop(guild_id, None)
        return

    siguiente_item = None
    url_audio = None
    titulo = 'Desconocido'
    before_options_track = ffmpeg_options['before_options']

    while not colas_musica[guild_id].empty() and not url_audio:
        siguiente = await colas_musica[guild_id].get()
        siguiente_item = siguiente
        item_url, item_titulo, item_before = descomponer_item_cola(siguiente)

        if isinstance(siguiente, dict) and siguiente.get('tipo') == 'youtube_pendiente':
            try:
                url_audio, titulo, before_options_track = await asyncio.to_thread(extraer_info_audio, item_url)
            except Exception as e:
                print(f"Omitiendo video no reproducible ({item_titulo}): {e}")
                continue
        else:
            url_audio, titulo, before_options_track = item_url, item_titulo, item_before

    if not url_audio:
        reproduccion_actual.pop(guild_id, None)
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client is None or not voice_client.is_connected():
        voice_client = await unirse_canal_voz(ctx)

    if voice_client is None:
        return

    def after_callback(error):
        if error:
            print(f"Error en reproducción: {error}")
        if detener_reproduccion.get(guild_id):
            detener_reproduccion.pop(guild_id, None)
            return
        asyncio.run_coroutine_threadsafe(reproducir_siguiente(ctx, guild_id), bot.loop)

    opciones_ffmpeg_track = dict(ffmpeg_options)
    opciones_ffmpeg_track['before_options'] = before_options_track

    try:
        voice_client.play(
            FFmpegPCMAudio(url_audio, executable=RUTA_FFMPEG, **opciones_ffmpeg_track),
            after=after_callback
        )
    except Exception as e:
        if siguiente_item is not None:
            colas_musica[guild_id]._queue.appendleft(siguiente_item)
        await ctx.send(f"❌ No pude iniciar la reproducción: {type(e).__name__}: {e}")
        reproduccion_actual.pop(guild_id, None)
        return

    reproduccion_actual[guild_id] = titulo
    await ctx.send(f"🎶 Reproduciendo: **{titulo}**")

@bot.command()
async def skip(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()  # Detiene la canción actual, activando el callback `after` para la siguiente
        await ctx.send("⏭ Canción saltada.")
    else:
        await ctx.send("No hay ninguna canción reproduciéndose.")

@bot.command()
async def eliminar(ctx, *, nombre: str):
    guild_id = ctx.guild.id
    if guild_id not in colas_musica:
        await ctx.send("No hay canciones en la cola.")
        return

    nueva_cola = asyncio.Queue()
    eliminada = False

    # Vaciamos la cola actual y buscamos coincidencia parcial
    while not colas_musica[guild_id].empty():
        cancion = await colas_musica[guild_id].get()
        _, titulo, _ = descomponer_item_cola(cancion)
        if nombre.lower() in titulo.lower() and not eliminada:
            eliminada = True
            await ctx.send(f"❌ Eliminado: **{titulo}**")
            continue
        await nueva_cola.put(cancion)

    colas_musica[guild_id] = nueva_cola

    if not eliminada:
        await ctx.send("No se encontró ninguna canción con ese nombre.")



@bot.command()
async def limpiar(ctx):
    guild_id = ctx.guild.id
    cancelar_precarga_playlist(guild_id)
    detener_reproduccion.pop(guild_id, None)
    if guild_id in colas_musica:
        while not colas_musica[guild_id].empty():
            await colas_musica[guild_id].get()
        await ctx.send("🧹 Cola de canciones limpiada.")
    else:
        await ctx.send("No hay cola que limpiar.")

@bot.command()
async def lista(ctx):
    guild_id = ctx.guild.id
    titulo_actual = reproduccion_actual.get(guild_id)
    pendientes_cache = len(cache_playlist_urls.get(guild_id, []))
    cola_vacia = guild_id not in colas_musica or colas_musica[guild_id].empty()

    if cola_vacia and not titulo_actual and pendientes_cache == 0:
        await ctx.send("📭 No hay canciones en la cola.")
        return

    mensaje = "**🎶 Estado de reproduccion:**\n"
    if titulo_actual:
        mensaje += f"▶️ Sonando ahora: {titulo_actual}\n\n"

    cola = list(colas_musica[guild_id]._queue) if guild_id in colas_musica else []
    if cola:
        mensaje += "**📝 Canciones en cola:**\n"
        for i, item in enumerate(cola, start=1):
            _, titulo, _ = descomponer_item_cola(item)
            mensaje += f"{i}. {titulo}\n"
    else:
        mensaje += "🧾 No hay canciones pendientes en cola.\n"

    if pendientes_cache:
        mensaje += f"\n📦 En cache por procesar: {pendientes_cache} URL(s).\n"

    await ctx.send(mensaje)

@bot.command()
async def comandos(ctx):
    mensaje = """
📜 **Comandos disponibles:**

🎵 `!play <nombre o link>` - Busca y reproduce música desde YouTube  
🛠 `!debugvoz` - Muestra estado interno de voz/cola/cache  
⏩ `!pahora` - Muestra las próximas 5 canciones  
⏭ `!last` - Salta a la ultima canción y borra el resto  
⏭ `!skip` - Salta la canción actual  
📝 `!lista` - Muestra la lista de canciones en cola  
❌ `!eliminar <nombre>` - Elimina una canción específica de la cola  
🧹 `!limpiar` - Limpia completamente la cola de canciones  
⏹ `!stop` - Detiene la reproducción  
👋 `!leave` - Sale del canal de voz  
📖 `!comandos` - Muestra esta lista de comandos
"""
    await ctx.send(mensaje)


@bot.command()
async def debugvoz(ctx):
    guild_id = ctx.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    cola_len = colas_musica[guild_id].qsize() if guild_id in colas_musica else 0
    cache_len = len(cache_playlist_urls.get(guild_id, []))
    tarea = tareas_precarga_playlist.get(guild_id)
    tarea_estado = "inactiva"
    if tarea is not None:
        if tarea.cancelled():
            tarea_estado = "cancelada"
        elif tarea.done():
            tarea_estado = "finalizada"
        else:
            tarea_estado = "activa"

    canal_objetivo = canal_voz_objetivo.get(guild_id)
    canal_actual = None
    conectado = False
    reproduciendo = False
    pausado = False

    if voice_client:
        conectado = bool(voice_client.is_connected())
        reproduciendo = bool(voice_client.is_playing())
        pausado = bool(voice_client.is_paused())
        canal_actual = getattr(getattr(voice_client, 'channel', None), 'id', None)

    titulo_actual = reproduccion_actual.get(guild_id, 'Ninguno')
    autor_en_voz = bool(getattr(ctx.author, 'voice', None) and getattr(ctx.author.voice, 'channel', None))

    mensaje = (
        "**🛠 Debug Voz**\n"
        f"Guild: {guild_id}\n"
        f"Autor en voz: {autor_en_voz}\n"
        f"Conectado: {conectado}\n"
        f"Canal actual: {canal_actual}\n"
        f"Canal objetivo: {canal_objetivo}\n"
        f"Reproduciendo: {reproduciendo}\n"
        f"Pausado: {pausado}\n"
        f"Sonando ahora: {titulo_actual}\n"
        f"Cola en memoria: {cola_len}\n"
        f"Cache playlist: {cache_len}\n"
        f"Precarga: {tarea_estado}"
    )
    await ctx.send(mensaje)


async def obtener_proximas_canciones(guild_id, limite=5):
    resultado = []

    cola = list(colas_musica[guild_id]._queue) if guild_id in colas_musica else []
    for item in cola:
        _, titulo, _ = descomponer_item_cola(item)
        resultado.append(titulo)
        if len(resultado) >= limite:
            return resultado

    cache = list(cache_playlist_urls.get(guild_id, []))
    for url_video in cache:
        try:
            _, titulo, _ = await asyncio.to_thread(extraer_info_audio, url_video)
            resultado.append(titulo)
        except Exception:
            resultado.append("[No reproducible]")

        if len(resultado) >= limite:
            break

    return resultado


@bot.command()
async def pahora(ctx):
    guild_id = ctx.guild.id
    proximas = await obtener_proximas_canciones(guild_id, limite=5)
    titulo_actual = reproduccion_actual.get(guild_id)

    if not proximas and not titulo_actual:
        await ctx.send("📭 No hay canciones para mostrar ahora mismo.")
        return

    mensaje = "**🎵 Pahora**\n"
    if titulo_actual:
        mensaje += f"▶️ Sonando ahora: {titulo_actual}\n"

    if proximas:
        mensaje += "\n**Próximas 5 canciones:**\n"
        for i, titulo in enumerate(proximas, start=1):
            mensaje += f"{i}. {titulo}\n"

    await ctx.send(mensaje)


@bot.command()
async def last(ctx):
    guild_id = ctx.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if guild_id not in colas_musica or colas_musica[guild_id].empty():
        await ctx.send("No hay canciones en cola para saltar a la ultima.")
        return

    cola = list(colas_musica[guild_id]._queue)
    ultima_cancion = cola[-1]

    nueva_cola = asyncio.Queue()
    await nueva_cola.put(ultima_cancion)
    colas_musica[guild_id] = nueva_cola

    cancelar_precarga_playlist(guild_id)
    cache_playlist_urls.pop(guild_id, None)
    tareas_precarga_playlist.pop(guild_id, None)

    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await ctx.send("⏭ Saltando a la ultima canción y limpiando el resto de la cola.")
    else:
        await ctx.send("⏭ Dejando solo la ultima canción y preparandola para reproducirse.")
        await reproducir_siguiente(ctx, guild_id)


# Comando: reproducir audio desde YouTube
@bot.command(name="play", aliases=["youtube", "p"])
async def play(ctx, *, nombre: str):
    try:
        if not voz_disponible():
            await ctx.send(mensaje_error_voz())
            return

        guild_id = ctx.guild.id
        if guild_id not in colas_musica:
            colas_musica[guild_id] = asyncio.Queue()

        if ctx.author.voice:
            canal_voz_objetivo[guild_id] = ctx.author.voice.channel.id

        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client is None or not voice_client.is_connected():
            voice_client = await unirse_canal_voz(ctx)
            if voice_client is None:
                return

        if nombre.strip().startswith(('http://', 'https://')) and obtener_playlist_id_youtube(nombre):
            await ctx.send("📚 Detecté un enlace con playlist. Cargando lista completa...")
            await cargar_playlist_en_cola(ctx, guild_id, voice_client, nombre)
            return

        if es_url_playlist_youtube(nombre):
            await cargar_playlist_en_cola(ctx, guild_id, voice_client, nombre)
            return

        consulta = normalizar_url_youtube(nombre)
        url = await asyncio.to_thread(buscar_youtube_audio, consulta)
        if not url:
            await ctx.send("No se encontró ningún video.")
            return

        url_audio, titulo, before_options_track = await asyncio.to_thread(extraer_info_audio, url)
        if voice_client and voice_client.is_playing():
            await colas_musica[guild_id].put((url_audio, titulo, before_options_track))
            await ctx.send(f"📝 Añadido a la cola: **{titulo}**")
        else:
            await colas_musica[guild_id].put((url_audio, titulo, before_options_track))
            await reproducir_siguiente(ctx, guild_id)

    except Exception as e:
        await ctx.send(f"❌ Error ({type(e).__name__}): {e}")


# Comando: detener reproducción
@bot.command()
async def stop(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    guild_id = ctx.guild.id

    cancelar_precarga_playlist(guild_id)

    if guild_id in colas_musica:
        while not colas_musica[guild_id].empty():
            await colas_musica[guild_id].get()

    reproduccion_actual.pop(guild_id, None)

    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        detener_reproduccion[guild_id] = True
        voice_client.stop()
        await ctx.send("⏹ Música detenida y cola limpiada.")
    else:
        detener_reproduccion.pop(guild_id, None)
        await ctx.send("No hay música reproduciéndose, pero la cola quedó limpia.")

# Comando: salir del canal de voz
@bot.command()
async def leave(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_connected():
        cancelar_precarga_playlist(ctx.guild.id)
        detener_reproduccion.pop(ctx.guild.id, None)
        await voice_client.disconnect()
        reproduccion_actual.pop(ctx.guild.id, None)
        canal_voz_objetivo.pop(ctx.guild.id, None)
        await ctx.send("👋 Desconectado del canal de voz.")
    else:
        await ctx.send("No estoy conectado a ningún canal de voz.")

# Mensaje de conexión
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user.name}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error

def main():
    try:
        bot.run(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print(
            "\n❌ Faltan intents privilegiados en Discord Developer Portal.\n"
            "Activa al menos: Bot -> Privileged Gateway Intents -> Message Content Intent.\n"
            "Si no vas a usar comandos con prefijo (!), también puedes desactivar intents.message_content en el código."
        )


if __name__ == "__main__":
    main()
