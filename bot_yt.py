import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import shutil
import sys
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
RUTA_FFMPEG = "./ffmpeg/bin/ffmpeg.exe"

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

colas_musica = {}  # Diccionario con una cola por servidor


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
    if isinstance(item, tuple):
        if len(item) == 3:
            return item[0], item[1], item[2]
        if len(item) == 2:
            return item[0], item[1], ffmpeg_options['before_options']
    return None, 'Desconocido', ffmpeg_options['before_options']


def crear_opciones_yt_dlp(formato, busqueda_por_defecto=None):
    node_path = shutil.which("node")
    opciones = {
        'format': formato,
        'noplaylist': True,
        'quiet': True,
        'remote_components': ['ejs:github']
    }

    if node_path:
        opciones['js_runtimes'] = {'node': {'path': node_path}}

    if busqueda_por_defecto:
        opciones['default_search'] = busqueda_por_defecto

    return opciones


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
        return await canal_voz.connect()
    else:
        await ctx.send("¡Debes estar en un canal de voz!")
        return None

# Función para reproducir el siguiente audio en la cola
async def reproducir_siguiente(ctx, guild_id):
    if colas_musica[guild_id].empty():
        return

    siguiente = await colas_musica[guild_id].get()
    url_audio, titulo, before_options_track = descomponer_item_cola(siguiente)

    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client is None or not voice_client.is_connected():
        voice_client = await unirse_canal_voz(ctx)

    if voice_client is None:
        return

    def after_callback(error):
        if error:
            print(f"Error en reproducción: {error}")
        fut = asyncio.run_coroutine_threadsafe(reproducir_siguiente(ctx, guild_id), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Error en after: {e}")

    opciones_ffmpeg_track = dict(ffmpeg_options)
    opciones_ffmpeg_track['before_options'] = before_options_track

    voice_client.play(
        FFmpegPCMAudio(url_audio, executable=RUTA_FFMPEG, **opciones_ffmpeg_track),
        after=after_callback
    )
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
    if guild_id in colas_musica:
        while not colas_musica[guild_id].empty():
            await colas_musica[guild_id].get()
        await ctx.send("🧹 Cola de canciones limpiada.")
    else:
        await ctx.send("No hay cola que limpiar.")

@bot.command()
async def lista(ctx):
    guild_id = ctx.guild.id
    if guild_id not in colas_musica or colas_musica[guild_id].empty():
        await ctx.send("📭 No hay canciones en la cola.")
        return

    cola = list(colas_musica[guild_id]._queue)
    mensaje = "**🎶 Canciones en cola:**\n"
    for i, item in enumerate(cola, start=1):
        _, titulo, _ = descomponer_item_cola(item)
        mensaje += f"{i}. {titulo}\n"

    await ctx.send(mensaje)

@bot.command()
async def comandos(ctx):
    mensaje = """
📜 **Comandos disponibles:**

🎵 `!youtube <nombre o link>` - Busca y reproduce música desde YouTube  
⏭ `!skip` - Salta la canción actual  
📝 `!lista` - Muestra la lista de canciones en cola  
❌ `!eliminar <nombre>` - Elimina una canción específica de la cola  
🧹 `!limpiar` - Limpia completamente la cola de canciones  
⏹ `!stop` - Detiene la reproducción  
👋 `!leave` - Sale del canal de voz  
📖 `!comandos` - Muestra esta lista de comandos
"""
    await ctx.send(mensaje)


# Comando: reproducir audio desde YouTube
@bot.command()
async def youtube(ctx, *, nombre: str):
    try:
        if not voz_disponible():
            await ctx.send(mensaje_error_voz())
            return

        url = buscar_youtube_audio(nombre)
        if not url:
            await ctx.send("No se encontró ningún video.")
            return

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

        guild_id = ctx.guild.id
        if guild_id not in colas_musica:
            colas_musica[guild_id] = asyncio.Queue()

        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
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
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("⏹ Música detenida.")
    else:
        await ctx.send("No hay música reproduciéndose.")

# Comando: salir del canal de voz
@bot.command()
async def leave(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await ctx.send("👋 Desconectado del canal de voz.")
    else:
        await ctx.send("No estoy conectado a ningún canal de voz.")

# Mensaje de conexión
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user.name}")

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
