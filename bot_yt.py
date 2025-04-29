import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv
from discord import FFmpegPCMAudio

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Ruta a ffmpeg
RUTA_FFMPEG = "./ffmpeg/bin/ffmpeg.exe"

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

colas_musica = {}  # Diccionario con una cola por servidor

# Función para buscar en YouTube
def buscar_youtube_audio(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info and len(info['entries']) > 0:
            return f"https://www.youtube.com/watch?v={info['entries'][0]['id']}"
        elif 'webpage_url' in info:
            return info['webpage_url']
        return None

# Función para unirse al canal de voz
async def unirse_canal_voz(ctx):
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
    url_audio, titulo = siguiente

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

    voice_client.play(
        FFmpegPCMAudio(url_audio, executable=RUTA_FFMPEG, **ffmpeg_options),
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
        url, titulo = cancion
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
    for i, (_, titulo) in enumerate(cola, start=1):
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
        url = buscar_youtube_audio(nombre)
        if not url:
            await ctx.send("No se encontró ningún video.")
            return

        ydl_opts = {
            'format': 'bestaudio',
            'quiet': True,
            'noplaylist': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            url_audio = info['url']
            titulo = info.get('title', 'Desconocido')

        guild_id = ctx.guild.id
        if guild_id not in colas_musica:
            colas_musica[guild_id] = asyncio.Queue()

        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_playing():
            await colas_musica[guild_id].put((url_audio, titulo))
            await ctx.send(f"📝 Añadido a la cola: **{titulo}**")
        else:
            await colas_musica[guild_id].put((url_audio, titulo))
            await reproducir_siguiente(ctx, guild_id)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

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

# Ejecutar el bot
bot.run(TOKEN)