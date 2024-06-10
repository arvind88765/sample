import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import subprocess
import nest_asyncio
import time
import asyncio
import uvloop
from asyncio import get_event_loop_policy, set_event_loop_policy, DefaultEventLoopPolicy
import random

# Set uvloop as the default event loop policy
set_event_loop_policy(uvloop.EventLoopPolicy())

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Apply nest_asyncio
nest_asyncio.apply()

# Telegram API Credentials
api_id = 25450294
api_hash = "1a5ef99bb275c1f1e6e7f0ff33c3e8b5"
bot_token = "6216536325:AAE4dTlIA3-8PYcJnireGCpwCqvIBLHE9Zw"

# Initialize Pyrogram Client
app = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Store message IDs for audio trimming and merging
audio_message_ids = {}
audio_files_to_merge = {}
audio_trim_sessions = {}
video_sample_sessions = {}
video_compress_sessions = {}

# Handler for /start command
@app.on_message(filters.command("start"))
async def start_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Video Sample Generator", callback_data="video_sample_generator")],
        [InlineKeyboardButton("Audio Trimmer", callback_data="audio_trimmer")],
        [InlineKeyboardButton("Audio Merger", callback_data="audio_merger")],
        [InlineKeyboardButton("Video Compressor", callback_data="video_compressor")]
    ])
    await message.reply("Please choose an option:", reply_markup=keyboard)

# Callback query handler for video sample generator
@app.on_callback_query(filters.regex(r"video_sample_generator"))
async def video_sample_generator(client, callback_query):
    user_id = callback_query.from_user.id
    video_sample_sessions[user_id] = {'file': None}
    await callback_query.message.edit_text("Send a video file to generate a sample.")

# Callback query handler for audio trimmer
@app.on_callback_query(filters.regex(r"audio_trimmer"))
async def audio_trimmer(client, callback_query):
    user_id = callback_query.from_user.id
    audio_trim_sessions[user_id] = {'file': None, 'start_time': None, 'end_time': None}
    await callback_query.message.edit_text("Send an audio file to trim.")

# Callback query handler for audio merger
@app.on_callback_query(filters.regex(r"audio_merger"))
async def audio_merger(client, callback_query):
    user_id = callback_query.from_user.id
    audio_files_to_merge[user_id] = {'num_files': None, 'received_files': []}
    await callback_query.message.edit_text("How many audio files would you like to merge? Please provide a number.")

# Callback query handler for video compressor
@app.on_callback_query(filters.regex(r"video_compressor"))
async def video_compressor(client, callback_query):
    user_id = callback_query.from_user.id
    video_compress_sessions[user_id] = {'file': None}
    await callback_query.message.edit_text("Send a video file to compress.")

# Custom filter to exclude commands
def exclude_commands(_, __, message):
    return not message.text.startswith("/")

# Handler for number of files for audio merger
@app.on_message(filters.text & filters.create(exclude_commands))
async def handle_number_of_files(client, message):
    user_id = message.from_user.id
    if user_id in audio_files_to_merge and audio_files_to_merge[user_id]['num_files'] is None:
        try:
            num_files = int(message.text)
            if num_files > 0:
                audio_files_to_merge[user_id]['num_files'] = num_files
                await message.reply(f"Please send {num_files} audio files for merging.")
            else:
                await message.reply("Please provide a valid number of files.")
        except ValueError:
            await message.reply("Please provide a valid number.")
    elif user_id in audio_trim_sessions and audio_trim_sessions[user_id]['file'] is None:
        await message.reply("Please send an audio file to trim first.")
    elif user_id in audio_trim_sessions and audio_trim_sessions[user_id]['start_time'] is None:
        if validate_timestamp(message.text):
            audio_trim_sessions[user_id]['start_time'] = message.text
            await message.reply("Now send the end timestamp (HH:MM:SS) for trimming.")
        else:
            await message.reply("Invalid timestamp format. Please use HH:MM:SS.")
    elif user_id in audio_trim_sessions and audio_trim_sessions[user_id]['end_time'] is None:
        if validate_timestamp(message.text):
            audio_trim_sessions[user_id]['end_time'] = message.text
            await trim_audio_file(client, message)
        else:
            await message.reply("Invalid timestamp format. Please use HH:MM:SS.")
    else:
        await message.reply("Please start by selecting an option using /start.")

