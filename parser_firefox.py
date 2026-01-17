import time
import sqlite3
import re
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.firefox import GeckoDriverManager
from bs4 import BeautifulSoup

# --- НАСТРОЙКИ ---
# Новая ссылка на 1156 заданий
TARGET_URL = "https://neofamily.ru/literatura/task-bank?sort_by=id&sort_order=asc&parts=%D0%A7%D0%B0%D1%81%D1%82%D1%8C+1&Print=true&Answers=with_answers&lines=184,186,187,190,191,192&themes=174,172,173,876,175,176,177,178,180,181,367,368,370,371,372,373,374,375,376,377,378,379,380,877,382,383,384,385,386,387,388,389,390,391,392,393,394,395,396,397,398,400,401,402,406,409,411"
TARGET_COUNT = 1156
DB_NAME = 'literature_bot.db'

def get_db_connection():
    return sqlite3.connect(DB_NAME)

def initialize_driver():
    options = Options()
    try:
        service = Service(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)
        driver.maximize_window()
        return driver
    except Exception as e:
        print(f"ОШИБКА драйвера: {e}")
        return None

def clean_text(html_content):
    """
    Очистка текста с сохранением форматирования (абзацы, пробелы, подчеркивания).
    """
    if not html_content: return None
    
    # 1. Заменяем блочные элементы на переносы строк
    html_content = html_content.replace("<br>", "\n").replace("<br/>", "\n")
    html_content = html_content.replace("</p>", "\n\n")
    html_content = html_content.replace("</div>", "\n")
    html_content = html_content.replace("</li>", "\n")

    soup = BeautifulSoup(html_content, "html.parser")

    # 2. Обработка пропусков (подчеркнутый текст)
    for tag in soup.find_all(True):
        style = tag.get('style', '')
        is_underlined = (tag.name == 'u') or ('text-decoration' in style and 'underline' in style)
        
        if is_underlined:
            inner_text = tag.get_text(strip=True)
            if not inner_text: # Если внутри только пробелы
                tag.replace_with(" _______ ")
    
    # 3. Получаем текст с разделителем-пробелом (чтобы не было вертикальных слов)
    text = soup.get_text(separator=" ")
    
    # 4. Финальная чистка
    text = re.sub(r'[ \t]+', ' ', text)      # Убираем лишние пробелы
    text = re.sub(r' *\n *', '\n', text)     # Убираем пробелы у переносов строк
    text = re.sub(r'\n{3,}', '\n\n', text)   # Не более 2 пустых строк
    
    return text.strip()

def parse_answer_from_text(full_text):
    """Ищет слово 'Ответ:' в полном тексте карточки"""
    if "Ответ:" in full_text:
        parts = full_text.split("Ответ:")
        if len(parts) > 1:
            raw_ans = parts[-1].strip().split('\n')[0]
            if "Источник" in raw_ans:
                raw_ans = raw_ans.split("Источник")[0].strip()
            raw_ans = raw_ans.replace(" ИЛИ ", "|").replace(" или ", "|")
            return raw_ans.lower()
    return None

def scrape_neofamily():
    driver = initialize_driver()
    if not driver: return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        print(f">>> Открываю сайт...")
        driver.get(TARGET_URL)
        time.sleep(5)

        # --- ЭТАП 1: СКРОЛЛИНГ ---
        print(f">>> Начинаю скроллинг до {TARGET_COUNT} заданий...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Быстрый подсчет через JS
            current_count = driver.execute_script("return document.getElementsByClassName('rounded-xl border-natural-2').length")
            print(f"    -> Загружено: {current_count}")
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if current_count >= TARGET_COUNT:
                print(f">>> Ура! Найдено {current_count} заданий.")
                break
            if new_height == last_height:
                # Вторая попытка
                time.sleep(2)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                new_height_2 = driver.execute_script("return document.body.scrollHeight")
                if new_height_2 == last_height:
                    print(">>> Скролл остановился.")
                    break
            last_height = new_height

        # --- ЭТАП 2: СБОР ---
        print(">>> Начинаю обработку...")
        
        for i in range(current_count):
            try:
                # 1. Находим все карточки заново
                cards = driver.find_elements(By.CSS_SELECTOR, "div.rounded-xl.border-natural-2")
                
                if i >= len(cards):
                    print(">>> Индекс вышел за пределы списка.")
                    break
                
                card = cards[i]
                
                # 2. Скроллим к карточке и ЖДЕМ отрисовки
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                time.sleep(0.5) 
                
                # --- СБОР ДАННЫХ ---
                
                # А. Линия
                try:
                    line_text = card.find_element(By.XPATH, ".//div[contains(text(), 'линия')]").text
                    line_number = int(re.search(r'\d+', line_text).group())
                except:
                    print(f"[{i+1}] Линия не найдена, пропускаю.")
                    continue

                # Б. Вопрос (с новой очисткой)
                try:
                    q_el = card.find_element(By.CSS_SELECTOR, ".detail-text_detailText__YRcv_")
                    question_text = clean_text(q_el.get_attribute('innerHTML'))
                except:
                    question_text = "Текст вопроса не найден"

                # В. Текст произведения
                content_text = None
                try:
                    expand_btns = card.find_elements(By.XPATH, ".//button[contains(text(), 'Показать полностью')]")
                    if expand_btns:
                        driver.execute_script("arguments[0].click();", expand_btns[0])
                        time.sleep(0.2)
                        
                        text_blocks = card.find_elements(By.CSS_SELECTOR, ".detail-text_detailText__YRcv_")
                        if len(text_blocks) > 1:
                            content_text = clean_text(text_blocks[1].get_attribute('innerHTML'))
                except:
                    pass

                # Г. Ответ
                card_full_text = card.text
                correct_answer = parse_answer_from_text(card_full_text)
                
                if not correct_answer:
                    try:
                        sol_btn = card.find_element(By.CSS_SELECTOR, "button[data-name='solution']")
                        driver.execute_script("arguments[0].click();", sol_btn)
                        time.sleep(0.5) 
                        
                        card_full_text_after_click = card.text
                        correct_answer = parse_answer_from_text(card_full_text_after_click)
                    except Exception as e:
                        if i == 0: driver.save_screenshot("debug_error.png")
                        pass

                # Д. Запись
                if correct_answer:
                    cursor.execute("SELECT id FROM tasks WHERE question_text = ? AND correct_answer = ?", (question_text, correct_answer))
                    if not cursor.fetchone():
                        # ВАЖНО: is_active = 1
                        cursor.execute('''
                            INSERT INTO tasks (line_number, question_text, content_text, correct_answer, is_active)
                            VALUES (?, ?, ?, ?, 1)
                        ''', (line_number, question_text, content_text, correct_answer))
                        conn.commit()
                        print(f"[{i+1}/{current_count}] Линия {line_number} -> OK: {correct_answer}")
                    else:
                        print(f"[{i+1}/{current_count}] Уже в базе")
                else:
                    print(f"[{i+1}/{current_count}] Ответ не извлечен.")

            except Exception as e:
                print(f"[{i+1}] Сбой итерации: {e}")
                continue

    finally:
        conn.close()
        driver.quit()

if __name__ == "__main__":
    scrape_neofamily()