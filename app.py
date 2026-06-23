import asyncio
import random
import os
import requests
import xlsxwriter

from pyrogram import Client, filters, compose
from pyrogram.errors import FloodWait, UserDeactivatedBan, AuthKeyDuplicated, AuthKeyUnregistered, Forbidden, UserAlreadyParticipant
from pyrogram.errors.exceptions.bad_request_400 import MsgIdInvalid, PeerIdInvalid


from pyrogram.enums import ParseMode, ChatAction
from pyrogram.raw.functions.users import GetFullUser
from pyrogram.raw.types import InputUser
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from pyrogram.errors import SessionPasswordNeeded

from pyrogram.raw.functions.contacts import Search

from handlers import add_handler, remove_handler, is_handler
from menus import pretexts_menu
from sqlite_functions import sql_select, sql_edit, core_commands
from config import API_ID, API_HASH, BOT_ID, BOT_LINK, BOT_TOKEN, ADMINS, TIMEWEB_TOKEN, TIMEWEB_AGENT_ID

# важное

SENT_TODAY = 0
TIMEWEB_API_BASE = 'https://agent.timeweb.cloud/api/v1/cloud-ai/agents'

conversation_history = ["Привет, как дела?", "Все отлично! Как я могу помочь вам?"]

admins_only = False
admins = ADMINS

# костыль для остановки парсинга, потом перепишу

working = False

# настройки бота

LIMIT = 2000000000
WORK_SINCE = 0
WORK_UNTIL = 0
MANAGERS_COUNT = 0
emojies = ('😺', '😸', '😹', '😻', '😾', '😿', '🙀', '😽', '😼', '❤️')

# при необходимости создаём таблицы

for command in core_commands:
    sql_edit(command, ())

# получаем уже сохраненные сессии

managers = sql_select('SELECT token FROM managers')
workers = sql_select('SELECT session, proxy FROM workers')
worker_apps = []
manager_apps = []

if not managers:
    managers.append((BOT_TOKEN,))
    sql_edit('INSERT INTO managers(token) VALUES(?)', (BOT_TOKEN,))

apps = []
workers_list = {}

