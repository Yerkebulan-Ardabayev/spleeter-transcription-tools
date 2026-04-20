import os
import sys
import subprocess
import shutil
import re  # Добавили модуль для умной сортировки
import math
import time
import contextlib
from pydub import AudioSegment
import imageio_ffmpeg

# --- КОНСТАНТЫ ---
CHUNK_MINUTES = 10
WORK_DIR = "temp_work_folder"
SEPARATED_DIR = "separated"
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.webm')
DEMUCS_SEGMENT_SIZES = [7, 5, 3, 10]  # workaround для pad1d assertion error

# Фиксим кодировку консоли для Windows
if sys.platform == "win32":
    with contextlib.suppress(OSError):
        os.system('chcp 65001 >nul 2>&1')  # UTF-8 для консоли
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# --- ФУНКЦИЯ УМНОЙ СОРТИРОВКИ ---
def smart_sort_key(filename):
    # 1. Заменяем точки и символы на пробелы, чтобы "ч.1" и "ч 2" стали похожи
    clean_name = filename.replace('.', ' ').replace('_', ' ')
    # 2. Разбиваем текст на куски: буквы отдельно, цифры отдельно
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', clean_name)]

# --- ФУНКЦИЯ ОПРЕДЕЛЕНИЯ НЕЗАКОНЧЕННОЙ РАБОТЫ ---
def detect_unfinished_work():
    """Проверяет наличие временных файлов и определяет незаконченную работу"""
    if not os.path.exists(WORK_DIR):
        return None, []

    files = os.listdir(WORK_DIR)
    clean_files = [f for f in files if f.endswith('_clean.wav')]
    raw_files = [f for f in files if f.endswith('.wav') and not f.endswith('_clean.wav')]

    if not clean_files and not raw_files:
        return None, []

    all_videos = [f for f in os.listdir('.') if f.lower().endswith(VIDEO_EXTENSIONS) and "_CLEAN" not in f]

    # Ищем видео, у которого ещё нет финального _CLEAN.mp3
    for video in all_videos:
        base_name = os.path.splitext(os.path.basename(video))[0]
        if not os.path.exists(f"{base_name}_CLEAN.mp3"):
            return video, clean_files

    if all_videos:
        return all_videos[0], clean_files

    return None, []

# --- ФУНКЦИЯ ПОИСКА НЕОБРАБОТАННЫХ ВИДЕО ---
def find_videos_to_process():
    """Список всех видео в папке, у которых ещё нет финального _CLEAN.mp3."""
    all_files = [f for f in os.listdir('.')
                 if f.lower().endswith(VIDEO_EXTENSIONS)
                 and "_CLEAN" not in f]

    # Фильтруем уже обработанные
    pending = []
    done = []
    for f in all_files:
        base_name = os.path.splitext(os.path.basename(f))[0]
        if os.path.exists(f"{base_name}_CLEAN.mp3"):
            done.append(f)
        else:
            pending.append(f)

    pending.sort(key=smart_sort_key)
    done.sort(key=smart_sort_key)

    if done:
        print(f"[*] Уже обработано: {len(done)} (пропускаем)")
    return pending

# --------------------------------

def _clear_separated():
    if os.path.exists(SEPARATED_DIR):
        with contextlib.suppress(OSError):
            shutil.rmtree(SEPARATED_DIR)


