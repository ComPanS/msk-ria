import schedule
import time
from datetime import datetime, time as dt_time
from parsers import ria, moscowtimes, habr, stopgame, championat, forklog
from utils import setup_database

setup_database()

PARSERS = [moscowtimes]

# def process_all_parsers():
#     """Запускает обработку для всех парсеров"""
#     for parser in PARSERS:
#         print(f"Запуск парсера: {parser.__name__}")
#         parser.process_rss()
#         print("-------------------------------------------------------\n")

# process_all_parsers()
# schedule.every(5).minutes.do(process_all_parsers)

# Счетчик выполнений
execution_count = 0
MAX_EXECUTIONS = 5  # Максимальное количество выполнений

# Индекс текущего парсера
current_parser_index = 0


def process_all_parsers():
    """Запускает обработку для всех парсеров"""
    global execution_count, current_parser_index

    # Если достигнуто максимальное количество выполнений, останавливаемся
    if execution_count >= MAX_EXECUTIONS:
        print("Достигнуто максимальное количество выполнений.")
        return

    for parser in PARSERS:
        print(f"Запуск парсера: {parser.__name__}")
        parser.process_rss()
        print("----\n")

    execution_count += 1
    print("-------------------------------------------------------\n")
    print(f"Выполнено запусков: {execution_count}/{MAX_EXECUTIONS}")


def is_time_between(start_time, end_time):
    """Проверяет, находится ли текущее время в заданном интервале"""
    now = datetime.now().time()
    return start_time <= now <= end_time


def reset_counter_if_outside_interval():
    """Сбрасывает счетчик, если текущее время вне интервала 8:00 - 23:00"""
    global execution_count, current_parser_index
    if not is_time_between(dt_time(8, 0), dt_time(20, 0)):
        execution_count = 0
        current_parser_index = 0
        print("Счетчик выполнений сброшен (вне интервала 8:00 - 20:00).")


def scheduled_task():
    """Задача, которая выполняется только в указанном временном интервале и не более MAX_EXECUTIONS раз"""
    global execution_count

    # Сброс счетчика, если время вне интервала
    reset_counter_if_outside_interval()

    # Если достигнуто максимальное количество выполнений, останавливаемся
    if execution_count >= MAX_EXECUTIONS:
        print("Достигнуто максимальное количество выполнений.")
        return

    # Если время в интервале, запускаем обработку парсеров
    if is_time_between(dt_time(8, 0), dt_time(20, 0)):
        process_all_parsers()
    else:
        print("Сейчас не время для работы парсеров (8:00 - 20:00 МСК).")


# Настройка расписания
process_all_parsers()
schedule.every(2).hours.do(scheduled_task)

print("Запуск мониторинга RSS...\n")
print("-------------------------------------------------------\n")
while True:
    schedule.run_pending()
    time.sleep(1)
