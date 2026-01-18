import sqlite3
import datetime

class Database:
    def __init__(self, db_file):
        # check_same_thread=False важен для асинхронного бота
        self.connection = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.connection.cursor()
        
        # Включаем WAL-режим (Write-Ahead Logging)
        # Это позволяет читать и писать в базу одновременно без лагов
        self.cursor.execute("PRAGMA journal_mode=WAL;")
        self.cursor.execute("PRAGMA synchronous=NORMAL;")

    def user_exists(self, user_id):
        with self.connection:
            result = self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchall()
            return bool(len(result))

    def add_user(self, user_id, username, full_name):
        with self.connection:
            return self.cursor.execute("INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)", 
                                       (user_id, username, full_name))

    def get_user_name(self, user_id):
        with self.connection:
            result = self.cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return result[0] if result else "Ученик"

    # --- ЛОГИКА ВЫДАЧИ ЗАДАНИЙ ---

    def get_todays_lines(self):
        """
        Вычисляет 5 линий для сегодняшнего дня (скользящее окно).
        Линии: 1, 2, 3, 6, 7, 8.
        """
        available_lines = [1, 2, 3, 6, 7, 8]
        # Получаем номер дня года (1...365)
        day_of_year = datetime.datetime.now().timetuple().tm_yday
        
        # Простое решение для сдвига:
        offset = day_of_year % len(available_lines)
        extended_list = available_lines + available_lines
        todays_lines = extended_list[offset : offset + 5]
        
        return todays_lines

    def check_today_completed(self, user_id):
        """
        Проверяет, выполнил ли пользователь норму на сегодня (>= 5 заданий).
        """
        with self.connection:
            # Считаем, сколько заданий было назначено СЕГОДНЯ.
            count = self.cursor.execute('''
                SELECT COUNT(*) FROM user_results 
                WHERE user_id = ? AND assigned_date = CURRENT_DATE
            ''', (user_id,)).fetchone()[0]
            # Если 5 или больше, значит план на сегодня всё.
            return count >= 5

    def get_new_tasks_for_user(self, user_id):
        """
        Логика:
        1. 5 свежих заданий на сегодня (в первую очередь).
        2. Все накопившиеся долги за прошлые дни (дополнительный блок).
        """
        tasks_to_send = []
        lines_today = self.get_todays_lines()

        with self.connection:
            # --- БЛОК 1: НОВЫЕ ЗАДАНИЯ (5 штук) ---
            # Берем первые 5 линий из расписания на сегодня
            current_lines_queue = lines_today[:5]
            
            for line in current_lines_queue:
                # Ищем нерешенное задание по этой линии
                task = self.cursor.execute('''
                    SELECT id, line_number, question_text, options_text, content_text 
                    FROM tasks 
                    WHERE line_number = ? 
                    AND is_active = 1
                    AND id NOT IN (SELECT task_id FROM user_results WHERE user_id = ?)
                    ORDER BY RANDOM() LIMIT 1
                ''', (line, user_id)).fetchone()
                
                if task:
                    # Записываем выдачу в базу
                    self.cursor.execute("INSERT INTO user_results (user_id, task_id, status, assigned_date) VALUES (?, ?, 0, CURRENT_DATE)", 
                                        (user_id, task[0]))
                    
                    tasks_to_send.append({
                        'id': task[0], 'line': task[1], 'question': task[2], 
                        'options': task[3], 'text': task[4], 'is_debt': False
                    })

            # --- БЛОК 2: ДОЛГИ (Все остальные) ---
            # Статус 2 = ошибка/пропуск, Дата != сегодня, Задание активно
            debts = self.cursor.execute('''
                SELECT t.id, t.line_number, t.question_text, t.options_text, t.content_text
                FROM user_results ur
                JOIN tasks t ON ur.task_id = t.id
                WHERE ur.user_id = ? 
                AND ur.status = 2 
                AND ur.assigned_date != CURRENT_DATE
                AND t.is_active = 1
            ''', (user_id,)).fetchall()
            
            for task in debts:
                tasks_to_send.append({
                    'id': task[0], 'line': task[1], 'question': task[2], 
                    'options': task[3], 'text': task[4], 'is_debt': True
                })
            
            return tasks_to_send

    def get_correct_answer(self, task_id):
        with self.connection:
            return self.cursor.execute("SELECT correct_answer FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]

    def update_task_status(self, user_id, task_id, is_correct, user_answer):
        """Обновляет статус задания после ответа"""
        status = 1 if is_correct else 2
        with self.connection:
            self.cursor.execute('''
                UPDATE user_results 
                SET status = ?, user_answer = ?, assigned_date = CURRENT_DATE 
                WHERE user_id = ? AND task_id = ?
            ''', (status, user_answer, user_id, task_id))

    def get_daily_stats(self, user_id):
        """Возвращает список всех заданий, решенных СЕГОДНЯ (для отчета)"""
        with self.connection:
            stats = self.cursor.execute('''
                SELECT ur.id, t.id, t.line_number, ur.status, ur.user_answer, t.correct_answer, t.question_text
                FROM user_results ur
                JOIN tasks t ON ur.task_id = t.id
                WHERE ur.user_id = ? AND ur.assigned_date = CURRENT_DATE
            ''', (user_id,)).fetchall()
            return stats

    def toggle_result_status(self, result_id, new_status):
        """
        Меняет статус конкретного решения (1 - верно, 2 - неверно).
        """
        with self.connection:
            self.cursor.execute("UPDATE user_results SET status = ? WHERE id = ?", (new_status, result_id))
            
    def get_task_text_by_result_id(self, result_id):
        """
        Получает текст произведения, зная ID результата в таблице user_results.
        """
        with self.connection:
            res = self.cursor.execute('''
                SELECT t.content_text FROM tasks t
                JOIN user_results ur ON ur.task_id = t.id
                WHERE ur.id = ?
            ''', (result_id,)).fetchone()
            return res[0] if res else None

    def toggle_task_active_status(self, task_id, is_active):
        """
        Меняет глобальную активность задания (1 - активно, 0 - скрыто/удалено).
        """
        with self.connection:
            self.cursor.execute("UPDATE tasks SET is_active = ? WHERE id = ?", (is_active, task_id))