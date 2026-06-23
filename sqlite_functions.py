import sqlite3


with sqlite3.connect("database.db") as connection:
    cursor = connection.cursor()

    core_commands = [
        "PRAGMA encoding='UTF-8'",
        'ALTER TABLE channels ADD COLUMN purpose TEXT DEFAULT "comments"',
        'CREATE TABLE IF NOT EXISTS managers(token TEXT)',
        'CREATE TABLE IF NOT EXISTS stickers(pack_id TEXT NOT NULL, sticker TEXT NOT NULL, emoji TEXT NOT NULL, session TEXT)',
        'CREATE TABLE IF NOT EXISTS channels(id INT, session TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS workers'
        '(session TEXT NOT NULL, proxy TEXT, prompt TEXT, auto_reply TEXT, '
        'delay FLOAT DEFAULT 0, chance INT DEFAULT 1, be_first INT DEFAULT 1, what_to_write TEXT, mode TEXT DEFAULT "text")',
        'ALTER TABLE stickers ADD session TEXT DEFAULT 79858490415',
        'ALTER TABLE managers ADD COLUMN channel text',
        'ALTER TABLE workers ADD COLUMN dont_use_gpt INT DEFAULT 0',
        
        'CREATE TABLE IF NOT EXISTS pretexts'
        '(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, session TEXT NOT NULL)',

        'UPDATE channels SET purpose = "comments"'
    ]

    def sql_edit(command, args):
        try:
            s_c = connection.cursor()
            s_c.execute(command, args)
            connection.commit()
        except Exception as exc:
            connection.rollback()
            print(f"{command}\nrollback: {exc}")


    def sql_select(command):
        try:
            s_c = connection.cursor()
            s_c.execute(command)
            return s_c.fetchall()
        except Exception as exc:
            print(f"{command}\nsql_select() error: {exc}")
