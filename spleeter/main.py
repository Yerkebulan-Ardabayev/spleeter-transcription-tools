import os
import sys
import subprocess
import shutil
import re  # Добавили модуль для умной сортировки
import time
from pydub import AudioSegment
import imageio_ffmpeg

# Фиксим кодировку консоли для Windows
if sys.platform == "win32":
    try:
        os.system('chcp 65001 >nul 2>&1')  # UTF-8 для консоли
    except:
        pass
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
    work_dir = "temp_work_folder"
    
    if not os.path.exists(work_dir):
        return None, []
    
    # Ищем файлы в рабочей директории
    files = os.listdir(work_dir)
    clean_files = [f for f in files if f.endswith('_clean.wav')]
    raw_files = [f for f in files if f.endswith('.wav') and not f.endswith('_clean.wav')]
    
    if not clean_files and not raw_files:
        return None, []
    
    # Определяем какое видео обрабатывалось
    # Ищем существующие _CLEAN.mp3 файлы чтобы понять какое видео не закончено
    video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm')
    all_videos = [f for f in os.listdir('.') if f.lower().endswith(video_extensions) and "_CLEAN" not in f]
    
    # Если есть временные файлы, проверяем какого видео нет в завершенных
    for video in all_videos:
        base_name = os.path.splitext(os.path.basename(video))[0]
        final_output = f"{base_name}_CLEAN.mp3"
        
        if not os.path.exists(final_output):
            # Это видео еще не завершено
            return video, clean_files
    
    # Если все видео обработаны, но есть временные файлы - возвращаем первое
    if all_videos:
        return all_videos[0], clean_files
    
    return None, []

# --- ФУНКЦИЯ АВТОПОИСКА ВИДЕО ---
def auto_find_video():
    video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm')
    
    files = [f for f in os.listdir('.') 
             if f.lower().endswith(video_extensions) 
             and "_CLEAN" not in f]

    # ПРИМЕНЯЕМ УМНУЮ СОРТИРОВКУ
    files.sort(key=smart_sort_key)

    if not files:
        print("[ОШИБКА] В этой папке нет видеофайлов!")
        return None
    
    if len(files) == 1:
        print(f"[*] Найден один файл: '{files[0]}'.")
        return files[0]
    
    while True:
        print("\n[*] Найдено несколько видео (отсортировано):")
        for i, f in enumerate(files):
            print(f"   {i+1}. {f}")
            
        try:
            choice = input("\nВведите НОМЕР файла (цифру): ").strip()
            idx = int(choice) - 1
            
            if 0 <= idx < len(files):
                selected_file = files[idx]
                print(f"\n[OK] Вы выбрали: {selected_file}")
                return selected_file
            else:
                print(f"[ОШИБКА] Нет файла с номером {choice}. Введите число от 1 до {len(files)}.")
        except ValueError:
            print("[ОШИБКА] Это не число. Попробуйте еще раз.")

# --------------------------------

