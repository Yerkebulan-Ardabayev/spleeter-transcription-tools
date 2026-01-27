import os
import json
import argparse
import subprocess
import sys
import shutil
import torch
from typing import List
from faster_whisper import WhisperModel

# --- НАСТРОЙКИ ПО УМОЛЧАНИЮ ---
SUPPORTED_FORMATS = {'.wav', '.mp3', '.ogg', '.m4a', '.flac', '.wma', '.opus'}
DEFAULT_MODEL = "large-v3"
DEFAULT_COMPUTE = "int8" # float16 для GPU, int8 для CPU

# === ТВОЙ ПУТЬ К FFMPEG ===
# Можно переопределить через аргумент --ffmpeg
HARDCODED_FFMPEG = r"C:\ffmpeg-2025-10-12-git-0bc54cddb1-essentials_build\ffmpeg-2025-10-12-git-0bc54cddb1-essentials_build\bin\ffmpeg.exe"

class AudioTranscriber:
    def __init__(self, model_size: str, device: str, compute_type: str, ffmpeg_path: str = None):
        self.ffmpeg_path = ffmpeg_path
        
        # Логика выбора устройства
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        
        print(f"\n⏳ Загрузка модели '{model_size}'...")
        print(f"   📍 Устройство: {device} ({compute_type})")
        print(f"   ⚠️  Это может занять 1-2 минуты при первом запуске...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            print(f"   ✓ Модель загружена успешно!\n")
        except Exception as e:
            print(f"   ⚠️  Не удалось загрузить на {device}. Пробуем CPU int8...")
            print(f"   Ошибка: {e}")
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
            print(f"   ✓ Модель загружена на CPU!\n")

    def _seconds_to_hms(self, seconds: float, separator=":") -> str:
        """Формат 00:00:00"""
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{int(h):02d}{separator}{int(m):02d}{separator}{int(s):02d}"

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Формат для SRT: 00:00:00,000"""
        parts = self._seconds_to_hms(seconds, ":")
        ms = int((seconds % 1) * 1000)
        return f"{parts},{ms:03d}"

    def _get_ffmpeg_cmd(self):
        # 1. Приоритет: аргумент командной строки
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            return self.ffmpeg_path
        # 2. Приоритет: хардкод
        if os.path.exists(HARDCODED_FFMPEG):
            return HARDCODED_FFMPEG
        # 3. Приоритет: системный путь
        if shutil.which("ffmpeg"):
            return "ffmpeg"
        return None

    def export_srt(self, segments, output_path):
        """Создание файла субтитров"""
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = self._seconds_to_srt_time(seg['start'])
                end = self._seconds_to_srt_time(seg['end'])
                text = seg['text'].strip()
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    def export_readable(self, segments, output_path):
        """Создание читаемого текстового файла с таймкодами"""
        with open(output_path, "w", encoding="utf-8") as f:
            for seg in segments:
                time_mark = self._seconds_to_hms(seg['start'])
                f.write(f"[{time_mark}] {seg['text'].strip()}\n")

    def transcribe(self, audio_path: str) -> List[dict]:
        base_name = os.path.splitext(audio_path)[0]
        progress_file = f"{base_name}_PROGRESS.jsonl"
        
        existing_segments = []
        resume_timestamp = 0.0
        
        # --- ВОЗОБНОВЛЕНИЕ ---
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as pf:
                    for line in pf:
                        if line.strip(): 
                            existing_segments.append(json.loads(line))
                if existing_segments:
                    resume_timestamp = existing_segments[-1]['end']
                    print(f"   🔄 Найден прогресс! Продолжаем с {self._seconds_to_hms(resume_timestamp)}")
                    print(f"   📊 Уже обработано сегментов: {len(existing_segments)}")
            except Exception as err:
                print(f"   ⚠️  Ошибка чтения прогресса: {err}")
                print(f"   🔁 Начинаем с начала...")
                existing_segments = []
                resume_timestamp = 0.0

        print(f"\n🎤 Начинаю обработку: {os.path.basename(audio_path)}")
        
        # Проверка существования файла
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудиофайл не найден: {audio_path}")
        
        process_path = audio_path
        temp_cut_file = None
        time_shift = 0.0 
        
        ffmpeg_cmd = self._get_ffmpeg_cmd()

        # --- ОБРЕЗКА (ОПТИМИЗАЦИЯ) ---
        if resume_timestamp > 5.0:
            if ffmpeg_cmd:
                # ИСПРАВЛЕНИЕ: используем абсолютный путь
                audio_dir = os.path.dirname(os.path.abspath(audio_path))
                temp_cut_file = os.path.join(audio_dir, f"temp_resume_{os.path.basename(audio_path)}")
                
                print(f"   ⚙️  Подготовка FFmpeg...")
                print(f"   📁 Создание временного файла с позиции {self._seconds_to_hms(resume_timestamp)}")
                
                try:
                    # Удаляем старый temp файл если есть
                    if os.path.exists(temp_cut_file):
                        os.remove(temp_cut_file)
                    
                    subprocess.run([
                        ffmpeg_cmd, '-y', '-v', 'quiet', '-ss', str(resume_timestamp), 
                        '-i', audio_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', temp_cut_file
                    ], check=True, timeout=60)
                    
                    # Проверяем что файл создан
                    if os.path.exists(temp_cut_file) and os.path.getsize(temp_cut_file) > 0:
                        process_path = temp_cut_file
                        time_shift = resume_timestamp
                        print(f"   ✓ Временный файл готов!")
                    else:
                        print(f"   ⚠️  Временный файл не создан. Обрабатываем полный файл.")
                        temp_cut_file = None
                        
                except subprocess.TimeoutExpired:
                    print(f"   ⚠️  FFmpeg завис (timeout). Работаем с полным файлом.")
                    if temp_cut_file and os.path.exists(temp_cut_file):
                        try: os.remove(temp_cut_file)
                        except: pass
                    temp_cut_file = None
                except Exception as e:
                    print(f"   ⚠️  Ошибка FFmpeg: {e}")
                    print(f"   🔄 Работаем с полным файлом (будет дольше, но надежнее)")
                    if temp_cut_file and os.path.exists(temp_cut_file):
                        try: os.remove(temp_cut_file)
                        except: pass
                    temp_cut_file = None
            else:
                print(f"   ⚠️  FFmpeg не найден. Пропуск обработанной части будет программным.")
        
        # --- ТРАНСКРИБАЦИЯ ---
        print(f"   🚀 Запуск транскрибации...\n")
        segments, info = self.model.transcribe(process_path, language="ru", vad_filter=True)
        total_duration = info.duration + time_shift 
        
        processed_count = 0
        with open(progress_file, 'a', encoding='utf-8') as pf:
            for segment in segments:
                current_start = segment.start + time_shift
                current_end = segment.end + time_shift
                
                # Защита от дублей при наложении
                if current_end <= resume_timestamp + 0.1:
                    continue
                
                percent = int((current_end / total_duration * 100)) if total_duration else 0
                
                # Визуальный прогресс-бар
                bar_length = 20
                filled = int(bar_length * percent / 100)
                bar = '█' * filled + '░' * (bar_length - filled)
                
                # Красивый вывод в консоль
                text_preview = segment.text.strip()[:40]
                sys.stdout.write(f"\r   🎤 [{bar}] {percent:3d}% | {self._seconds_to_hms(current_end)} | {text_preview}...")
                sys.stdout.flush()
                
                seg_data = {
                    "start": round(current_start, 2), 
                    "end": round(current_end, 2), 
                    "text": segment.text.strip()
                }
                pf.write(json.dumps(seg_data, ensure_ascii=False) + "\n")
                pf.flush()
                existing_segments.append(seg_data)
                processed_count += 1
        
        print(f"\n   ✓ Обработка завершена! Обработано сегментов: {processed_count}")

        # Удаляем временный файл
        if temp_cut_file and os.path.exists(temp_cut_file):
            try: 
                os.remove(temp_cut_file)
                print(f"   🧹 Временный файл удален")
            except Exception as e:
                print(f"   ⚠️  Не удалось удалить temp файл: {e}")

        return existing_segments

def get_audio_files(directory: str) -> List[str]:
    files = []
    print(f"\n📂 Сканирую папку: {os.path.abspath(directory)}")
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in SUPPORTED_FORMATS:
                files.append(os.path.join(root, filename))
    
    if files:
        print(f"   ✓ Найдено аудиофайлов: {len(files)}")
        for i, f in enumerate(files, 1):
            print(f"      {i}. {os.path.basename(f)}")
    else:
        print(f"   ℹ️  Аудиофайлы не найдены")
    
    return sorted(files)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Транскрибатор аудио")
    parser.add_argument("path", nargs="?", default=".", help="Путь к папке с аудио или конкретному файлу")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Размер модели (tiny, base, small, medium, large-v3)")
    parser.add_argument("--device", default="auto", help="Устройство (cuda, cpu, auto)")
    parser.add_argument("--ffmpeg", default=None, help="Путь к ffmpeg.exe вручную")
    args = parser.parse_args()

    # Сбор файлов
    target_files = []
    if os.path.isfile(args.path):
        target_files = [args.path]
    else:
        target_files = get_audio_files(args.path)

    if not target_files:
        print("\n❌ Аудиофайлов не найдено. Проверьте путь.")
        sys.exit(0)

    try:
        app = AudioTranscriber(
            model_size=args.model, 
            device=args.device, 
            compute_type="float16" if args.device == "cuda" or (args.device=="auto" and torch.cuda.is_available()) else "int8",
            ffmpeg_path=args.ffmpeg
        )
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА при загрузке модели: {e}")
        print(f"   💡 Проверьте подключение к интернету и наличие свободного места")
        sys.exit(1)

    for i, file_path in enumerate(target_files, 1):
        filename = os.path.basename(file_path)
        base_path = os.path.splitext(file_path)[0]
        
        # Пути выходных файлов
        srt_file = base_path + ".srt"
        txt_file = base_path + ".txt" # Читаемый
        
        print(f"\n" + "="*70)
        print(f"📄 Файл {i}/{len(target_files)}: {filename}")
        print("="*70)
        
        # Если файлы уже есть, пропускаем
        if os.path.exists(srt_file) and os.path.exists(txt_file):
             print(f"   ⏭️  Этот файл уже обработан, пропускаем.")
             print(f"   📁 SRT: {os.path.basename(srt_file)}")
             print(f"   📁 TXT: {os.path.basename(txt_file)}")
             continue
            
        try:
            segments = app.transcribe(file_path)
            
            print(f"\n   💾 Сохранение результатов...")
            # Сохраняем SRT (для видео)
            app.export_srt(segments, srt_file)
            print(f"   ✓ SRT: {os.path.basename(srt_file)}")
            
            # Сохраняем читаемый текст (для чтения)
            app.export_readable(segments, txt_file)
            print(f"   ✓ TXT: {os.path.basename(txt_file)}")
            
            print(f"\n   🎉 ГОТОВО! Всего сегментов: {len(segments)}")
            
        except KeyboardInterrupt:
            print(f"\n\n   ⏸️  ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ")
            print(f"   💡 Прогресс сохранен! Запустите снова для продолжения.")
            sys.exit(0)
        except Exception as e:
            print(f"\n   ❌ ОШИБКА при обработке {filename}:")
            print(f"   📝 Детали: {e}")
            import traceback
            print(f"\n   🔍 Полная трассировка:")
            traceback.print_exc()
    
    print(f"\n" + "="*70)
    print(f"✅ ВСЕ ФАЙЛЫ ОБРАБОТАНЫ!")
    print("="*70)