# Handler for audio messages
@app.on_message(filters.audio)
async def handle_audio(client, message):
    user_id = message.from_user.id
    if user_id in audio_files_to_merge:
        if len(audio_files_to_merge[user_id]['received_files']) < audio_files_to_merge[user_id]['num_files']:
            audio_files_to_merge[user_id]['received_files'].append(message)
            if len(audio_files_to_merge[user_id]['received_files']) == audio_files_to_merge[user_id]['num_files']:
                await merge_audio_files(client, message)
        else:
            await message.reply("You have already sent the required number of files.")
    elif user_id in audio_trim_sessions:
        audio_trim_sessions[user_id]['file'] = message
        await message.reply("Please send the start timestamp (HH:MM:SS) for trimming.")
    else:
        await message.reply("Please select an option using /start first.")

# Handler for video messages
@app.on_message(filters.video | filters.document)
async def handle_video(client, message):
    user_id = message.from_user.id
    if user_id in video_sample_sessions and video_sample_sessions[user_id]['file'] is None:
        video_sample_sessions[user_id]['file'] = message
        await generate_video_sample(client, message)
    elif user_id in video_compress_sessions and video_compress_sessions[user_id]['file'] is None:
        video_compress_sessions[user_id]['file'] = message
        await compress_video_file(client, message)
    else:
        await message.reply("Please select an option using /start first.")

# Function to validate timestamp format
def validate_timestamp(timestamp):
    try:
        time.strptime(timestamp, '%H:%M:%S')
        return True
    except ValueError:
        return False

# Function to merge audio files
async def merge_audio_files(client, message):
    user_id = message.from_user.id
    audio_messages = audio_files_to_merge[user_id]['received_files']
    output_file = f"merged_{user_id}.mp3"
    input_files = []

    try:
        status_msg = await message.reply("Starting audio merge...")

        # Download all audio files
        last_update_time = time.time()
        for i, audio_message in enumerate(audio_messages):
            async def progress_callback(current, total):
                nonlocal last_update_time
                if time.time() - last_update_time > 1:  # Update every 1 second
                    await status_msg.edit_text(f"Downloading audio {i+1}/{len(audio_messages)}... {current / total * 100:.1f}%")
                    last_update_time = time.time()
            file_path = await audio_message.download(progress=progress_callback)
            input_files.append(file_path)

        await status_msg.edit_text("All audio files downloaded.\nMerging audio files...")

        # Temporarily switch to the default event loop policy for handling subprocess
        original_policy = get_event_loop_policy()
        set_event_loop_policy(DefaultEventLoopPolicy())

        # Merge audio files using ffmpeg
        ffmpeg_cmd = ["ffmpeg"]
        for input_file in input_files:
            ffmpeg_cmd.extend(["-i", input_file])
        ffmpeg_cmd.extend(["-filter_complex", f"concat=n={len(input_files)}:v=0:a=1", "-c:a", "libmp3lame", output_file])
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Log ffmpeg output
        async for line in process.stderr:
            logger.info(line.decode().strip())
        await process.communicate()

        # Switch back to uvloop
        set_event_loop_policy(original_policy)

        await status_msg.edit_text("Merging completed.\nUploading merged audio...")

        # Upload merged audio
        await client.send_audio(
            chat_id=message.chat.id,
            audio=output_file,
            caption="Merged audio"
        )

        # Final update
        await status_msg.edit_text("Merged audio uploaded!")
    except Exception as e:
        logger.error(f"Error during audio merge: {e}")
        await message.reply("An error occurred during the audio merge.")
    finally:
        # Cleanup
        for input_file in input_files:
            if os.path.exists(input_file):
                os.remove(input_file)
        if os.path.exists(output_file):
            os.remove(output_file)
        audio_files_to_merge.pop(user_id, None)

# Function to trim audio file
async def trim_audio_file(client, message):
    user_id = message.from_user.id
    audio_message = audio_trim_sessions[user_id]['file']
    start_time = audio_trim_sessions[user_id]['start_time']
    end_time = audio_trim_sessions[user_id]['end_time']
    output_file = f"trimmed_{user_id}.mp3"

    try:
        status_msg = await message.reply("Downloading audio file...")

        last_update_time = time.time()
        async def progress_callback(current, total):
            nonlocal last_update_time
            if time.time() - last_update_time > 1:  # Update every 1 second
                await status_msg.edit_text(f"Downloading audio file... {current / total * 100:.1f}%")
                last_update_time = time.time()

        file_path = await audio_message.download(progress=progress_callback)
        await status_msg.edit_text("Audio file downloaded.\nTrimming audio file...")

        # Temporarily switch to the default event loop policy for handling subprocess
        original_policy = get_event_loop_policy()
        set_event_loop_policy(DefaultEventLoopPolicy())

        # Trim audio using ffmpeg
        ffmpeg_cmd = [
            "ffmpeg", "-i", file_path, "-ss", start_time, "-to", end_time,
            "-c", "copy", output_file
        ]
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Log ffmpeg output
        async for line in process.stderr:
            logger.info(line.decode().strip())
        await process.communicate()

        # Switch back to uvloop
        set_event_loop_policy(original_policy)

        await status_msg.edit_text("Trimming completed.\nUploading trimmed audio...")

        # Upload trimmed audio
        await client.send_audio(
            chat_id=message.chat.id,
            audio=output_file,
            caption="Trimmed audio"
        )

        # Final update
        await status_msg.edit_text("Trimmed audio uploaded!")
    except Exception as e:
        logger.error(f"Error during audio trimming: {e}")
        await message.reply("An error occurred during the audio trimming.")
    finally:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(output_file):
            os.remove(output_file)
        audio_trim_sessions.pop(user_id, None)