def clean_voice_final_v2(video_filename):
    if not video_filename:
        return

    print(f"--- >>> НАЧИНАЕМ ОБРАБОТКУ: {video_filename} ---")
    
    AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    
    if os.path.exists("separated"):
        try:
            shutil.rmtree("separated")
        except:
            pass

    base_name = os.path.splitext(os.path.basename(video_filename))[0]
    final_output = f"{base_name}_CLEAN.mp3"
    
    CHUNK_MINUTES = 10 
    chunk_length_sec = CHUNK_MINUTES * 60
    work_dir = "temp_work_folder"
    
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    try:
        # Получаем длительность через ffprobe/ffmpeg
        probe_cmd = [
            ffmpeg_exe, "-i", video_filename,
            "-hide_banner"
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, errors='ignore')
        # ffmpeg выводит информацию в stderr
        # Проверяем наличие аудиодорожки
        has_audio = bool(re.search(r'Stream\s+#\d+:\d+.*Audio:', result.stderr))
        if not has_audio:
            print("[ОШИБКА] В этом видео НЕТ аудиодорожки! Нечего очищать.")
            return

        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', result.stderr)
        if duration_match:
            h, m, s, _ = duration_match.groups()
            duration = int(h) * 3600 + int(m) * 60 + int(s)
        else:
            print("[ОШИБКА] Не удалось определить длительность видео!")
            return

        print(f"[INFO] Длительность видео: {duration // 60:.0f} мин.")
        total_chunks = int(duration // chunk_length_sec) + 1
    except Exception as e:
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
        chunk_audio = os.path.join(work_dir, f"{chunk_name}.wav")
        chunk_clean = os.path.join(work_dir, f"{chunk_name}_clean.wav")
        
        # Прогресс в процентах
        progress = int((i / total_chunks) * 100)
        print(f"\n{'='*60}")
        print(f">>> [Часть {i+1} из {total_chunks}] ({progress}%) | {start_t/60:.1f}-{end_t/60:.1f} мин")
        print(f"{'='*60}")

        if os.path.exists(chunk_clean):
            processed_files.append(chunk_clean)
            print("   [OK] УЖЕ ОБРАБОТАНО (пропускаем)")
            continue

        # Проверяем есть ли уже извлеченное аудио
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
                    chunk_audio
                ]
                subprocess.run(extract_cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                err_text = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                print(f"[ОШИБКА] Ошибка нарезки: {err_text}")
                return
        else:
            print("   [OK] Аудио уже извлечено")

        print("   [AI] Нейросеть чистит голос... (это займет ~1 мин)")
        chunk_start = time.time()
        
        # Список размеров сегментов для попыток (workaround для pad1d assertion error)
        segment_sizes = [7, 5, 3, 10]
        demucs_success = False
        
        for seg_size in segment_sizes:
            # Очищаем separated перед каждой попыткой
            if os.path.exists("separated"):
                try:
                    shutil.rmtree("separated")
                except:
                    pass
            
            cmd = [
                sys.executable, "-m", "demucs", 
                "-n", "htdemucs", 
                "--two-stems=vocals",
                f"--segment={seg_size}",
                "--shifts=0", "-j", "0",
                chunk_audio
            ]
            
            try:
                subprocess.run(cmd, check=True, capture_output=True) 
                demucs_success = True
                break  # Успех — выходим из цикла попыток
            except subprocess.CalledProcessError as e:
                err_text = ""
                try:
                    err_text = e.stderr.decode('utf-8', errors='ignore')
                except:
                    err_text = str(e.stderr)
                
                if "assert" in err_text.lower() or "AssertionError" in err_text or "AssertionError" in err_text:
                    print(f"   [ПОВТОР] Сегмент {seg_size}s не подошёл, пробуем другой...")
                    continue
                else:
                    print(f"[ОШИБКА] Сбой нейросети (segment={seg_size}):")
                    print(err_text)
                    break  # Другая ошибка — не пытаемся дальше
            except Exception as ex:
                print(f"[ОШИБКА] Общая ошибка запуска: {ex}")
                break
        
        if not demucs_success:
            print(f"   [ПРОПУСК] Часть {i+1} не удалось обработать, переходим к следующей...")
            # Удаляем сырой файл чтобы повторить при перезапуске
            try:
                os.remove(chunk_audio)
            except:
                pass
            continue

        demucs_out = os.path.join("separated", "htdemucs", chunk_name, "vocals.wav")
        if os.path.exists(demucs_out):
            shutil.move(demucs_out, chunk_clean)
            processed_files.append(chunk_clean)
            
            chunk_time = time.time() - chunk_start
            print(f"   [OK] Кусок готов за {chunk_time:.1f} сек (segment={seg_size})")
            
            # Оценка оставшегося времени
            if i > 0:
                avg_time = (time.time() - start_time) / (i + 1)
                remaining = (total_chunks - i - 1) * avg_time
                print(f"   [INFO] Примерно осталось: {remaining/60:.1f} мин")
            
            try:
                shutil.rmtree("separated") 
                os.remove(chunk_audio)
            except:
                pass
        else:
            print(f"   [ПРОПУСК] Файл не появился после обработки, переходим дальше...")
            continue

    print(f"\n[*] Склеиваем всё в один файл...")
    try:
        combined = AudioSegment.empty()
        for f in processed_files:
            combined += AudioSegment.from_wav(f)
        
        print("[*] Сохраняем MP3 (128kbps)...")
        combined.export(final_output, format="mp3", bitrate="128k")
        
        try:
            shutil.rmtree(work_dir)
        except:
            pass
        
        print("\n" + "="*50)
        print(">>> АУДИО ОЧИЩЕНО!")
        print(f"[СОХРАНЕНО] Файл сохранен как: {final_output}")
        print("="*50)
        print("\n[INFO] Для транскрипции запустите: transcription/speechToText.py")
        print("   (поддерживает возобновление с места остановки)")

    except Exception as e:
        print(f"[ОШИБКА] Ошибка при сохранении: {e}")

if __name__ == "__main__":
    print("\n" + "="*60)
    print(">>> ОЧИСТКА ГОЛОСА В ВИДЕО (Demucs AI)")
    print("="*60)
    
    # Проверяем незаконченную работу
    unfinished_video, processed_parts = detect_unfinished_work()
    
    if unfinished_video:
        print(f"\n>>> ОБНАРУЖЕНА НЕЗАКОНЧЕННАЯ РАБОТА!")
        print(f"Видео: {unfinished_video}")
        print(f"Уже обработано частей: {len(processed_parts)}")
        print(f"\n>>> Продолжаем обработку...\n")
        clean_voice_final_v2(unfinished_video)
    else:
        found_video = auto_find_video()
        
        if found_video:
            clean_voice_final_v2(found_video)
        else:
            input("\nНажмите Enter, чтобы выйти...")