async def accounts(message):
    keyboard = []
    
    for user in workers_list.keys():
        try:
            user_info = await workers_list[user].get_me()
            keyboard.append([InlineKeyboardButton(f'{user_info.first_name}',
                                                  callback_data=f'user {user_info.phone_number}')])
        except UserDeactivatedBan:
            sql_edit(f"DELETE FROM workers WHERE session = '{user}'", ())
            continue
        except AuthKeyDuplicated:
            sql_edit(f"DELETE FROM workers WHERE session = '{user}'", ())
            continue
        except AuthKeyUnregistered:
            sql_edit(f"DELETE FROM workers WHERE session = '{user}'", ())
            continue
        except Exception as e:
            await message.reply(f'Ошибка при получении информации об аккаунте<pre>{e}</pre>')
            continue

    keyboard.append([InlineKeyboardButton('Добавить аккаунт 👮‍♀️', callback_data='+')])
    
    await message.edit(
        "<b>Список ваших аккаунтов</b>\n\nДля настройки аккаунта нажмите на его ник",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def menu(message):
    keyboard = []
    
    # for user in workers_list.keys():
    #     try:
    #         user_info = await workers_list[user].get_me()
    #         keyboard.append([InlineKeyboardButton(f'{user_info.first_name}',
    #                                               callback_data=f'user {user_info.phone_number}')])
    #     except UserDeactivatedBan:
    #         sql_edit(f'DELETE FROM workers WHERE session = {user}', ())
    #         continue
    #     except AuthKeyDuplicated:
    #         sql_edit(f'DELETE FROM workers WHERE session = {user}', ())
    #         continue
    #     except AuthKeyUnregistered:
    #         sql_edit(f'DELETE FROM workers WHERE session = {user}', ())
    #         continue
    #     except Exception as e:
    #         await message.reply(f'Ошибка при получении информации об аккаунте<pre>{e}</pre>')
    #         continue
    
    if workers_list:
        keyboard.append([InlineKeyboardButton('Спарсить комменты 💬', callback_data='parse_comments')])
        keyboard.append([InlineKeyboardButton('Поиск каналов 🔎', callback_data='search')])
    
    keyboard.append([InlineKeyboardButton('Канал уведомлений 🥰', callback_data='service channel')])
    keyboard.append([InlineKeyboardButton('Токен Timeweb AI ♻️', callback_data='token')])
    keyboard.append([InlineKeyboardButton('Agent ID Timeweb AI 🖥️', callback_data='proxy')])
    keyboard.append([InlineKeyboardButton('Новый бот для управления 🤖', callback_data='bot')])
    keyboard.append([InlineKeyboardButton('Добавить аккаунт 👮‍♀️', callback_data='+')])
    
    await message.edit(
        "Список ваших аккаунтов:",
        reply_markup=InlineKeyboardMarkup(keyboard))

def _timeweb_headers():
    return {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {TIMEWEB_TOKEN}',
    }

def _timeweb_url():
    return f'{TIMEWEB_API_BASE}/{TIMEWEB_AGENT_ID}/v1/chat/completions'

def generate_keywords(keyword):
    url = _timeweb_url()
    headers = _timeweb_headers()

    conversation_history.append(f'подбери 10 похожих ключевых слов к запросу "{keyword}" для поиска телеграм каналов')

    data = {
        'model': 'gpt-4',
        'messages': [
            {"role": "system", "content": "Ты полезный помощник."},
            {"role": "user", "content": conversation_history[-1]},
        ]
    }

    gptreq = requests.post(url, headers=headers, json=data)

    if 'error' in gptreq.json():
        return 'insufficient_quota'

    assistant_reply = gptreq.json()["choices"][0]['message']['content']

    if assistant_reply.startswith('"') and assistant_reply.endswith('"'):
        assistant_reply = assistant_reply[1:-1]

    conversation_history.append(assistant_reply)
    return assistant_reply
    
async def generate_response(prompt, role, app):
    try:
        url = _timeweb_url()
        headers = _timeweb_headers()

        conversation_history.append(prompt)

        data = {
            'model': 'gpt-4',
            'messages': [
                {"role": "system", "content": role},
                {"role": "user", "content": conversation_history[-1]},
            ]
        }

        gptreq = requests.post(url, headers=headers, json=data)

        if gptreq.status_code == 200:

            assistant_reply = gptreq.json()["choices"][0]['message']['content']

            if assistant_reply.startswith('"') and assistant_reply.endswith('"'):
                assistant_reply = assistant_reply[1:-1]

            conversation_history.append(assistant_reply)

            return assistant_reply

        else:
            for admin in admins:
                try:
                    await app.send_message(
                        admin, f'Ошибка при запросе к Timeweb AI: [{gptreq.status_code}] {gptreq.json()["error"]["message"]}')
                except:
                    pass

    except Exception as e:
        print(e)


def format_proxy(proxy):
    if len(proxy) == 5:
        return {"scheme": proxy[0],
                "hostname": proxy[1],
                "port": int(proxy[2]),
                "username": proxy[3],
                "password": proxy[4]}
    elif len(proxy) == 3:
        return {"scheme": proxy[0],
                "hostname": proxy[1],
                "port": int(proxy[2])}
    else:
        return False


def startup():
    for token in managers:
        
        global MANAGERS_COUNT
        
        try:
            client = Client(f"bot{MANAGERS_COUNT}", api_id=API_ID, api_hash=API_HASH, bot_token=token[0])

            
            client.start()
            client.stop()
            
            apps.append(client)
            manager_apps.append(client)
            setup_manager(client)
            
            MANAGERS_COUNT += 1

        except UserDeactivatedBan:
            continue
        except Exception as e:
            print(e)
    
    for session in workers:
        try:
            
            if session[1]:
                try:
                    proxy = session[1].split(':')
                    proxy = format_proxy(proxy)

                    client = Client(session[0], api_id=API_ID, api_hash=API_HASH, proxy=proxy)
                except ConnectionError:
                    client = Client(session[0], api_id=API_ID, api_hash=API_HASH)
                except:
                    client = Client(session[0], api_id=API_ID, api_hash=API_HASH)
            
            else:
                client = Client(session[0], api_id=API_ID, api_hash=API_HASH)
            
            try:
                client.start()
                client.get_me()
                client.stop()
                
            except UserDeactivatedBan:
                sql_edit(f"DELETE FROM workers WHERE session = '{session[0]}'", ())
                continue
            except AuthKeyDuplicated:
                sql_edit(f"DELETE FROM workers WHERE session = '{session[0]}'", ())
                continue
            except Exception as e:
                continue
            
            apps.append(client)
            worker_apps.append(client)
            workers_list[session[0]] = client
            setup_worker(client)
        except Exception as e:
            print(e)


def setup_manager(app):
    
    manager_apps.append(app)
    
    @app.on_message(filters.command('clear_workers', '/'))
    async def callback(_, message):
        sql_edit('DELETE FROM workers', ())
        await message.reply('✅')
    
    @app.on_message(filters.command('start', '/'))
    async def callback(_, message):
        
        if not admins_only or message.from_user.id in admins:
        
            await app.delete_messages(message.chat.id, message.id)
            await app.send_message(message.from_user.id, "👮‍♀️")
            
            await app.send_message(message.from_user.id, "Ваше меню:", reply_markup=ReplyKeyboardMarkup(
                [['Мои аккаунты 🙂'], ['Меню 🌴'],
                 # ['Заменить токен OpenAI ♻️'],
                 # ['Заменить прокси для ChatGPT 🖥️'],
                 # ['Спарсить комментарии 💬', 'Поиск каналов 🔎'],
                 ], resize_keyboard=True))
    
    @app.on_message(filters.command('Мои аккаунты 🙂', ''))
    async def callback(_, message):
        
        if not admins_only or message.from_user.id in admins:
            await app.delete_messages(message.chat.id, message.id)
            
            sent = await app.send_message(message.from_user.id, "Минутку...")
            
            await accounts(sent)
        
    @app.on_message(filters.command('Меню 🌴', ''))
    async def callback(_, message):
        
        if not admins_only or message.from_user.id in admins:
            await app.delete_messages(message.chat.id, message.id)
            
            sent = await app.send_message(message.from_user.id, "Минутку...")
            
            await menu(sent)
    
    @app.on_message(filters.command('Заменить токен OpenAI ♻️', ''))
    async def callback(_, message):
        
        await app.delete_messages(message.chat.id, message.id)
        
        sent = await app.send_message(message.from_user.id, "Минутку...")
        
        await accounts(sent)
    
    @app.on_message(filters.command('Заменить прокси для ChatGPT 🖥️', ''))
    async def callback(_, message):
        
        await app.delete_messages(message.chat.id, message.id)
        
        sent = await app.send_message(message.from_user.id, "Минутку...")
        
        await accounts(sent)
    
    @app.on_message(filters.command('Спарсить комментарии 💬', ''))
    async def callback(_, message):
        
        await app.delete_messages(message.chat.id, message.id)
        
        sent = await app.send_message(message.from_user.id, "Минутку...")
        
        await accounts(sent)
    
    @app.on_message(filters.command('Поиск каналов 🔎', ''))
    async def callback(_, msg):
        
        sent = await app.send_message(
            msg.from_user.id, "🔍 Введите запрос для поиска:",
            reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))
        
        async def wait(message):
            await remove_handler(message.from_user.id)
            await app.delete_messages(sent.chat.id, sent.id)
            await app.delete_messages(message.chat.id, message.id)
            
            if message.text == 'Отмена ❌':
                sent2 = await app.send_message(message.from_user.id, "❌ Отменено",
                                               reply_markup=ReplyKeyboardRemove())
                await asyncio.sleep(2)
                await app.delete_messages(sent2.chat.id, sent2.id)
                return
            
            try:
                if workers_list:
                    
                    notification = await msg.reply(
                        'Ждём, пока ChatGPT предоставит нам список ключевых слов... 😊')
                    
                    keywords = generate_keywords(message.text)
                    keywords = keywords.split('\n')
                    
                    keywords_to_remove = []
                    
                    for i in range(len(keywords)):
                        keyword = keywords[i]
                        if '. ' not in keyword:
                            keywords_to_remove.append(keyword)
                        else:
                            keywords[i] = keyword.split('. ')[1]
                    
                    for keyword in keywords_to_remove:
                        keywords.remove(keyword)
                    
                    keywords.append(message.text)
                    
                    for keyword in keywords:
                        
                        channels = await list(workers_list.values())[0].invoke(Search(q=keyword, limit=100))
                        if channels.chats:
                            
                            text = f'🌴 Каналы по запросу "{keyword}":\n'
                            
                            i = 1
                            for channel in channels.chats:
                                if channel.broadcast:
                                    if channel.username:
                                        text += f'\n<b>{i}.</b> {channel.title} (@{channel.username})'
                                    elif channel.usernames:
                                        text += f'\n<b>{i}.</b> {channel.title} (@{channel.usernames[0].username})'
                                    i += 1
                            
                            await notification.reply(text)
            
            except Exception as e:
                await msg.reply(f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
        
        await add_handler(msg.from_user.id, wait)
    
    @app.on_message(filters.document)
    async def login(_, document):
        sent = await document.reply('🌴 Проверяем файл...')
        
        if document.document.file_name.endswith('.session'):
            
            async def progress(current, total):
                await sent.edit(f"🌴 Скачиваем файл... <code>{current * 100 / total:.1f}%</code>")
            
            directory = await app.download_media(
                document, file_name=f'{os.getcwd()}/{document.document.file_name}', progress=progress)
            
            await sent.edit(f"🌴 Файл скачан! {directory}")
            
            sent2 = await document.reply(
                "Введите SOCKS5 прокси в формате ниже:\n\n<code>scheme:ip:port:username:password</code>\n\n"
                "Пример: socks5:45.145.57.238:10253:ucXRvV:dcEscZ"
                "\n\n<i>/cancel для отмены</i>",
                reply_markup=ReplyKeyboardMarkup([['Без прокси']], resize_keyboard=True))
            
            async def wait_for(proxy):
                
                await remove_handler(document.from_user.id)
                
                await app.delete_messages(sent2.chat.id, sent2.id)
                await app.delete_messages(proxy.chat.id, proxy.id)
                
                try:
                    
                    if proxy.text == 'Без прокси':
                        client = Client(document.document.file_name[:-8], api_id=API_ID, api_hash=API_HASH)
                    
                    else:
                        
                        proxy_to_login = proxy.text.split(':')
                        proxy_to_login = format_proxy(proxy_to_login)
                        if not proxy_to_login:
                            await app.send_message(document.from_user.id,
                                                   "Неправильный формат прокси. Пример правильного формата ниже:\n\n"
                                                   "<pre>socks5:45.145.57.238:10253:ucXRvV:dcEscZ</pre>")
                            return
                        
                        client = Client(document.document.file_name[:-8],
                                        api_id=API_ID, api_hash=API_HASH, proxy=proxy_to_login)
                    
                    await client.start()
                    account_info = await client.get_me()
                    await client.stop()
                    
                    os.rename(document.document.file_name, str(account_info.phone_number) + '.tmp')
                    os.rename(str(account_info.phone_number) + '.tmp', str(account_info.phone_number) + '.session')
                    
                    if account_info.is_bot:
                        await sent.edit(f"🤖")
                        await asyncio.sleep(2)
                        await sent.reply(f"😕 Ботов пока что так добавлять нельзя, ещё не написал код под это")
                    else:
                        client = Client(str(account_info.phone_number), api_id=API_ID, api_hash=API_HASH)
                        await client.start()
                        try:
                            await client.send_message((await app.get_me()).username, '👋')
                        except Exception as e:
                            await sent.reply(f'Аккаунт пидарас - {e}')
                        setup_worker(client)
                        await sent.edit(f"😎")
                        
                        workers_list[account_info.phone_number] = client
                        
                        if proxy.text != 'Без прокси':
                            sql_edit('INSERT INTO workers VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                     (account_info.phone_number, proxy.text,
                                      'Вы - двадцатилетняя девушка',
                                      "Отвечу только когда перейдёшь по ссылке в описании)", 0, 1, 1,
                                      'Напиши интересный комментарий до 10 слов на тему этого поста:', 'text'))
                        else:
                            sql_edit('INSERT INTO workers VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                     (account_info.phone_number, None,
                                      'Вы - двадцатилетняя девушка',
                                      "Отвечу только когда перейдёшь по ссылке в описании)", 0, 1, 1,
                                      'Напиши интересный комментарий до 10 слов на тему этого поста:', 'text'))
                        
                        try:
                            await document.reply(
                                f'<b>{account_info.mention}</b> @{account_info.username}\n\n'
                                f'⭐ Премиум: {account_info.is_premium}\n'
                                f'🚫 Ограничения: {account_info.is_restricted}',
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton('Профиль ⛓️', user_id=account_info.id)]]))
                        except PeerIdInvalid:
                            await document.reply(
                                f'<b>{account_info.mention}</b> @{account_info.username}\n\n'
                                f'⭐ Премиум: {account_info.is_premium}\n'
                                f'🚫 Ограничения: {account_info.is_restricted}',
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton(
                                        'Профиль ⛓️', url=f'tg://user?id={account_info.id}')]]))
                    
                
                except Exception as e:
                    await app.send_message(document.from_user.id, f'😛 Произошла ошибка\n\n<pre>{e}</pre>',
                                           reply_markup=ReplyKeyboardRemove())
            
            await add_handler(document.from_user.id, wait_for)
            
        else:
            await sent.edit(f"😕 Бот работает только с файлами формата <code>.session</code>!")
            
    @app.on_message()
    async def handle(_, message):
        if not await is_handler(message):
            if message.text.startswith('https://t.me/') or message.text.startswith('t.me/'):
                msg = await message.reply('Получаем посты...')
                
                if worker_apps:
                    #тут сделать выбор акка
                    posts = message.text.split('\n')
                    
                    global SENT_TODAY
                    
                    for post in posts:
                        
                        client = random.choice(worker_apps)
                        
                        client_data = await client.get_me()
                        settings = sql_select(f"SELECT * FROM workers WHERE session = '{client_data.phone_number}'")

                        service_channel = sql_select('SELECT channel FROM managers')
                        
                        if post.startswith('https://t.me/'):
                            post = post[13:]
                        elif post.startswith('t.me/'):
                            post = post[5:]
                        
                        post = post.split('/')
                        if post[0].isdigit():
                            post[0] = int(post[0])
                        
                        try:

                            chat = await client.get_chat(post[0])
                            post_message = await client.get_discussion_message(chat.id, int(post[1]))

                            if post_message.caption:
                                post = post_message.caption
                            else:
                                post = post_message.text

                            # await app.get_discussion_replies()
                            if settings[0][9] == 1:

                                pretexts = sql_select(
                                    f"SELECT text FROM pretexts WHERE session = '{client_data.phone_number}'")

                                sent_message = None
                                try:

                                    if pretexts:
                                        sent_message = await post_message.reply(random.choice(pretexts)[0])
                                    else:
                                        sent_message = await post_message.reply(random.choice(emojies))

                                except Forbidden:
                                    try:
                                        await client.join_chat(post_message.chat.id)
                                        if pretexts:
                                            sent_message = await post_message.reply(random.choice(pretexts)[0])
                                        else:
                                            sent_message = await post_message.reply(random.choice(emojies))
                                    except Exception as e:
                                        print(e)
                                        if service_channel:
                                            await manager_apps[0].send_message(
                                                service_channel[0][0],
                                                f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                                f'{e}')
                                            continue

                                except Exception as e:
                                    print(e)
                                    if service_channel:
                                        await manager_apps[0].send_message(
                                            service_channel[0][0],
                                            f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                            f'{e}')
                                        continue

                                return

                            if settings[0][6] == 1:
                                sent_message = None
                                try:

                                    pretexts = sql_select(f"SELECT text FROM pretexts WHERE session = '{client_data.phone_number}'")

                                    if pretexts:
                                        sent_message = await post_message.reply(random.choice(pretexts)[0])
                                    else:
                                        sent_message = await post_message.reply(random.choice(emojies))

                                except Forbidden:
                                    try:
                                        await client.join_chat(post_message.chat.id)
                                        test_message = await post_message.reply('👍')
                                        await test_message.delete()
                                    except Exception as e:
                                        print(e)
                                        if service_channel:
                                            await manager_apps[0].send_message(
                                                service_channel[0][0],
                                                f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                                f'{e}')
                                            continue
                                except Exception as e:
                                    print(e)
                                    if service_channel:
                                        await manager_apps[0].send_message(
                                            service_channel[0][0],
                                            f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                            f'{e}')
                                        continue
                                    
                            else:
                                sent_message = None
                        
                        except Exception as e:
                            print(e)
                            if service_channel:
                                await manager_apps[0].send_message(
                                    service_channel[0][0],
                                    f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                    f'{e}')
                            return
                        
                        prompt = settings[0][7] + f' "{post}"'
                        
                        reply = None
                        output = await generate_response(prompt, settings[0][2], app)
                        
                        try:
                            if sent_message:
                                reply = await sent_message.edit(output)
                                SENT_TODAY += 1
                                # for admin in admins:
                                #     for client in worker_apps:
                                #         try:
                                #             await client.send_message(admin, reply.link)
                                #         finally:
                                #             pass
                            else:
                                try:
                                    reply = await post_message.reply(output)
                                except Forbidden:
                                    try:
                                        await client.join_chat(post_message.chat.id)
                                        await post_message.reply(output)
                                    except Exception as e:
                                        if service_channel:
                                            await manager_apps[0].send_message(
                                                service_channel[0][0],
                                                f'<b>Ошибка при комментарии в {post_message.chat.title}</b>\n\n'
                                                f'{e}')
                                # for admin in admins:
                                #     for client in worker_apps:
                                #         try:
                                #             await client.send_message(admin, reply.link)
                                #         finally:
                                #             pass
                            if service_channel and reply:
                                await manager_apps[0].send_message(
                                    service_channel[0][0],
                                    f'<b>Новый комментарий в {post_message.chat.title}</b>\n\n'
                                    f'{reply.link}'
                                )
                                
                            await msg.edit(msg.text + f'\n{reply.link}')
                        
                        except Exception as e:
                            if service_channel:
                                await manager_apps[0].send_message(
                                    service_channel[0][0],
                                    f'<b>Ошибка при комментарии в {post_message.chat.title}</b>\n\n'
                                    f'{e}')
                        
                        
                else:
                    await msg.edit('Сначала добавьте в бота аккаунты!')
        
        
    
    @app.on_callback_query()
    async def callback(_, callback_query):
        
        data = callback_query.data
        global workers_list
        
        if data.startswith('user'):
            try:
                await callback_query.message.edit('Получаем данные об аккаунте...')
                
                settings = sql_select(f"SELECT * FROM workers WHERE session = '{data.split()[1]}'")
                
                if settings[0][6] == 1:
                    be_first = '✅'
                else:
                    be_first = '❌'
                
                client = workers_list[data.split(' ', 1)[1]]
                
                client_data = await client.get_me()
                keyboard = []
                
                
                reply_text = (
                    f'<b>{client_data.mention}</b> @{client_data.username}:\n\n'
                    f'⭐ Премиум: {client_data.is_premium}\n'
                    f'🚫 Ограничения: {client_data.is_restricted}\n\n'
                    f'🤖 Роль: <code>{settings[0][2]}</code>\n'
                    f'🤖 Промпт: <code>{settings[0][7]}</code>\n\n'
                    f'👩‍🎓 Автоответ: <code>{settings[0][3]}</code>')
                
                keyboard.append(
                    [InlineKeyboardButton('Промпт 🤖', callback_data=f'set what_to_write {client_data.phone_number}')])
                keyboard.append(
                    [InlineKeyboardButton('Роль 🤖', callback_data=f'set prompt {client_data.phone_number}'),
                     InlineKeyboardButton('Автоответ 👩‍🎓', callback_data=f'set auto_reply {client_data.phone_number}')])
                keyboard.append(
                    [InlineKeyboardButton(
                        f'Задержка - {settings[0][4]} ⌛', callback_data=f'set delay {client_data.phone_number}'),
                     InlineKeyboardButton(
                         f'Шанс коммента - {settings[0][5]} 🎲', callback_data=f'set chance {client_data.phone_number}')])
                keyboard.append([InlineKeyboardButton('Профиль ⛓️', user_id=client_data.id),
                                 InlineKeyboardButton('✏️', callback_data=f'change {client_data.phone_number}')])
                keyboard.append(
                    [InlineKeyboardButton('Добавить каналы 💬', callback_data=f'newchannels {client_data.phone_number} comments'),
                     InlineKeyboardButton('Удалить аккаунт ❌', callback_data=f'del {client_data.phone_number}')])
                
                keyboard.append(
                    [InlineKeyboardButton(f'Комментировать первым {be_first}', callback_data=f'switchbefirst {client_data.phone_number}')])


                if settings[0][9] == 1:
                    use_gpt = '✅'
                else:
                    use_gpt = '❌'


                keyboard.append(
                    [InlineKeyboardButton(f'Комментировать шаблонами {use_gpt}', callback_data=f'switchgpt {client_data.phone_number}')])

                if settings[0][6] == 1:
                    keyboard.append(
                        [InlineKeyboardButton(f'Тексты первого коммента',
                                              callback_data=f'editpretexts {client_data.phone_number}')])

                keyboard.append(
                    [InlineKeyboardButton('Последние посты 🌴', callback_data=f'posts {client_data.phone_number}')])
                
                keyboard.append(
                    [InlineKeyboardButton('Список каналов 🧿', callback_data=f'allchannels {client_data.phone_number}')])

                keyboard.append(
                    [InlineKeyboardButton('Инвайтинг 🦁',
                                          callback_data=f'inviting {client_data.phone_number}')])
                keyboard.append(
                    [InlineKeyboardButton('Рассылка по лс 🌪',
                                          callback_data=f'spam_dms {client_data.phone_number}')])
                
                keyboard.append([InlineKeyboardButton('Все Аккаунты ◀️', callback_data='accounts')])
                
                try:
                    await callback_query.message.edit(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))
                except PeerIdInvalid:
                    keyboard = []
                    
                    keyboard.append(
                        [InlineKeyboardButton('Промпт 🤖',
                                              callback_data=f'set what_to_write {client_data.phone_number}')])
                    keyboard.append(
                        [InlineKeyboardButton('Роль 🤖', callback_data=f'set prompt {client_data.phone_number}'),
                         InlineKeyboardButton('Автоответ 👩‍🎓',
                                              callback_data=f'set auto_reply {client_data.phone_number}')])
                    keyboard.append(
                        [InlineKeyboardButton(f'Задержка - {settings[0][4]} ⌛',
                                              callback_data=f'set delay {client_data.phone_number}'),
                         InlineKeyboardButton(f'Шанс коммента - {settings[0][5]} 🎲',
                                              callback_data=f'set chance {client_data.phone_number}')])
                    keyboard.append([InlineKeyboardButton('Профиль ⛓️', url=f'tg://user?id={client_data.id}'),
                                     InlineKeyboardButton('✏️', callback_data=f'change {client_data.phone_number}')])
                    keyboard.append(
                        [InlineKeyboardButton('Добавить каналы 💬', callback_data=f'newchannels {client_data.phone_number} comments'),
                         InlineKeyboardButton('Удалить аккаунт ❌', callback_data=f'del {client_data.phone_number}')])
                    
                    keyboard.append(
                        [InlineKeyboardButton(f'Комментировать первым {be_first}',
                                              callback_data=f'switchbefirst {client_data.phone_number}')])

                    if settings[0][9] == 1:
                        use_gpt = '✅'
                    else:
                        use_gpt = '❌'

                    keyboard.append(
                        [InlineKeyboardButton(f'Комментировать шаблонами {use_gpt}',
                                              callback_data=f'switchgpt {client_data.phone_number}')])


                    if settings[0][6] == 1:
                        keyboard.append(
                            [InlineKeyboardButton(f'Тексты первого коммента',
                                                  callback_data=f'editpretexts {client_data.phone_number}')])
                    
                    keyboard.append(
                        [InlineKeyboardButton('Список каналов 🧿',
                                              callback_data=f'allchannels {client_data.phone_number}')])
                    keyboard.append(
                        [InlineKeyboardButton('Инвайтинг 🦁',
                                              callback_data=f'inviting {client_data.phone_number}')])
                    keyboard.append(
                        [InlineKeyboardButton('Рассылка по лс 🌪',
                                              callback_data=f'spam_dms {client_data.phone_number}')])

                    keyboard.append([InlineKeyboardButton('Все аккаунты ◀️', callback_data='accounts')])
                    
                    await callback_query.message.edit(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))
                    

            except Exception as e:
                await callback_query.message.reply(f'{workers_list}\n\n{e}')
                
        elif data.startswith('allchannels'):
            channels = sql_select(f"SELECT id FROM channels WHERE session = '{data.split()[1]}'")
            
            if not channels:
                await callback_query.answer('У этого аккаунта ещё нет подключенных аккаунтов 🙈',
                                            show_alert=True)
            else:
                
                await callback_query.message.edit('Минутку, ищем каналы...')
                
                client = workers_list[data.split()[1]]
                
                client_data = await client.get_me()
                
                text = (f'Аккаунт {client_data.mention} комментирует {len(channels)} каналов\n\n'
                        f'Чтобы удалить канал, нажмите на кнопку с его названием')
                
                kb = []
                
                for channel in channels:
                    try:
                        channel_object = await client.get_chat(channel[0])
                        
                        if channel_object:
                            kb.append([InlineKeyboardButton(
                                '❌' + channel_object.title, callback_data=f'removechannel {channel[0]} {data.split()[1]}')])
                    except Exception:
                        pass
                
                kb.append([InlineKeyboardButton('К аккаунту 👤', callback_data=f'user {data.split()[1]}')])
                kb.append([InlineKeyboardButton('Все аккаунты ◀️', callback_data='accounts')])
                
                await callback_query.message.edit(text, reply_markup=InlineKeyboardMarkup(kb))
            
        elif data.startswith('removechannel'):
            
            sql_edit(f"DELETE FROM channels WHERE id = {data.split()[1]} and session = '{data.split()[2]}'", ())
            client = workers_list[data.split()[2]]
            
            await callback_query.message.edit('Канал удалён', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('Обратно к каналам 🧿', callback_data=f'allchannels {data.split()[1]}')],
                [InlineKeyboardButton('Все Аккаунты ◀️', callback_data='accounts')]]))
            
            await app.leave_chat(data.split()[1])
            
        elif data.startswith('switchbefirst'):
            
            current = sql_select(f"SELECT be_first FROM workers WHERE session = '{data.split()[1]}'")
            
            if current and current[0]:
                if current[0][0] == 0:
                    text = 'Теперь бот будет комментировать посты первым 🙂'
                    val = 1
                else:
                    text = 'Теперь бот НЕ будет комментировать посты первым 🙂'
                    val = 0
            
                sql_edit(f"UPDATE workers SET be_first = {val} WHERE session = '{data.split()[1]}'", ())
                await callback_query.message.edit(text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('К аккаунту 👤', callback_data=f'user {data.split()[1]}')],
                    [InlineKeyboardButton('Список аккаунтов ◀️', callback_data='accounts')]]))
            
        elif data.startswith('switchgpt'):

            current = sql_select(f"SELECT dont_use_gpt FROM workers WHERE session = '{data.split()[1]}'")

            if current and current[0]:
                if current[0][0] == 0:
                    text = 'Теперь бот будет комментировать посты шаблонами 🙂'
                    val = 1
                else:
                    text = 'Теперь бот НЕ будет комментировать посты шаблонами 🙂'
                    val = 0

                sql_edit(f"UPDATE workers SET dont_use_gpt = {val} WHERE session = '{data.split()[1]}'", ())
                await callback_query.message.edit(text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('К аккаунту 👤', callback_data=f'user {data.split()[1]}')],
                    [InlineKeyboardButton('Список аккаунтов ◀️', callback_data='accounts')]]))

        elif data.startswith('accounts'):
            await accounts(callback_query.message)
            
        elif data.startswith('del'):
            
            client = workers_list[data.split(' ', 1)[1]]
            
            client_data = await client.get_me()
            
            await callback_query.message.edit(
                f'Вы уверены, что хотите удалить аккаунт {client_data.mention}?',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('Да, удаляем', callback_data='confirm' + data)],
                    [InlineKeyboardButton('Назад ◀️', callback_data='accounts')]])
            )
        
        elif data.startswith('confirmdel'):
            
            client = workers_list[data.split(' ', 1)[1]]
            
            client_data = await client.get_me()
            await client.stop()
            workers_list.pop(data.split(' ', 1)[1])
            sql_edit(f'DELETE FROM workers WHERE session = \'{data.split(" ", 1)[1]}\'', ())
            await callback_query.message.edit(f'Аккаунт {client_data.mention} был удалён.')
            await asyncio.sleep(1)
            await accounts(callback_query.message)
        
        elif data.startswith('posts'):
            
            await callback_query.message.edit('🌴 Введите, сколько постов нам нужно получить с каждого канала:')
            
            async def wait(amount_message):
                
                amount = int(amount_message.text)
                
                if not amount:
                    await callback_query.message.edit('❌ Похоже, вы ввели не число')
                    await asyncio.sleep(2)
                    await accounts(callback_query.message)
                    return False
                
                client = workers_list[data.split()[1]]
                client_data = await client.get_me()
                
                all_channels = sql_select(f"SELECT id FROM channels WHERE session = '{client_data.phone_number}'")

                workbook = xlsxwriter.Workbook(f'посты{client_data.phone_number}.xlsx')
                
                worksheet = workbook.add_worksheet('Посты')
                
                index = 0
                for chat_id in all_channels:
                    
                    i = 0
                    
                    channel_info = await client.get_chat(chat_id[0])
                    worksheet.write(0, index, channel_info.title)
                    
                    async for message in client.get_chat_history(chat_id[0], limit=amount):
                        
                        global SENT_TODAY
                        
                        settings = sql_select(f"SELECT * FROM workers WHERE session = '{client_data.phone_number}'")

                        await asyncio.sleep(settings[0][4])
                        
                        if random.randint(1, settings[0][5]) == 1 and SENT_TODAY < LIMIT and (
                                message.text or message.caption):
                            
                            if message.caption:
                                post = message.caption
                            else:
                                post = message.text
                            
                            try:
                                message = await app.get_discussion_message(message.sender_chat.id, message.id)
                                # await app.get_discussion_replies()

                                if settings[0][9] == 1:

                                    pretexts = sql_select(
                                        f"SELECT text FROM pretexts WHERE session = '{client_data.phone_number}'")

                                    sent_message = None
                                    try:

                                        if pretexts:
                                            sent_message = await message.reply(random.choice(pretexts)[0])
                                        else:
                                            sent_message = await message.reply(random.choice(emojies))

                                    except Forbidden:
                                        try:
                                            await client.join_chat(message.chat.id)
                                            if pretexts:
                                                sent_message = await message.reply(random.choice(pretexts)[0])
                                            else:
                                                sent_message = await message.reply(random.choice(emojies))
                                        except Exception as e:
                                            print(e)
                                            # if service_channel:
                                            #     await manager_apps[0].send_message(
                                            #         service_channel[0][0],
                                            #         f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                            #         f'{e}')
                                            #     continue

                                    except Exception as e:
                                        print(e)
                                        # if service_channel:
                                        #     await manager_apps[0].send_message(
                                        #         service_channel[0][0],
                                        #         f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                        #         f'{e}')
                                        #     continue

                                    return

                                if settings[0][6] == 1:

                                    pretexts = sql_select(
                                        f"SELECT text FROM pretexts WHERE session = '{client_data.phone_number}'")

                                    if pretexts:
                                        sent_message = await message.reply(random.choice(pretexts)[0])
                                    else:
                                        sent_message = await message.reply(random.choice(emojies))

                                    print(sent_message.link)
                                else:
                                    sent_message = None
                            
                            except Exception as e:
                                print(1)
                                print(e)
                                return
                            
                            print(1)
                            prompt = settings[0][7] + f' "{post}"'

                            output = await generate_response(prompt, settings[0][2], app)

                            try:
                                if sent_message:
                                    reply = await sent_message.edit(output)
                                    SENT_TODAY += 1
                                    # for admin in admins:
                                    #     for client in worker_apps:
                                    #         try:
                                    #             await client.send_message(admin, reply.link)
                                    #         finally:
                                    #             pass
                                else:
                                    reply = await message.reply(output)
                                    # for admin in admins:
                                    #     for client in worker_apps:
                                    #         try:
                                    #             await client.send_message(admin, reply.link)
                                    #         finally:
                                    #             pass
                                
                                print(reply.link)
                            
                            except Exception as e:
                                print(2)
                                print(e)
                        
                        worksheet.write(1 + 2*i, index, message.text)
                        worksheet.write(2 + 2*i, index, message.link)
                        
                        i += 1
                    
                    index += 1
                
                workbook.close()
                await accounts(callback_query.message)
                await callback_query.message.reply_document(f'посты{client_data.phone_number}.xlsx')
            
            await add_handler(callback_query.from_user.id, wait)

        elif data.startswith('inviting'):

            client = workers_list[data.split()[1]]
            client_data = await client.get_me()

            await callback_query.message.edit('🌴 Пришлите ссылку на группу, в которую добавлять людей:')
            async def wait(channel_text):

                await remove_handler(channel_text.from_user.id)

                channel = channel_text.text
                if channel.startswith('https://t.me/+') or channel.startswith('https://t.me/-'):
                    pass
                elif channel.startswith('https://t.me/'):
                    channel = channel[13:]
                elif channel.startswith('t.me/'):
                    channel = channel[5:]
                elif channel.startswith('@'):
                    channel = channel[1:]
                elif channel.isdigit():
                    channel = int(channel)

                try:
                    group = await client.get_chat(channel)
                    res = await client.join_chat(channel)
                    if res:
                        await channel_text.reply(f'Успешно зашли в {group.title}')
                    else:
                        await channel_text.reply('Не получилось зайти в чат...')
                        return
                except UserAlreadyParticipant:
                    await channel_text.reply(f'Аккаунт уже в группе')
                except Exception as e:
                    await channel_text.reply(f'Не нашли чат. {e}')
                    return

                await callback_query.message.reply(
                    '🌴 Пришлите список людей для инвайта, каждый с новой строчки. Например:\n\n'
                    '@человек1\n@человек2')

                async def wait2(people_list):

                    await remove_handler(people_list.from_user.id)
                    await app.delete_messages(people_list.from_user.id, people_list.id)

                    await callback_query.message.reply(
                        'С каким промежутком добавлть людей? Для рандомного выбора напишите промежуток в таком формате: 1-5 (от 1й до 5ти сек)',
                    reply_markup=ReplyKeyboardMarkup([['Без задержки']]))


                    async def wait3(timeout):

                        await remove_handler(channel_text.from_user.id)
                        spl = timeout.text.split('-')

                        async def count_cooldown():

                            if timeout.text == 'Без задержки':
                                secs = 0
                            elif len(spl) > 1:
                                secs = random.randint(int(spl[0]), int(spl[1]))
                            else:
                                secs = int(timeout.text)

                            return secs

                        res_msg = await callback_query.message.reply('Запустили инвайтинг!',
                                                                     reply_markup=ReplyKeyboardRemove())

                        total = 0
                        successes = 0
                        failures = 0

                        users_to_add = []

                        for person in people_list.text.split('\n'):

                            total += 1

                            if person.startswith('https://t.me/'):
                                person = person[13:]
                            elif person.startswith('t.me/'):
                                person = person[5:]
                            elif person.startswith('@'):
                                person = person[1:]
                            elif person.isdigit():
                                person = int(person)

                            users_to_add.append(person)

                            try:
                                await client.add_chat_members(group.id, users_to_add)
                                successes += 1
                            except Exception as e:
                                await app.send_message(channel_text.from_user.id, f'Ошибка:\n\n<pre>{e}</pre>')
                                failures += 1

                            await asyncio.sleep(await count_cooldown())



                        await app.send_message(
                            people_list.from_user.id,
                            f'Рассылка с аккаунта {client_data.mention}:\n\n'
                            f'{total}/{len(people_list.text.split('\n'))}\n\n'
                            f'Отправлено {successes}\n'
                            f'Ошибок {failures}')

                    await add_handler(callback_query.from_user.id, wait3)

                await add_handler(callback_query.from_user.id, wait2)

            await add_handler(callback_query.from_user.id, wait)

        elif data.startswith('spam_dms'):

            await callback_query.message.edit('🌴 Пришлите сообщение для рассылки:')

            async def wait(message):

                await remove_handler(message.from_user.id)

                await callback_query.message.reply('🌴 Пришлите список людей для рассылки, каждый с новой строчки. Например:\n\n'
                                                   '@человек1\n@человек2')


                async def wait2(people_list):
                    await remove_handler(people_list.from_user.id)
                    await app.delete_messages(people_list.from_user.id, people_list.id)

                    await callback_query.message.reply(
                        'С каким промежутком рассылать сообщения? Для рандомного выбора напишите промежуток в таком формате: 1-5 (от 1й до 5ти сек)',
                    reply_markup=ReplyKeyboardMarkup([['Без задержки']]))

                    async def wait3(timeout):

                        spl = timeout.text.split('-')

                        async def count_cooldown():

                            if timeout.text == 'Без задержки':
                                secs = 0
                            elif len(spl) > 1:
                                secs = random.randint(int(spl[0]), int(spl[1]))
                            else:
                                secs = int(timeout.text)

                            return secs

                        await remove_handler(people_list.from_user.id)
                        await app.delete_messages(people_list.from_user.id, timeout.id)

                        client = workers_list[data.split()[1]]
                        client_data = await client.get_me()


                        await client.send_message(BOT_LINK, random.choice(emojies))
                        await app.copy_message(client_data.id, message.chat.id, message.id)

                        msg = None
                        async for iMsg in client.get_chat_history(BOT_ID, limit=1, offset_id=-1):
                            msg = iMsg

                        total = 0
                        successes = 0
                        failures = 0

                        await callback_query.message.reply(
                            'Запустили рассылку!',
                            reply_markup=ReplyKeyboardMarkup([['Мои аккаунты 🙂'], ['Меню 🌴']],
                                                             resize_keyboard=True))

                        for person in people_list.text.split('\n'):

                            total += 1

                            if person.startswith('https://t.me/'):
                                person = person[13:]
                            elif person.startswith('t.me/'):
                                person = person[5:]
                            elif person.startswith('@'):
                                person = person[1:]
                            if person.isdigit():
                                person = int(person)

                            try:

                                await client.copy_message(person, BOT_ID, msg.id)
                                successes += 1
                            except Exception as e:
                                failures += 1
                                await message.reply(f'Ошибка при отправке сообщения @{person}:\n\n<pre>{e}</pre>')

                            await asyncio.sleep(await count_cooldown())

                        await app.send_message(
                            people_list.from_user.id,
                            f'Рассылка с аккаунта {client_data.mention}:\n\n'
                            f'{total}/{len(people_list.text.split('\n'))}\n\n'
                            f'Отправлено {successes}\n'
                            f'Ошибок {failures}')

                    await add_handler(callback_query.from_user.id, wait3)

                await add_handler(callback_query.from_user.id, wait2)

            await add_handler(callback_query.from_user.id, wait)

        elif data.startswith('newchannels'):
            
            if len(data.split()) < 3:
                await callback_query.message.edit(
                    'Выберите цель добавления каналов',
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton('Комментарии', callback_data=data + ' comments')],
                         [InlineKeyboardButton('Посты', callback_data=data + ' posts')]]))
            else:
            
                await callback_query.message.edit('🌴 Введите список каналов, каждый канал с новой строчки:')
                
                async def wait(message):
                    
                    await remove_handler(message.from_user.id)
                    await app.delete_messages(message.from_user.id, message.id)
                    
                    channels = message.text.split('\n')
                    
                    client = workers_list[data.split()[1]]
                    client_data = await client.get_me()
                    
                    success = 0
                    fail = 0
                    
                    await callback_query.message.edit(
                        f'<b>🌴 Вы прислали {len(channels)} каналов.</b> '
                        f'Начинаем вступать в них с аккаунта {client_data.first_name}...')
                    
                    for channel in channels:
                        
                        if channel.startswith('https://t.me/+') or channel.startswith('https://t.me/-'):
                            pass
                        elif channel.startswith('https://t.me/'):
                            channel = channel[13:]
                        elif channel.startswith('t.me/'):
                            channel = channel[5:]
                        elif channel.startswith('@'):
                            channel = channel[1:]
                        elif channel.isdigit():
                            channel = int(channel)
                        
                        try:
                            res = await client.join_chat(channel)
                            sql_edit(
                                f"INSERT INTO channels VALUES(?, '{data.split()[1]}', '{data.split()[2]}')", (res.id,))
                            success += 1
                            
                            async for message in client.get_chat_history(res.id, limit=1, offset_id=-1):
                                dmsg = await client.get_discussion_message(res.id, message.id)
                                try:
                                    msg = await dmsg.reply('👍')
                                    await msg.delete()
                                except Forbidden:
                                    
                                    try:
                                        await client.join_chat(dmsg.chat.id)
                                        msg = await dmsg.reply('👍')
                                        await msg.delete()
                                    except Exception as e:
                                        print(e)
                                except Exception as e:
                                    print(e)
                                    
                            
                            
                            text = f'<b>🌴 Вступаю в каналы...</b>\n\n✅ {success}'
                            if fail > 0:
                                text += f'\n❌ {fail}'
                                
                            await callback_query.message.edit(text)
                            
                        except Exception as e:
                            fail += 1
                            await callback_query.message.edit(f'<b>🌴 Вступаю в каналы...</b>\n\n✅ {success}\n❌ {fail}')
                            await callback_query.message.reply(
                                f'🤷‍♂️ Не получилось зайти в @{channel}<pre>{e}</pre>')
                            
                        
                        text = f'<b>🌴 Закончили вступать в каналы!</b>\n\n✅ {success}'
                        if fail > 0:
                            text += f'\n❌ {fail}'
                            
                        await callback_query.message.edit(text, reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton('К аккаунту 👤', callback_data=f'user {data.split()[1]}')],
                            [InlineKeyboardButton('Все Аккаунты ◀️', callback_data='accounts')]]))
                    
                await add_handler(callback_query.from_user.id, wait)



        elif data.startswith('delpretext'):

            sql_edit(f'DELETE FROM pretexts WHERE id = {data.split()[1]}', ())
            await pretexts_menu(callback_query)


        elif data.startswith('editpretexts'):

            await pretexts_menu(callback_query)


        elif data.startswith('addpretexts'):
            await callback_query.message.edit('🌴 Введите тексты, каждый текст с новой строчки:')

            async def wait(message):

                await remove_handler(message.from_user.id)
                await app.delete_messages(message.from_user.id, message.id)

                pretexts = message.text.split('\n')

                for pretext in pretexts:
                    sql_edit(f"INSERT INTO pretexts(text, session) VALUES('{pretext}', '{data.split()[1]}')", ())

                await pretexts_menu(callback_query)

            await add_handler(callback_query.from_user.id, wait)


        elif data.startswith('change'):

            client = workers_list[data.split(" ", 2)[1]]
            
            
            client_data = await client.get_me()
            
            data_text = f'<b>Изменение профиля</b>\n\nТекущие данные:\n\n'\
                        f'Имя: <code>{client_data.first_name}</code>'
            
            if client_data.last_name:
                data_text += f'\nФамилия: <code>{client_data.last_name}</code>'
            else:
                data_text += f'\nФамилия не задана'
            
            if client_data.photo:
                data_text += f'\nФото: ✅'
            else:
                data_text += f'\nФото не задано'
            
            data_text += f'\n\n👇 Чтобы поменять или задать данные профиля, жмите кнопки ниже'
            
            try:
                await callback_query.message.edit(data_text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('Фото', callback_data=f'update photo {client_data.phone_number}'),
                     InlineKeyboardButton('Имя', callback_data=f'update first_name {client_data.phone_number}')],
                    [InlineKeyboardButton('Описание', callback_data=f'update about {client_data.phone_number}'),
                     InlineKeyboardButton('Фамилия', callback_data=f'update last_name {client_data.phone_number}')],
                    [InlineKeyboardButton('Юзернейм', callback_data=f'update username {client_data.phone_number}')],
                    [InlineKeyboardButton('Профиль ⛓️', user_id=client_data.id)],
                    [InlineKeyboardButton('Назад ◀️', callback_data=f'user {client_data.phone_number}')]]))
            except PeerIdInvalid:
                await callback_query.message.edit(data_text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('Фото', callback_data=f'update photo {client_data.phone_number}'),
                     InlineKeyboardButton('Имя', callback_data=f'update first_name {client_data.phone_number}')],
                    [InlineKeyboardButton('Описание', callback_data=f'update about {client_data.phone_number}'),
                     InlineKeyboardButton('Фамилия', callback_data=f'update last_name {client_data.phone_number}')],
                    [InlineKeyboardButton('Юзернейм', callback_data=f'update username {client_data.phone_number}')],
                    [InlineKeyboardButton('Профиль ⛓️', url=f'tg://user?id={client_data.id}')],
                    [InlineKeyboardButton('Назад ◀️', callback_data=f'user {client_data.phone_number}')]]))
                
        
        elif data == 'Main menu':
            await menu(callback_query.message)
        
        elif data.startswith('update'):
            
            args = data.split(" ", 2)
            client = workers_list[args[2]]
            
            async def end(message, client=client):
                await asyncio.sleep(2)
                
                client_data = await client.get_me()
                
                data_text = f'<b>Изменение профиля</b>\n\nТекущие данные:\n\n' \
                            f'Имя: <code>{client_data.first_name}</code>'
                
                if client_data.last_name:
                    data_text += f'\nФамилия: <code>{client_data.last_name}</code>'
                else:
                    data_text += f'\nФамилия не задана'
                
                if client_data.photo:
                    data_text += f'\nФото: ✅'
                else:
                    data_text += f'\nФото не задано'
                
                data_text += f'\n\n👇 Чтобы поменять или задать данные профиля, жмите кнопки ниже'
                
                try:
                    await callback_query.message.edit(data_text, reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('Фото', callback_data=f'update photo {client_data.phone_number}'),
                         InlineKeyboardButton('Имя', callback_data=f'update first_name {client_data.phone_number}')],
                        [InlineKeyboardButton('Описание', callback_data=f'update about {client_data.phone_number}'),
                         InlineKeyboardButton('Фамилия', callback_data=f'update last_name {client_data.phone_number}')],
                        [InlineKeyboardButton('Юзернейм', callback_data=f'update username {client_data.phone_number}')],
                        [InlineKeyboardButton('Профиль ⛓️', user_id=client_data.id)],
                        [InlineKeyboardButton('Назад ◀️', callback_data=f'user {client_data.phone_number}')]]))
                except PeerIdInvalid:
                    await callback_query.message.edit(data_text, reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('Фото', callback_data=f'update photo {client_data.phone_number}'),
                         InlineKeyboardButton('Имя', callback_data=f'update first_name {client_data.phone_number}')],
                        [InlineKeyboardButton('Описание', callback_data=f'update about {client_data.phone_number}'),
                         InlineKeyboardButton('Фамилия', callback_data=f'update last_name {client_data.phone_number}')],
                        [InlineKeyboardButton('Юзернейм', callback_data=f'update username {client_data.phone_number}')],
                        [InlineKeyboardButton('Профиль ⛓️', url=f'tg://user?id={client_data.id}')],
                        [InlineKeyboardButton('Назад ◀️', callback_data=f'user {client_data.phone_number}')]]))
                
            
            async def wait_for_photo(message, client=client):
                
                await remove_handler(message.from_user.id)
                await callback_query.message.edit('🌴 Ищем медиа...')
                
                async def progress(current, total):
                    await callback_query.message.edit(
                        f"🌴 Скачиваем аватарку... <code>{current * 100 / total:.1f}%</code>")
                
                if message.video:
                    
                    avatarka = await app.download_media(message, progress=progress, in_memory=True)
                    
                    await client.set_profile_photo(video=avatarka)
                    
                    await callback_query.message.edit(f"🌴 Фото профиля было успешно изменено!")
                
                elif message.photo:
                    
                    avatarka = await app.download_media(message, progress=progress,  in_memory=True)
                    
                    await client.set_profile_photo(photo=avatarka)
                    
                    await callback_query.message.edit(f"🌴 Фото профиля было успешно изменено!")
                
                else:
                    await callback_query.message.edit('❌ В качестве аватарки можно поставить только фото или видео')
                
                await app.delete_messages(message.from_user.id, message.id)
                await end(callback_query.message, client)
                
            async def wait_for_name(message, client=client):
                
                await remove_handler(message.from_user.id)
                
                if message.text:
                    try:
                        await client.update_profile(first_name=message.text)
                    except Exception as e:
                        await callback_query.message.edit(f'❌ Произошла ошибка<pre>{e}</pre>')
                else:
                    await callback_query.message.edit('❌ Имя должно быть текстом')
                
                await app.delete_messages(message.from_user.id, message.id)
                await end(callback_query.message, client)
                
            async def wait_for_surname(message, client=client):
                
                await remove_handler(message.from_user.id)
                
                if message.text:
                    try:
                        await client.update_profile(last_name=message.text)
                    except Exception as e:
                        await callback_query.message.edit(f'❌ Произошла ошибка<pre>{e}</pre>')
                else:
                    await callback_query.message.edit('❌ Фамилия должна быть текстом')
                
                await app.delete_messages(message.from_user.id, message.id)
                await end(callback_query.message, client)
                
            async def wait_for_about(message, client=client):
                
                await remove_handler(message.from_user.id)
                
                if message.text:
                    try:
                        await client.update_profile(bio=message.text)
                    except Exception as e:
                        await callback_query.message.edit(f'❌ Произошла ошибка<pre>{e}</pre>')
                else:
                    await callback_query.message.edit('❌ Описание должно быть текстом')
                
                await app.delete_messages(message.from_user.id, message.id)
                await end(callback_query.message, client)
                
            async def wait_for_username(message, client=client):
                
                await remove_handler(message.from_user.id)
                
                if message.text:
                    try:
                        await client.set_username(username=message.text)
                    except Exception as e:
                        await callback_query.message.edit(f'❌ Произошла ошибка<pre>{e}</pre>')
                else:
                    await callback_query.message.edit('❌ @юзернейм должен быть текстом')
                
                await app.delete_messages(message.from_user.id, message.id)
                await end(callback_query.message, client)
                
            functions = {
                'photo': ('новое фото', wait_for_photo),
                'first_name': ('новое имя', wait_for_name),
                'last_name': ('новую фамилию', wait_for_surname),
                'about': ('новое описание', wait_for_about),
                'username': ('новый @юзернейм', wait_for_username),
            }
            
            await callback_query.message.edit(f'✏️ Пришлите боту {functions[args[1]][0]}:')
            
            await add_handler(callback_query.from_user.id, functions[args[1]][1])
        
        elif data.startswith('confirmset auto_reply'):
            async def wait(info):
                
                await callback_query.message.edit(
                    '<b>Введите новый текст для автоответчика:</b>\n\n'
                    'Можете написать что угодно. Например, предложение подписаться на ваш канал')
                
                await app.delete_messages(info.chat.id, info.id)
                
                try:
                    await remove_handler(callback_query.from_user.id)
                    sql_edit(f"UPDATE workers SET {data.split(' ', 2)[1]} = ? "
                             f"WHERE session = '{data.split(' ', 2)[2]}'", (info.text,))

                    await callback_query.message.edit('👍 Данные обновлены')
                    await asyncio.sleep(2)
                    await menu(callback_query.message)
                
                except Exception as e:
                    await callback_query.message.edit(info.from_user.id, f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
                    await remove_handler(callback_query.from_user.id)
            
            await add_handler(callback_query.from_user.id, wait)
        
        elif data.startswith('no auto_reply'):
            sql_edit(f"UPDATE workers SET {data.split(' ', 2)[1]} = ? "
                     f"WHERE session = '{data.split(' ', 2)[2]}'", ('-',))
            await callback_query.message.edit(
                'Автоответчик был отключён на этом аккаунте.',
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton('Назад к аккаунту ◀️', callback_data='user ' + data.split()[2])]]))
            
        elif data.startswith('set'):
            
            if data.startswith('set prompt'):
                await callback_query.message.edit(
                    'Введите новую роль для ChatGPT:\n\n'
                    'Например:\n\n'
                    '• <code>Вы - студентка</code>\n'
                    '• <code>Вы - маркетолог</code>\n'
                    '• <code>Вы - Стив Джобс</code>\n')
            if data.startswith('set what_to_write'):
                await callback_query.message.edit(
                    'Введите новый промпт для ChatGPT:\n\n'
                    'Например:\n\n'
                    '• <code>Напиши интересный комментарий до 10 слов на тему этого поста:</code>\n'
                    '• <code>Напиши короткую историю на тему этого поста:</code>\n'
                    '• <code>Придумай шутку на тему этого поста:</code>\n')
            elif data.startswith('set auto_reply'):
                await callback_query.message.edit(
                    'Выберите действие:',
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton('Задать новый текст ✏️', callback_data='confirm' + data)],
                         [InlineKeyboardButton('Убрать автоответ', callback_data='no auto_reply ' + data.split()[2]),
                          InlineKeyboardButton('Назад ◀️', callback_data='user ' + data.split()[2])]]))
                return
            
            elif data.startswith('set delay'):
                await callback_query.message.edit('Введите новое значение задержки, в секундах:')
            
            elif data.startswith('set chance'):
                await callback_query.message.edit('Введите шанс, с которым будут оставляться комментарии\n\n'
                                                  'Если хотите 33%, введите 3 (1к<b>3</b>)\n'
                                                  'Если хотите 50%, введите 2 (1к<b>3</b>)\n'
                                                  'Если хотите 100%, введите 1 (1к<b>1</b>)')
            
            async def wait(info):
                
                await app.delete_messages(info.chat.id, info.id)
                
                try:
                    await remove_handler(callback_query.from_user.id)
                    sql_edit(f"UPDATE workers SET {data.split(' ', 2)[1]} = ? "
                             f"WHERE session = '{data.split(' ', 2)[2]}'", (info.text,))

                    await callback_query.message.edit('👍 Данные обновлены',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton('Назад к аккаунту ◀️',
                                                  callback_data='user ' + data.split(" ", 2)[2])]]))
                
                except Exception as e:
                    await callback_query.message.edit(
                        info.from_user.id, f'😛 Произошла ошибка\n\n<pre>{e}</pre>',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton('Назад к аккаунту ◀️',
                                                  callback_data='user ' + data.split(" ", 2)[2])]]))
                    await remove_handler(callback_query.from_user.id)
            
            await add_handler(callback_query.from_user.id, wait)

        elif data.startswith('bot'):
            
            sent = await app.send_message(callback_query.from_user.id,
                                          "🤖 Введите токен бота, который будет "
                                          "использоваться для управления аккаунтами:",
                                          reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))
            
            async def wait(token):
                
                await remove_handler(callback_query.from_user.id)
                await app.delete_messages(token.chat.id, token.id)
                await app.delete_messages(sent.chat.id, sent.id)
                
                if token.text == 'Отмена ❌':
                    
                    sent2 = await app.send_message(callback_query.from_user.id,
                                                  "❌ Отменено",
                                                  reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    return
            
                try:
                    global MANAGERS_COUNT
                    
                    client = Client(f"bot{MANAGERS_COUNT}", api_id=API_ID, api_hash=API_HASH, bot_token=token.text)
                    MANAGERS_COUNT += 1
                    
                    setup_manager(client)
                    await client.start()
                    
                    sql_edit('INSERT INTO managers(token) VALUES(?)', (token.text,))
                    sent2 = await app.send_message(callback_query.from_user.id, "👌 Бот подключен",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                
                except Exception as e:
                    await sent.edit(f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
            
            await add_handler(callback_query.from_user.id, wait)
        
        elif data.startswith('search'):
            
            sent = await app.send_message(callback_query.from_user.id,
                                          "🔍 Введите запрос для поиска:",
                                          reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))
            
            async def wait(message):
                await remove_handler(callback_query.from_user.id)
                await app.delete_messages(sent.chat.id, sent.id)
                await app.delete_messages(message.chat.id, message.id)
                
                if message.text == 'Отмена ❌':
                    sent2 = await app.send_message(callback_query.from_user.id, "❌ Отменено",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    return
                
                try:
                    if workers_list:
                        
                        notification = await callback_query.message.reply(
                            'Ждём, пока ChatGPT предоставит нам список ключевых слов... 😊')
                        

                        keywords = generate_keywords(message.text)
                        keywords = keywords.split('\n')
                        
                        keywords_to_remove = []
                        
                        for i in range(len(keywords)):
                            keyword = keywords[i]
                            if '. ' not in keyword:
                                keywords_to_remove.append(keyword)
                            else:
                                keywords[i] = keyword.split('. ')[1]
                        
                        for keyword in keywords_to_remove:
                            keywords.remove(keyword)
                        
                        keywords.append(message.text)
                        
                        for keyword in keywords:
                        
                            channels = await list(workers_list.values())[0].invoke(Search(q=keyword, limit=100))
                            if channels.chats:
                            
                                text = f'🌴 Каналы по запросу "{keyword}":\n'
                                
                                i = 1
                                for channel in channels.chats:
                                    if channel.broadcast:
                                        if channel.username:
                                            text += f'\n<b>{i}.</b> {channel.title} (@{channel.username})'
                                        elif channel.usernames:
                                            text += f'\n<b>{i}.</b> {channel.title} (@{channel.usernames[0].username})'
                                        i += 1
                                
                            
                                await notification.reply(text)
                    
                except Exception as e:
                    await callback_query.message.reply(f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
            
            await add_handler(callback_query.from_user.id, wait)
        
        
        elif data.startswith('parse_comments'):
            
            sent = await app.send_message(
                callback_query.from_user.id, "🌴 Введите ссылку на канал:",
                reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))
            
            async def wait(message, sent=sent):
                await remove_handler(callback_query.from_user.id)
                await app.delete_messages(sent.chat.id, sent.id)
                await app.delete_messages(message.chat.id, message.id)
                
                if message.text == 'Отмена ❌':
                    sent2 = await app.send_message(callback_query.from_user.id, "❌ Отменено",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    return
                
                try:
                    
                    if workers_list:
                    
                        if message.text.startswith('https://t.me/'):
                            chat_id = str(message.text[13:])
                        elif message.text.startswith('t.me/'):
                            chat_id = str(message.text[5:])
                        else:
                            chat_id = message.text
                        
                        client = random.choice(list(workers_list.values()))
                        
                        msgs = []
                        users = []
                        usernames = []
                        
                        global working
                        invalids = 0
                        
                        working = True
                        
                        async for msg in client.get_chat_history(chat_id):
                            msgs.append(msg.id)
                        
                        sent = await callback_query.message.reply(
                            f'Найдено {len(msgs)} постов, начинаю парсить комментарии\n\n'
                            f'<i>Завершить парсинг досрочно - /finish</i>')
                        
                        async def finish(finishmessage):
                            if finishmessage.text == '/finish':
                                global working
                                working = False
                                
                        await add_handler(callback_query.from_user.id, finish)
                        
                        
                        for message_id in msgs:
                            if working:
                                
                                try:
                                    client = random.choice(list(workers_list.values()))
                                    async for message in client.get_discussion_replies(chat_id, message_id):
                                        
                                        if message.from_user and not message.from_user.id in users:
                                            users.append(message.from_user.id)
                                        
                                        if (message.from_user and message.from_user.username
                                                and not message.from_user.username in usernames):
                                            usernames.append(message.from_user.username)
                                
                                except FloodWait as e:
                                    await asyncio.sleep(e.value)
                                
                                except MsgIdInvalid:
                                    invalids += 1
                                    await sent.edit(f'Найдено {len(msgs)} постов, парсинг в процессе\n'
                                                    f'Бот не смог получить {invalids}💬\n\n'
                                                    f'<i>Завершить парсинг досрочно - /finish</i>')
                                    
                                except Exception as e:
                                    await callback_query.message.reply(
                                        f'🤖 Ошибка при парсинге\n\n Застряли на сообщении с id {message_id}\n\n'
                                        f'<pre>{e}</pre>')
                            else:
                                break
                        
                        await remove_handler(callback_query.from_user.id)
                        
                        id_results = open(f"IDs {chat_id}.txt", "w+")
                        id_results.truncate()
                        for user in users:
                            id_results.write(f'{user}\n')
                        id_results.close()
                        
                        username_results = open(f"Usernames {chat_id}.txt", "w+")
                        username_results.truncate()
                        for user in usernames:
                            username_results.write(f'@{user}\n')
                        username_results.close()
                        
                        await app.send_document(callback_query.from_user.id, f'IDs {chat_id}.txt')
                        await app.send_document(callback_query.from_user.id, f'Usernames {chat_id}.txt')
                
                except Exception as e:
                    await callback_query.message.reply(f'😛 {e}')
            
            await add_handler(callback_query.from_user.id, wait)
        
        elif data == 'service channel':
            
            sent = await app.send_message(callback_query.from_user.id,
                                          "<b>🤖 Чтобы добавить канал для уведомлений:</b>\n\n"
                                          "1) Дайте боту админку в канале\n"
                                          "2) Пришлите ссылку на канал 👇",
                                          reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))
            
            async def wait(channel_message):
                
                await remove_handler(callback_query.from_user.id)
                
                if channel_message.text == 'Отмена ❌':
                    sent2 = await app.send_message(
                        callback_query.from_user.id, "❌ Отменено", reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(1.1)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    return
                
                channel_message = channel_message.text
                
                try:
                    
                    if channel_message.startswith('https://t.me/+') or channel_message.startswith('https://t.me/-'):
                        await app.send_message(callback_query.from_user.id, 'Бот не может заходить по пригласительным ссылкам')
                        return
                    elif channel_message.startswith('https://t.me/'):
                        channel_message = channel_message[13:]
                    elif channel_message.startswith('t.me/'):
                        channel_message = channel_message[5:]
                    elif channel_message.startswith('@'):
                        channel_message = channel_message[1:]
                    elif channel_message.isdigit():
                        channel_message = int(channel_message)
                        
                    service_channel = await app.get_chat(channel_message)
                    
                    sql_edit('UPDATE managers SET channel = ?', (service_channel.id,))
                    
                    sent2 = await app.send_message(
                        callback_query.from_user.id,
                        f"👌 Уведомления теперь присылаются в {service_channel.title}",
                        reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(channel_message.chat.id, channel_message.id)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                
                except Exception as e:
                    print(e)
                    await channel_message.reply(f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
            
            await add_handler(callback_query.from_user.id, wait)
        
        elif data.startswith('token'):
            
            sent = await app.send_message(callback_query.from_user.id,
                                          "🤖 Введите Bearer-токен Timeweb AI:",
                                          reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))

            async def wait(token):

                await remove_handler(callback_query.from_user.id)
                await app.delete_messages(token.chat.id, token.id)
                await app.delete_messages(sent.chat.id, sent.id)

                if token.text == 'Отмена ❌':

                    sent2 = await app.send_message(callback_query.from_user.id,
                                                   "❌ Отменено",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    return

                try:

                    F = open('tw_token.txt', 'w', encoding='utf-8')
                    F.write(token.text.strip())
                    F.close()

                    sent2 = await app.send_message(callback_query.from_user.id, "👌 Токен изменён",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)

                except Exception as e:
                    await sent.edit(f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
            
            await add_handler(callback_query.from_user.id, wait)
            
        elif data.startswith('proxy'):
            
            sent = await app.send_message(
                callback_query.from_user.id,
                "🤖 Введите Agent Access ID из кабинета Timeweb AI:",
                reply_markup=ReplyKeyboardMarkup([['Отмена ❌']], resize_keyboard=True))

            async def wait(token):

                await remove_handler(callback_query.from_user.id)
                await app.delete_messages(token.chat.id, token.id)
                await app.delete_messages(sent.chat.id, sent.id)

                if token.text == 'Отмена ❌':

                    sent2 = await app.send_message(callback_query.from_user.id,
                                                   "❌ Отменено",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    return

                try:

                    f = open('tw_agent_id.txt', 'w', encoding='utf-8')
                    f.write(token.text.strip())
                    f.close()

                    sent2 = await app.send_message(callback_query.from_user.id, "👌 Agent ID изменён",
                                                   reply_markup=ReplyKeyboardRemove())
                    await asyncio.sleep(2)
                    await app.delete_messages(sent2.chat.id, sent2.id)

                except Exception as e:
                    await sent.edit(f'😛 Произошла ошибка\n\n<pre>{e}</pre>')
            
            await add_handler(callback_query.from_user.id, wait)
            
        elif data == '+':
            sent = await callback_query.message.reply("Введите номер аккаунта:\n\n<i>/cancel для отмены</i>")
            
            async def wait(number):
                
                if number.text.startswith('8'):
                    number.text = number.text.replace('8', '7', 1)
                
                await app.delete_messages(sent.chat.id, sent.id)
                await app.delete_messages(number.chat.id, number.id)
                sent2 = await callback_query.message.reply("Введите SOCKS5 прокси в формате ниже:\n\n"
                                                  "<code>scheme:ip:port:username:password</code>\n\n"
                                                  "Пример: socks5:45.145.57.238:10253:ucXRvV:dcEscZ",
                                                  reply_markup=ReplyKeyboardMarkup([['Без прокси']],
                                                                                   resize_keyboard=True))
                
                async def wait_for(proxy):
                    
                    await app.delete_messages(sent2.chat.id, sent2.id)
                    await app.delete_messages(proxy.chat.id, proxy.id)
                    
                    try:
                        
                        phone = number.text.replace(' ', '').replace('+', '')
                        
                        if proxy.text == 'Без прокси':
                            client = Client(phone, API_ID, API_HASH)
                        
                        else:
                            
                            proxy_to_login = proxy.text.split(':')
                            proxy_to_login = format_proxy(proxy_to_login)
                            if not proxy_to_login:
                                await app.send_message(number.from_user.id,
                                                       "Неправильный формат прокси. Пример правильного формата ниже:\n\n"
                                                       "<pre>socks5:45.145.57.238:10253:ucXRvV:dcEscZ</pre>")
                                return
                            
                            client = Client(phone, API_ID, API_HASH, proxy=proxy_to_login)
                        
                        # подключаемся к серверам
                        await client.connect()
                        
                        # отправляем код для входа
                        s_code = await client.send_code(phone)
                        
                        await remove_handler(callback_query.from_user.id)
                        await app.send_message(
                            callback_query.from_user.id,
                            "👇 Введите код, который прислал Telegram",
                            reply_markup=ReplyKeyboardRemove())
                        
                        async def wait_for_the(code):
                            await remove_handler(callback_query.from_user.id)
                            await app.delete_messages(code.chat.id, code.id)
                            
                            try:
                                try:
                                    await client.sign_in(phone, s_code.phone_code_hash, code.text)
                                
                                except SessionPasswordNeeded:
                                    
                                    await callback_query.message.reply("👇 Введите код двухфакторной ауентификации "
                                                                       "(Пароль от аккаунта)")
                                    
                                    async def wait_for_pass(word):
                                        await remove_handler(callback_query.from_user.id)
                                        await app.delete_messages(code.chat.id, code.id)
                                        
                                        try:
                                            await client.check_password(word.text)
                                            await client.disconnect()
                                            await client.start()
                                            setup_worker(client)
                                            
                                            if proxy.text != 'Без прокси':
                                                sql_edit('INSERT INTO workers VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                                         (phone, proxy.text,
                                                          'Вы - двадцатилетняя девушка',
                                                          "Отвечу только когда перейдёшь по ссылке в описании)", 0, 1, 1,
                                      'Напиши интересный комментарий до 10 слов на тему этого поста:', 'text'))
                                            else:
                                                sql_edit('INSERT INTO workers VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                                         (phone, None,
                                                          'Вы - двадцатилетняя девушка',
                                                          "Отвечу только когда перейдёшь по ссылке в описании)", 0, 1, 1,
                                      'Напиши интересный комментарий до 10 слов на тему этого поста:', 'text'))
                                            workers_list[phone] = client
                                            
                                            sent3 = await callback_query.message.reply(
                                                "👌 Аккаунт подключен",
                                                reply_markup=ReplyKeyboardMarkup([['Мои аккаунты 🙂'], ['Меню 🌴']],
                                                                                 resize_keyboard=True))
                                            accounts_message = await callback_query.message.reply('...')
                                            await asyncio.sleep(1)
                                            await accounts(accounts_message)
                                        
                                        
                                        except Exception as e2:
                                            await app.send_message(number.from_user.id,
                                                                   f'😛 Произошла ошибка\n\n<pre>{e2}</pre>')
                                            await remove_handler(callback_query.from_user.id)
                                    
                                    await add_handler(number.from_user.id, wait_for_pass)
                                    return
                                
                                await client.disconnect()
                                await client.start()
                                setup_worker(client)
                                worker_apps.append(client)
                                
                                if proxy.text != 'Без прокси':
                                    sql_edit('INSERT INTO workers VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                             (phone, proxy.text,
                                              'Вы - двадцатилетняя девушка',
                                              "Отвечу только когда перейдёшь по ссылке в описании)", 0, 1, 1,
                                      'Напиши интересный комментарий до 10 слов на тему этого поста:', 'text'))
                                else:
                                    sql_edit('INSERT INTO workers VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                             (phone, None,
                                              'Вы - двадцатилетняя девушка',
                                              "Отвечу только когда перейдёшь по ссылке в описании)", 0, 1, 1,
                                      'Напиши интересный комментарий до 10 слов на тему этого поста:', 'text'))
                                workers_list[phone] = client
                                
                                sent3 = await callback_query.message.reply(
                                    "👌 Аккаунт подключен",
                                    reply_markup=ReplyKeyboardMarkup([['Мои аккаунты 🙂'], ['Меню 🌴']],
                                                                     resize_keyboard=True))
                                accounts_message = await callback_query.message.reply('...')
                                await asyncio.sleep(1)
                                await accounts(accounts_message)
                                await sent3.delete()
                            
                            
                            except Exception as e2:
                                await app.send_message(number.from_user.id, f'😛 Произошла ошибка\n\n<pre>{e2}</pre>')
                        
                        await remove_handler(callback_query.from_user.id)
                        await add_handler(callback_query.from_user.id, wait_for_the)
                    
                    except Exception as e:
                        await app.send_message(number.from_user.id, f'😛 Произошла ошибка\n\n<pre>{e}</pre>',
                                               reply_markup=ReplyKeyboardMarkup([['Мои аккаунты 🙂'], ['Меню 🌴']], resize_keyboard=True))
                    
                
                await remove_handler(callback_query.from_user.id)
                await add_handler(callback_query.from_user.id, wait_for)
            
            
            await add_handler(callback_query.from_user.id, wait)


def setup_worker(app):
        
    @app.on_message(filters.channel, group=2)
    async def comment(_, message):
        
        global SENT_TODAY
        channel_message = message
        client_data = await app.get_me()
        
        channels = sql_select(f"SELECT purpose, session FROM channels WHERE session = '{client_data.phone_number}' "
                              f'and id = {message.chat.id}')

        if channels:


            # if channels[0][0] == 'comments':
            if True:

                settings = sql_select(f"SELECT * FROM workers WHERE session = '{client_data.phone_number}'")
                
                await asyncio.sleep(settings[0][4])
                
                if random.randint(1, settings[0][5]) == 1 and SENT_TODAY < LIMIT and (message.text or message.caption):
                    

                    service_channel = sql_select('SELECT channel FROM managers')
                    
                    if message.caption:
                        post = message.caption
                    else:
                        post = message.text
                    
                    try:
                        message = await app.get_discussion_message(message.sender_chat.id, message.id)
                        # await app.get_discussion_replies()

                        if settings[0][9] == 1:

                            pretexts = sql_select(
                                f"SELECT text FROM pretexts WHERE session = '{client_data.phone_number}'")

                            sent_message = None
                            try:

                                if pretexts:
                                    sent_message = await message.reply(random.choice(pretexts)[0])
                                else:
                                    sent_message = await message.reply(random.choice(emojies))

                            except Forbidden:
                                try:
                                    await client.join_chat(message.chat.id)
                                    if pretexts:
                                        sent_message = await message.reply(random.choice(pretexts)[0])
                                    else:
                                        sent_message = await message.reply(random.choice(emojies))
                                except Exception as e:
                                    print(e)
                                    # if service_channel:
                                    #     await manager_apps[0].send_message(
                                    #         service_channel[0][0],
                                    #         f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                    #         f'{e}')
                                    #     continue

                            except Exception as e:
                                print(e)
                                # if service_channel:
                                #     await manager_apps[0].send_message(
                                #         service_channel[0][0],
                                #         f'<b>Ошибка при комментарии в {chat.title}</b>\n\n'
                                #         f'{e}')
                                #     continue

                            return

                        if settings[0][6] == 1:
                            pretexts = sql_select(
                                f"SELECT text FROM pretexts WHERE session = '{client_data.phone_number}'")

                            if pretexts:
                                sent_message = await message.reply(random.choice(pretexts)[0])
                            else:
                                sent_message = await message.reply(random.choice(emojies))
                        else:
                            sent_message = None

                    except Exception as e:
                        if service_channel:
                            await manager_apps[0].send_message(
                                service_channel[0][0],
                                f'<b>Ошибка при комментарии в {channel_message.chat.title}</b>\n\n'
                                f'{e}')
                        return
                    
                    prompt = settings[0][7] + f' "{post}"'
                    
                    output = await generate_response(prompt, settings[0][2], app)
                    
                    try:
                        if sent_message:
                            reply = await sent_message.edit(output)
                            SENT_TODAY += 1
                            # for admin in admins:
                            #     for client in worker_apps:
                            #         try:
                            #             await client.send_message(admin, reply.link)
                            #         finally:
                            #             pass
                        else:
                            reply = await message.reply(output)
                            # for admin in admins:
                            #     for client in worker_apps:
                            #         try:
                            #             await client.send_message(admin, reply.link)
                            #         finally:
                            #             pass-
                        if service_channel:
                            await manager_apps[0].send_message(
                                service_channel[0][0],
                                f'<b>Новый комментарий в {channel_message.chat.title}</b>\n\n'
                                f'{reply.link}'
                            )
                            
                    except Exception as e:
                        if service_channel:
                            await manager_apps[0].send_message(
                                service_channel[0][0],
                                f'<b>Ошибка при комментарии в {channel_message.chat.title}</b>\n\n'
                                f'{e}')
    
    @app.on_message(filters.private)
    async def comment(_, message):

        if message.from_user.id == BOT_ID:
            return
        
        text = message.text
        
        if text and (text.startswith('https://t.me/') or text.startswith('t.me/') or text.startswith('@')):
            if text.startswith('https://t.me/'):
                text = str(message.text[13:])
            elif text.startswith('t.me/'):
                text = str(message.text[5:])
            elif text.startswith('@'):
                text = str(message.text[1:])
            try:
                await app.join_chat(text)
                res = client_data = await app.get_me()
                await message.reply('Спасибо за канал 👍')
                sql_edit(f"INSERT INTO channels VALUES(?, '{client_data.phone_number}')", (res.id,))
            except Exception:
                await message.reply('Не могу подписаться(')
        else:
            await app.send_chat_action(message.chat.id, ChatAction.TYPING)
            client_data = await app.get_me()
            settings = sql_select(f"SELECT * FROM workers WHERE session = '{client_data.phone_number}' AND auto_reply != '-'")
            if settings and settings[0][3]:
                await asyncio.sleep(1)
                await message.reply(settings[0][3])
            else:
                await app.send_chat_action(message.chat.id, ChatAction.CANCEL)

startup()
compose(apps)
