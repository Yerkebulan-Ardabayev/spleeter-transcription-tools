@echo off
:: Включаем поддержку русских символов в консоли
chcp 65001 > nul

:: Запускаем скрипт через Python 3.10
:: ВАЖНО: Убедитесь, что ваш python-скрипт называется main.py 
:: (или замените main.py на имя вашего файла, например split_by_time.py)
py -3.10 split_by_time.py

echo.
pause