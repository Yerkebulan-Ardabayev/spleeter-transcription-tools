import os
import subprocess
import shutil

# --- НАСТРОЙКИ ---
SPLIT_TIME_MIN = 40  # Длительность одной части в минутах
SPLIT_TIME_SEC = SPLIT_TIME_MIN * 60

# Путь к FFmpeg. Можно переопределить через env var FFMPEG_PATH.
HARDCODED_FFMPEG = os.environ.get(
    "FFMPEG_PATH",
    r"C:\ffmpeg-2025-10-12-git-0bc54cddb1-essentials_build\ffmpeg-2025-10-12-git-0bc54cddb1-essentials_build\bin\ffmpeg.exe",
)

def get_ffmpeg_path() -> str | None:
    local_ffmpeg = os.path.join(os.getcwd(), "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
    if os.path.exists(HARDCODED_FFMPEG):
        return HARDCODED_FFMPEG
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    return None

def get_duration(ffmpeg_path: str, file_path: str) -> float:
    ffprobe_path = ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe")
    if not os.path.exists(ffprobe_path):
        ffprobe_path = "ffprobe"
    cmd = [
        ffprobe_path, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        print(f"⚠️  Не удалось определить длительность '{file_path}': {e}")
        return 0.0

def split_video_by_time(ffmpeg_path: str, input_file: str) -> None:
    base_name, ext = os.path.splitext(input_file)
    duration = get_duration(ffmpeg_path, input_file)

    if duration <= 0:
        print(f"⚠️  Пропускаем '{input_file}' — длительность неизвестна.")
        return

    duration_min = duration / 60
    if duration_min <= SPLIT_TIME_MIN:
        print(f"✅ {input_file} короче {SPLIT_TIME_MIN} мин ({duration_min:.1f} мин). Пропускаем.")
        return

    print(f"\n✂️ Обработка: {input_file} ({duration_min:.1f} мин)")
    output_pattern = f"{base_name}_part_%03d{ext}"

    # -map 0 — все дорожки, -c copy — без перекодировки
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "warning",
        "-i", input_file, "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(SPLIT_TIME_SEC),
        "-reset_timestamps", "1", output_pattern,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✨ Готово! Файлы: {base_name}_part_XXX{ext}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка ffmpeg: {e.stderr or e}")

def main():
    # --- ВАЖНОЕ ИСПРАВЛЕНИЕ: ПЕРЕХОДИМ В ПАПКУ СКРИПТА ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    # -----------------------------------------------------

    print(f"--- 🚀 AUTO SPLITTER ({SPLIT_TIME_MIN} min) ---")
    print(f"📂 Рабочая папка: {script_dir}")
    
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        print("❌ FFmpeg не найден!")
        input("Нажмите Enter...")
        return

    video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v')
    # Ищем файлы уже в правильной папке
    files = [f for f in os.listdir('.') if f.lower().endswith(video_extensions)]
    
    # Сортируем файлы (чтобы сначала шли part_001, если есть)
    files.sort()

    found_work = False
    for f in files:
        if "_part_" in f: continue
        found_work = True
        split_video_by_time(ffmpeg, f)

    if not found_work:
        print("📂 Подходящие видеофайлы не найдены (или они уже нарезаны).")

    print("\n🏁 Работа завершена.")
    input("Нажмите Enter, чтобы выйти...")

if __name__ == "__main__":
    main()