<div align="center">

# 🖥️ Telegram PC Control

**Управляй своим Windows-компьютером прямо из чата Telegram**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Telegram](https://img.shields.io/badge/Bot-API-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

Полноценный пульт для ПК: скриншоты и трансляция экрана, мышь и клавиатура,
WASD для игр, управление музыкой, Anti-AFK и Telegram Mini App — всё в одном боте.

[Возможности](#-возможности) • [Установка](#-установка) • [Команды](#-команды) • [Mini App](#-mini-app) • [Структура](#-структура-проекта)

</div>

---

## ✨ Возможности

| | Функция | Описание |
|---|---|---|
| 📸 | **Скриншоты** | `/screenshot` — снимок экрана прямо в чат |
| 🔴 | **Трансляция экрана** | `/live 3` — живые кадры экрана + кнопки управления мышью, как AnyDesk, только в Telegram |
| 🖼 | **Просмотр картинок** | Пришли фото боту → `/showimage` — откроется на весь экран ПК |
| 🖱 | **Мышь и клавиатура** | Панели `/mouse`, `/keyboard`, `/wasd`, ввод текста через `/type` |
| 🎮 | **WASD для игр** | Режимы «Тап» и «Удержание» клавиш, автоотпускание через 60 сек |
| 🎵 | **Управление плеером** | Play/pause, треки, громкость — через системные медиа-клавиши |
| 🚀 | **Запуск программ** | `/open telegram` — найдёт ярлык в «Пуске» и запустит |
| 💤 | **Anti-AFK** | Два режима: для мессенджеров (незаметное движение мыши) и для игр (Space + клик) |
| 📋 | **Буфер обмена** | `/clipboard` и `/setclip` — читает и пишет буфер обмена ПК |
| 🔋 | **Система** | `/status`, `/battery`, `/ip`, `/volume`, `/lock`, `/shutdown`, `/restart` |
| 📱 | **Mini App** | Веб-панель для Telegram на GitHub Pages — тёмная тема, кнопки, тумблеры |
| 🔐 | **Пароль-сессия** | Сессия на 24 часа, ввод пароля при старте — никто чужой не подключится |
| 🖥 | **GUI-панель** | `control_panel.pyw` — тёмный интерфейс: настройки, запуск/стоп, автозапуск с Windows, трей |

## 📦 Установка

> **Всё автоматически!** Python ставить заранее не нужно — `install.bat` сам скачает и установит Python, создаст окружение и поставит зависимости.

```bash
# 1. Скачай и распакуй проект
# 2. Создай бота у @BotFather и получи токен

# 3. Запусти установку (двойной клик)
install.bat

# 4. Открой панель управления
ControlPanel.vbs
```

<details>
<summary><b>⚙️ Ручная установка</b></summary>

1. Установи [Python 3.11+](https://www.python.org/downloads/) с галочкой **Add python.exe to PATH**
2. Снова запусти `install.bat` — установятся только зависимости
3. Заполни `.env` по образцу из `.env.example` и запусти `run.bat`

</details>

<details>
<summary><b>🔧 Настройка панели управления</b></summary>

В панели `ControlPanel.vbs` можно:

- 🔑 Указать **Bot Token**, **Telegram User ID**, **пароль** и **Mini App URL** (поля скрыты, есть 👁)
- ▶️ Запустить/остановить бота **в фоне** — без окна консоли
- 🔄 Включить **автозапуск вместе с Windows**
- 📌 Свернуть в **системный трей** — управление ботом оттуда

</details>

## 💬 Команды

| Команда | Что делает |
|---|---|
| `/start` | Полный список команд с описаниями |
| `/screenshot` | Скриншот экрана |
| `/live [сек]` | Трансляция экрана (кадры каждые 2.5 сек, минимум 1.5) |
| `/stoplive` | Остановить трансляцию |
| `/showimage` | Показать присланное фото на весь экран |
| `/mouse` | Панель мыши: стрелки, клики, скролл |
| `/keyboard` | Панель клавиш: Enter, Esc, Tab, Alt+Tab, Ctrl+C/V/Z... |
| `/wasd` | WASD-панель для игр |
| `/type <текст>` | Напечатать текст в активное окно |
| `/key <имя>` | Нажать клавишу, например `/key enter` |
| `/music` | Панель управления плеером |
| `/open [название]` | Запустить программу, например `/open steam` |
| `/apps [название]` | Список похожих программ кнопками |
| `/antiafk on\|off` | Anti-AFK для мессенджеров |
| `/antiafkgame on\|off` | Anti-AFK для игр |
| `/volume up\|down\|mute` | Громкость системы |
| `/clipboard` / `/setclip <текст>` | Чтение / запись буфера обмена |
| `/battery` `/ip` `/status` | Заряд, IP, состояние ПК |
| `/app` | Открыть Mini App |
| `/lock` `/shutdown` `/restart` | Управление питанием |

## 📱 Mini App

В комплекте есть `mini_app/index.html` — мобильная веб-панель в тёмной теме.

Подключение через GitHub Pages (бесплатно, один раз):

1. Загрузи `mini_app/index.html` в публичный репозиторий
2. `Settings → Pages` → включи GitHub Pages для ветки `main`
3. Получишь ссылку вида `https://логин.github.io/репозиторий/index.html`
4. Вставь её в панель управления → «💾 Сохранить настройки»
5. В Telegram напиши боту `/app` → кнопка «🚀 Открыть Mini App»

> ⚠️ Telegram закрывает Mini App после каждого действия — это особенность API, не баг. Для быстрых повторных нажатий удобнее панели `/mouse`, `/keyboard` и `/music` в чате.

## 🗂 Структура проекта

```
TelegramControlPC/
├── 🤖 bot.py                 # Основной код бота
├── 🖥 control_panel.pyw      # GUI-панель управления
├── 🚀 ControlPanel.vbs       # Запуск панели без окна консоли
├── 📦 install.bat            # Автоустановка (Python + зависимости)
├── ▶️ run.bat                # Запуск бота в консольном режиме
├── 🗑 Uninstall.bat          # Полное удаление программы
├── 🎨 app_icon.ico           # Иконка приложения и трея
├── ⚙️ .env.example           # Шаблон настроек
├── 📄 requirements.txt       # Зависимости
└── 📱 mini_app/
    └── index.html            # Telegram Mini App
```

## ⚠️ Важно

- 🔐 Никому не передавай `BOT_TOKEN`, файл `.env` и пароль `APP_PASSWORD`
- 🌐 Telegram Bot API не поддерживает настоящее видео — «трансляция» это быстрые скриншоты (оптимально 2–3 сек между кадрами)
- 🛠 Частая ошибка «Python не найден» на Windows — заглушка Microsoft Store. `install.bat` умеет её распознавать
- 🗑 Полное удаление: `Uninstall.bat` (подтверждение вводом `YES`), после — отзови токен у @BotFather (`/revoke`)

## 🛠 Технологии

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)
![Pillow](https://img.shields.io/badge/Pillow-9A55D0?style=flat-square&logo=pillow&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-0078D6?style=flat-square&logo=windows&logoColor=white)

---

<div align="center">

**⭐ Понравился проект — поставь звёздочку! ⭐**

</div>