def clean_voice_final_v2(video_filename):
    if not video_filename:
        return

    print(f"--- >>> НАЧИНАЕМ ОБРАБОТКУ: {video_filename} ---")

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    AudioSegment.converter = ffmpeg_exe

    _clear_separated()

    base_name = os.path.splitext(os.path.basename(video_filename))[0]
    final_output = f"{base_name}_CLEAN.mp3"

    chunk_length_sec = CHUNK_MINUTES * 60
    os.makedirs(WORK_DIR, exist_ok=True)

    try:
        # Получаем длительность и проверяем наличие аудиодорожки через ffmpeg
        probe_cmd = [ffmpeg_exe, "-i", video_filename, "-hide_banner"]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, errors='ignore')

        has_audio = bool(re.search(r'Stream\s+#\d+:\d+.*Audio:', result.stderr))
        if not has_audio:
            print("[ОШИБКА] В этом видео НЕТ аудиодорожки! Нечего очищать.")
            return

        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', result.stderr)
        if not duration_match:
            print("[ОШИБКА] Не удалось определить длительность видео!")
            return

        h, m, s, _ = duration_match.groups()
        duration = int(h) * 3600 + int(m) * 60 + int(s)

        print(f"[INFO] Длительность видео: {duration // 60:.0f} мин.")
        total_chunks = max(1, math.ceil(duration / chunk_length_sec))
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[ОШИБКА] Ошибка открытия видео: {e}")
        return

    processed_files = []
    start_time = time.time()

    for i in range(total_chunks):
        start_t = i * chunk_length_sec
        end_t = min((i + 1) * chunk_length_sec, duration)

        if start_t >= duration:
            break

        chunk_name = f"part_{i}"
        chunk_audio = os.path.join(WORK_DIR, f"{chunk_name}.wav")
        chunk_clean = os.path.join(WORK_DIR, f"{chunk_name}_clean.wav")

        progress = int(((i + 1) / total_chunks) * 100)
        print(f"\n{'='*60}")
        print(f">>> [Часть {i+1} из {total_chunks}] ({progress}%) | {start_t/60:.1f}-{end_t/60:.1f} мин")
        print(f"{'='*60}")

        if os.path.exists(chunk_clean):
            processed_files.append(chunk_clean)
            print("   [OK] УЖЕ ОБРАБОТАНО (пропускаем)")
            continue

        if not os.path.exists(chunk_audio):
            print("   [*] Извлекаем аудио из видео...")
            try:
                extract_cmd = [
                    ffmpeg_exe, "-y",
                    "-ss", str(start_t),
                    "-to", str(end_t),
                    "-i", video_filename,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "44100", "-ac", "2",
                    chunk_audio,
                ]
                subprocess.run(extract_cmd, check=True, capture_output=True, text=True, errors='ignore')
            except subprocess.CalledProcessError as e:
                print(f"[ОШИБКА] Ошибка нарезки: {e.stderr or e}")
                return
        else:
            print("   [OK] Аудио уже извлечено")

        print("   [AI] Нейросеть чистит голос... (это займет ~1 мин)")
        chunk_start = time.time()

        demucs_success = False
        seg_size = None

        for seg_size in DEMUCS_SEGMENT_SIZES:
            _clear_separated()

            cmd = [
                sys.executable, "-m", "demucs",
                "-n", "htdemucs",
                "--two-stems=vocals",
                f"--segment={seg_size}",
                "--shifts=0", "-j", "0",
                chunk_audio,
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, errors='ignore')
                demucs_success = True
                break
            except subprocess.CalledProcessError as e:
                err_text = e.stderr or ""
                if "assert" in err_text.lower():
                    print(f"   [ПОВТОР] Сегмент {seg_size}s не подошёл, пробуем другой...")
                    continue
                print(f"[ОШИБКА] Сбой нейросети (segment={seg_size}):")
                print(err_text)
                break
            except OSError as ex:
                print(f"[ОШИБКА] Общая ошибка запуска: {ex}")
                break

        if not demucs_success:
            print(f"   [ПРОПУСК] Часть {i+1} не удалось обработать, переходим к следующей...")
            with contextlib.suppress(OSError):
                os.remove(chunk_audio)
            continue

        demucs_out = os.path.join(SEPARATED_DIR, "htdemucs", chunk_name, "vocals.wav")
        if os.path.exists(demucs_out):
            shutil.move(demucs_out, chunk_clean)
            processed_files.append(chunk_clean)

            chunk_time = time.time() - chunk_start
            print(f"   [OK] Кусок готов за {chunk_time:.1f} сек (segment={seg_size})")

            if i > 0:
                avg_time = (time.time() - start_time) / (i + 1)
                remaining = (total_chunks - i - 1) * avg_time
                print(f"   [INFO] Примерно осталось: {remaining/60:.1f} мин")

            _clear_separated()
            with contextlib.suppress(OSError):
                os.remove(chunk_audio)
        else:
            print(f"   [ПРОПУСК] Файл не появился после обработки, переходим дальше...")
            continue

    if not processed_files:
        print("\n[ОШИБКА] Нет обработанных частей — нечего склеивать.")
        return

    print(f"\n[*] Склеиваем всё в один файл...")
    try:
        combined = AudioSegment.empty()
        for f in processed_files:
            combined += AudioSegment.from_wav(f)

        print("[*] Сохраняем MP3 (128kbps)...")
        combined.export(final_output, format="mp3", bitrate="128k")

        with contextlib.suppress(OSError):
            shutil.rmtree(WORK_DIR)

        print("\n" + "="*50)
        print(">>> АУДИО ОЧИЩЕНО!")
        print(f"[СОХРАНЕНО] Файл сохранен как: {final_output}")
        print("="*50)
        print("\n[INFO] Для транскрипции запустите: audio-transcriber/speechToText.py")
        print("   (поддерживает возобновление с места остановки)")

    except (OSError, ValueError) as e:
        print(f"[ОШИБКА] Ошибка при сохранении: {e}")

if __name__ == "__main__":
    print("\n" + "="*60)
    print(">>> ОЧИСТКА ГОЛОСА В ВИДЕО (Demucs AI) — BATCH MODE")
    print("="*60)

    # 1. Если есть прерванная работа — сначала дообработать её
    unfinished_video, processed_parts = detect_unfinished_work()
    processed_this_run = set()

    if unfinished_video:
        print(f"\n>>> ОБНАРУЖЕНА НЕЗАКОНЧЕННАЯ РАБОТА!")
        print(f"Видео: {unfinished_video}")
        print(f"Уже обработано частей: {len(processed_parts)}")
        print(f"\n>>> Продолжаем с того места...\n")
        clean_voice_final_v2(unfinished_video)
        processed_this_run.add(unfinished_video)

    # 2. Пройти по всем остальным необработанным видео
    pending = [v for v in find_videos_to_process() if v not in processed_this_run]

    if not pending:
        if not unfinished_video:
            print("\n[*] Нет видео для обработки (либо все уже сделаны).")
        else:
            print("\n" + "="*60)
            print(">>> ВСЁ ОБРАБОТАНО!")
            print("="*60)
        input("\nНажмите Enter, чтобы выйти...")
    else:
        print(f"\n>>> НАЙДЕНО {len(pending)} видео для обработки (по очереди):")
        for i, v in enumerate(pending, 1):
            print(f"   {i}. {v}")

        for i, video in enumerate(pending, 1):
            print(f"\n{'#'*60}")
            print(f"### ФАЙЛ {i}/{len(pending)}: {video}")
            print(f"{'#'*60}")
            clean_voice_final_v2(video)

        print("\n" + "="*60)
        print(f">>> ВСЕ {len(pending)} ФАЙЛОВ ОБРАБОТАНЫ!")
        print("="*60)
        input("\nНажмите Enter, чтобы выйти...")