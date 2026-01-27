import os
import sys
import subprocess
import shutil
import re  # Добавили модуль для умной сортировки
from moviepy import VideoFileClip
from pydub import AudioSegment
import imageio_ffmpeg

# --- ФУНКЦИЯ УМНОЙ СОРТИРОВКИ ---
def smart_sort_key(filename):
    # 1. Заменяем точки и символы на пробелы, чтобы "ч.1" и "ч 2" стали похожи
    clean_name = filename.replace('.', ' ').replace('_', ' ')
    # 2. Разбиваем текст на куски: буквы отдельно, цифры отдельно
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', clean_name)]

# --- ФУНКЦИЯ АВТОПОИСКА ВИДЕО ---
def auto_find_video():
    video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm')
    
    files = [f for f in os.listdir('.') 
             if f.lower().endswith(video_extensions) 
             and "_CLEAN" not in f]

    # ПРИМЕНЯЕМ УМНУЮ СОРТИРОВКУ
    files.sort(key=smart_sort_key)

    if not files:
        print("❌ В этой папке нет видеофайлов!")
        return None
    
    if len(files) == 1:
        print(f"🔎 Найден один файл: '{files[0]}'.")
        return files[0]
    
    while True:
        print("\n🔎 Найдено несколько видео (отсортировано):")
        for i, f in enumerate(files):
            print(f"   {i+1}. {f}")
            
        try:
            choice = input("\nВведите НОМЕР файла (цифру): ").strip()
            idx = int(choice) - 1
            
            if 0 <= idx < len(files):
                selected_file = files[idx]
                print(f"\n✅ Вы выбрали: {selected_file}")
                return selected_file
            else:
                print(f"❌ Нет файла с номером {choice}. Введите число от 1 до {len(files)}.")
        except ValueError:
            print("❌ Это не число. Попробуйте еще раз.")

# --------------------------------

def clean_voice_final_v2(video_filename):
    if not video_filename:
        return

    print(f"--- 🚀 НАЧИНАЕМ ОБРАБОТКУ: {video_filename} ---")
    
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

    try:
        with VideoFileClip(video_filename) as video:
            duration = video.duration
            print(f"⏱ Длительность видео: {duration // 60:.0f} мин.")
            total_chunks = int(duration // chunk_length_sec) + 1
    except Exception as e:
        print(f"❌ Ошибка открытия видео: {e}")
        return

    processed_files = []

    for i in range(total_chunks):
        start_t = i * chunk_length_sec
        end_t = min((i + 1) * chunk_length_sec, duration)
        
        if start_t >= duration:
            break
            
        chunk_name = f"part_{i}"
        chunk_audio = os.path.join(work_dir, f"{chunk_name}.wav")
        chunk_clean = os.path.join(work_dir, f"{chunk_name}_clean.wav")
        
        print(f"\n🔹 [Часть {i+1} из {total_chunks}] {start_t:.0f}-{end_t:.0f} сек...")

        if os.path.exists(chunk_clean):
            processed_files.append(chunk_clean)
            print("   ↳ ✅ УЖЕ ОБРАБОТАНО (пропускаем)")
            continue

        try:
            with VideoFileClip(video_filename) as video:
                sub = video.subclipped(start_t, end_t) 
                sub.audio.write_audiofile(chunk_audio, logger=None)
        except Exception as e:
            print(f"❌ Ошибка нарезки: {e}")
            return

        print("   ⏳ Нейросеть чистит голос... (подождите)")
        
        cmd = [
            sys.executable, "-m", "demucs", 
            "-n", "htdemucs", 
            "--two-stems=vocals",
            "--shifts=0", "-j", "0",
            chunk_audio
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True) 
        except subprocess.CalledProcessError as e:
            print("❌ Сбой нейросети.")
            try:
                print(e.stderr.decode('utf-8', errors='ignore'))
            except:
                print(e.stderr)
            return
        except Exception as ex:
             print(f"❌ Общая ошибка запуска: {ex}")
             return

        demucs_out = os.path.join("separated", "htdemucs", chunk_name, "vocals.wav")
        if os.path.exists(demucs_out):
            shutil.move(demucs_out, chunk_clean)
            processed_files.append(chunk_clean)
            print("   ✅ Кусок готов")
            
            try:
                shutil.rmtree("separated") 
                os.remove(chunk_audio)
            except:
                pass
        else:
            print("⚠️ Ошибка: файл не обработался.")
            return

    print(f"\n🔗 Склеиваем всё в один файл...")
    try:
        combined = AudioSegment.empty()
        for f in processed_files:
            combined += AudioSegment.from_wav(f)
        
        print("💾 Сохраняем MP3 (128kbps)...")
        combined.export(final_output, format="mp3", bitrate="128k")
        
        try:
            shutil.rmtree(work_dir)
        except:
            pass
        
        print("\n" + "="*50)
        print("✅ АУДИО ОЧИЩЕНО!")
        print(f"📁 Файл сохранен как: {final_output}")
        print("="*50)
        print("\n💡 Для транскрипции запустите: transcription/speechToText.py")
        print("   (поддерживает возобновление с места остановки)")

    except Exception as e:
        print(f"❌ Ошибка при сохранении: {e}")

if __name__ == "__main__":
    found_video = auto_find_video()
    
    if found_video:
        clean_voice_final_v2(found_video)
    else:
        input("\nНажмите Enter, чтобы выйти...")