# Function to generate video sample
async def generate_video_sample(client, message):
    user_id = message.from_user.id
    video_message = video_sample_sessions[user_id]['file']
    output_file = f"sample_{user_id}.mp4"

    try:
        status_msg = await message.reply("Downloading video file...")

        last_update_time = time.time()
        async def progress_callback(current, total):
            nonlocal last_update_time
            if time.time() - last_update_time > 1:  # Update every 1 second
                await status_msg.edit_text(f"Downloading video file... {current / total * 100:.1f}%")
                last_update_time = time.time()

        file_path = await video_message.download(progress=progress_callback)
        await status_msg.edit_text("Video file downloaded.\nGenerating video sample...")

        # Temporarily switch to the default event loop policy for handling subprocess
        original_policy = get_event_loop_policy()
        set_event_loop_policy(DefaultEventLoopPolicy())

        # Generate video sample using ffmpeg
        ffmpeg_cmd = [
            "ffmpeg", "-i", file_path, "-t", "30", "-c", "copy", output_file
        ]
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Log ffmpeg output
        async for line in process.stderr:
            logger.info(line.decode().strip())
        await process.communicate()

        # Switch back to uvloop
        set_event_loop_policy(original_policy)

        await status_msg.edit_text("Sample generation completed.\nUploading video sample...")

        # Upload video sample
        await client.send_video(
            chat_id=message.chat.id,
            video=output_file,
            caption="Video sample"
        )

        # Final update
        await status_msg.edit_text("Video sample uploaded!")
    except Exception as e:
        logger.error(f"Error during video sample generation: {e}")
        await message.reply("An error occurred during the video sample generation.")
    finally:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(output_file):
            os.remove(output_file)
        video_sample_sessions.pop(user_id, None)

# Function to compress video file
async def compress_video_file(client, message):
    user_id = message.from_user.id
    video_message = video_compress_sessions[user_id]['file']
    output_file = f"compressed_{user_id}.mp4"

    try:
        status_msg = await message.reply("Downloading video file...")

        last_update_time = time.time()
        async def progress_callback(current, total):
            nonlocal last_update_time
            if time.time() - last_update_time > 1:  # Update every 1 second
                await status_msg.edit_text(f"Downloading video file... {current / total * 100:.1f}%")
                last_update_time = time.time()

        file_path = await video_message.download(progress=progress_callback)
        await status_msg.edit_text("Video file downloaded.\nCompressing video file...")

        # Temporarily switch to the default event loop policy for handling subprocess
        original_policy = get_event_loop_policy()
        set_event_loop_policy(DefaultEventLoopPolicy())

        # Compress video using ffmpeg
        ffmpeg_cmd = [
            "ffmpeg", "-i", file_path, "-vcodec", "libx265", "-crf", "28", "-preset", "fast", output_file
        ]
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Track progress
        last_progress = 0
        async for line in process.stderr:
            line = line.decode().strip()
            if "frame=" in line:
                progress = int(line.split('frame=')[1].split('fps=')[0].strip())
                if progress != last_progress:
                    last_progress = progress
                    await status_msg.edit_text(f"Compressing video file... {progress / 100:.1f}%")
            logger.info(line)
        await process.communicate()

        # Switch back to uvloop
        set_event_loop_policy(original_policy)

        await status_msg.edit_text("Compression completed.\nUploading compressed video...")

        # Upload compressed video
        await client.send_video(
            chat_id=message.chat.id,
            video=output_file,
            caption="Compressed video"
        )

        # Final update
        await status_msg.edit_text("Compressed video uploaded!")
    except Exception as e:
        logger.error(f"Error during video compression: {e}")
        await message.reply("An error occurred during the video compression.")
    finally:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(output_file):
            os.remove(output_file)
        video_compress_sessions.pop(user_id, None)

# Main function to run the bot
async def main():
    await app.start()

    # Create an asyncio event to keep the bot running
    stop_event = asyncio.Event()
    await stop_event.wait()

    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
