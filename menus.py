from sqlite_functions import sql_select
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


async def pretexts_menu(callback_query):

    data = callback_query.data
    pretexts = sql_select(f'SELECT text, id FROM pretexts WHERE session = {data.split()[1]}')

    if pretexts:

        kb = []

        for pretext in pretexts:
            kb.append([InlineKeyboardButton(pretext[0], callback_data=f'delpretext {pretext[1]}')])

        kb.append([InlineKeyboardButton('Добавить тексты', callback_data=f'addpretexts {data.split()[1]}')])

        await callback_query.message.edit(
            'Тексты первичного комментария',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    else:
        await callback_query.message.edit(
            'Вы ещё не добавляли тексты первичного комментария',
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('Добавить тексты', callback_data=f'addpretexts {data.split()[1]}')]])
        )