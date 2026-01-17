import sqlite3

def create_database():
    db_name = 'literature_bot.db'
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # 1. Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. Таблица заданий (С НОВОЙ КОЛОНКОЙ is_active)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        line_number INTEGER NOT NULL,
        question_text TEXT NOT NULL,
        options_text TEXT,
        content_text TEXT,
        correct_answer TEXT NOT NULL,
        is_active INTEGER DEFAULT 1  -- Новая колонка (1 = активно)
    )
    ''')

    # 3. Таблица результатов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
        status INTEGER DEFAULT 0, 
        user_answer TEXT DEFAULT NULL,
        assigned_date DATE DEFAULT CURRENT_DATE,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    ''')

    conn.commit()
    conn.close()
    print(f"База данных '{db_name}' успешно создана (версия с is_active).")

if __name__ == '__main__':
    create_database()