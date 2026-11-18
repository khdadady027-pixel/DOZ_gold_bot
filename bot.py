import os, time, random, logging, requests, json

TOKEN = os.getenv('BALE_TOKEN', '').strip()
OWNER_ID = str(os.getenv('OWNER_ID', '')).strip()
BASE = f'https://tapi.bale.ai/bot{TOKEN}/'
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

if not TOKEN:
    raise SystemExit('Set BALE_TOKEN in your hosting service environment variables.')

http = requests.Session()
offset = 0
users = set()
banned = set()
games_finished = 0
waiting = None
ADMINS_FILE = os.getenv('ADMINS_FILE', 'admins.json')

def load_admins():
    try:
        with open(ADMINS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {str(x) for x in data if str(x) != OWNER_ID}
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return set()

def save_admins():
    with open(ADMINS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(admins), f, ensure_ascii=False, indent=2)

admins = load_admins()

def is_owner(user_id):
    return str(user_id) == OWNER_ID

def is_admin(user_id):
    return is_owner(user_id) or str(user_id) in admins
active = {}  # chat_id -> game


def api(method, payload=None, params=None):
    r = http.post(BASE + method, json=payload, params=params, timeout=45) if payload is not None else http.get(BASE + method, params=params, timeout=45)
    r.raise_for_status()
    data = r.json()
    if not data.get('ok', False):
        logging.warning('API %s returned: %s', method, data)
    return data


def send(chat, text, keyboard=None):
    body = {'chat_id': chat, 'text': text}
    if keyboard is not None:
        body['reply_markup'] = keyboard
    return api('sendMessage', body)


def answer_callback(callback_id, text=''):
    api('answerCallbackQuery', {'callback_query_id': callback_id, 'text': text})


def main_menu(admin=False):
    rows = [
        [{'text': '🤖 بازی با ربات', 'callback_data': 'ai'}],
        [{'text': '👥 بازی دونفره', 'callback_data': 'duel'}, {'text': '📊 آمار من', 'callback_data': 'mystats'}],
    ]
    if admin:
        rows.append([{'text': '👑 پنل مدیریت', 'callback_data': 'admin'}])
    return {'inline_keyboard': rows}


def board_keyboard(board, game_id, locked=False):
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            mark = board[i] or '⬜'
            row.append({'text': mark, 'callback_data': f'move:{game_id}:{i}' if not locked and not board[i] else 'noop'})
        rows.append(row)
    rows.append([{'text': '🏠 منوی اصلی', 'callback_data': 'home'}])
    return {'inline_keyboard': rows}


def outcome(board):
    lines = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in lines:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return 'draw' if all(board) else None


def render_game(chat, game, note=''):
    turn = 'نوبت توست (❌)' if game['turn'] == 'X' else 'نوبت حریف (⭕)'
    send(chat, (note + '\n' if note else '') + turn, board_keyboard(game['board'], game['id']))


def start_ai(chat):
    game = {'id': str(random.randrange(100000, 999999)), 'mode': 'ai', 'board': ['']*9, 'turn': 'X', 'wins': 0}
    active[str(chat)] = game
    render_game(chat, game, 'بازی با ربات شروع شد! تو ❌ هستی.')


def finish(chat, game, result):
    global games_finished
    games_finished += 1
    if result == 'draw': msg = '🤝 بازی مساوی شد!'
    elif game['mode'] == 'ai': msg = '🎉 تو بردی!' if result == 'X' else '🤖 ربات برنده شد!'
    else: msg = f'🏆 بازیکن {game["players"][result]} برنده شد!'
    send(chat, msg + '\nبرای بازی دوباره از منوی اصلی استفاده کن.', main_menu(is_admin(chat)))
    active.pop(str(chat), None)


def ai_move(board):
    # Take a winning move, otherwise block, otherwise choose a free square.
    for mark in ('O', 'X'):
        for i in range(9):
            if not board[i]:
                board[i] = mark
                won = outcome(board) == mark
                board[i] = ''
                if won:
                    return i
    free = [i for i, v in enumerate(board) if not v]
    return random.choice(free) if free else None


def admin_panel(chat):
    if not is_admin(chat):
        send(chat, '⛔ این بخش فقط برای مدیران بات است.')
        return
    role = '👑 مالک اصلی' if is_owner(chat) else '🛡️ مدیر'
    commands = '/ban شناسه_کاربر\n/unban شناسه_کاربر'
    if is_owner(chat):
        commands += '\n/addadmin شناسه_کاربر\n/deladmin شناسه_کاربر\n/admins\n/broadcast متن پیام'
    send(chat, f'👑 پنل مدیریت دوز طلایی\n{role}\n\n👤 کاربران شناخته‌شده: {len(users)}\n🎮 بازی‌های پایان‌یافته از آخرین اجرا: {games_finished}\n🚫 کاربران مسدود: {len(banned)}\n🛡️ مدیران: {len(admins)}\n\nدستورهای مدیریتی:\n{commands}')


def handle_message(msg):
    chat = str(msg.get('chat', {}).get('id', ''))
    sender = str(msg.get('from', {}).get('id', chat))
    text = (msg.get('text') or '').strip()
    if not chat:
        return
    users.add(chat)
    if sender in banned or chat in banned:
        return
    if text in ('/myid', '/id'):
        send(chat, f'شناسه کاربری بله: {sender}')
    elif text.startswith('/start'):
        send(chat, '🎮 به دوز طلایی خوش آمدی!\nیک حالت بازی انتخاب کن:', main_menu(is_admin(sender)))
    elif text.startswith('/panel'):
        admin_panel(sender)
    elif text.startswith('/addadmin'):
        if not is_owner(sender):
            send(chat, '⛔ فقط مالک اصلی می‌تواند مدیر اضافه کند.')
            return
        parts = text.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip().isdigit():
            send(chat, 'روش استفاده: /addadmin شناسه_عددی')
            return
        new_admin = parts[1].strip()
        if is_owner(new_admin):
            send(chat, 'مالک اصلی از قبل بالاترین دسترسی را دارد.')
        else:
            admins.add(new_admin)
            save_admins()
            send(chat, f'🛡️ کاربر {new_admin} به مدیران اضافه شد.')
    elif text.startswith('/deladmin'):
        if not is_owner(sender):
            send(chat, '⛔ فقط مالک اصلی می‌تواند مدیر حذف کند.')
            return
        parts = text.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip().isdigit():
            send(chat, 'روش استفاده: /deladmin شناسه_عددی')
            return
        target_admin = parts[1].strip()
        if target_admin in admins:
            admins.remove(target_admin)
            save_admins()
            send(chat, f'مدیریت کاربر {target_admin} لغو شد.')
        else:
            send(chat, 'این شناسه در فهرست مدیران نیست.')
    elif text == '/admins':
        if not is_owner(sender):
            send(chat, '⛔ فقط مالک اصلی می‌تواند فهرست مدیران را ببیند.')
            return
        listing = '\n'.join(sorted(admins)) if admins else 'هنوز مدیری اضافه نشده است.'
        send(chat, '🛡️ فهرست مدیران:\n' + listing)
    elif text.startswith('/broadcast '):
        if sender != OWNER_ID:
            send(chat, '⛔ فقط مالک اجازه دارد.')
            return
        announcement = text[len('/broadcast '):].strip()
        ok = 0
        for target in list(users):
            if target not in banned:
                try:
                    send(target, '📢 پیام مدیریت:\n' + announcement)
                    ok += 1
                    time.sleep(0.05)
                except Exception:
                    pass
        send(chat, f'پیام برای {ok} گفتگو ارسال شد.')
    elif text.startswith('/ban '):
        if not is_admin(sender):
            send(chat, '⛔ فقط مدیران اجازه دارند.')
            return
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            send(chat, 'روش استفاده: /ban شناسه_کاربر')
            return
        target = parts[1].strip()
        if is_owner(target) or (target in admins and not is_owner(sender)):
            send(chat, '⛔ اجازه مسدودکردن مالک یا مدیر دیگر را نداری.')
        else:
            banned.add(target)
            send(chat, 'کاربر مسدود شد.')
    elif text.startswith('/unban '):
        if not is_admin(sender):
            send(chat, '⛔ فقط مدیران اجازه دارند.')
            return
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            send(chat, 'روش استفاده: /unban شناسه_کاربر')
            return
        banned.discard(parts[1].strip())
        send(chat, 'مسدودیت برداشته شد.')
    else:
        send(chat, 'برای شروع بازی /start را بفرست.')


def handle_callback(q):
    global waiting
    data = q.get('data', '')
    chat = str(q.get('message', {}).get('chat', {}).get('id', ''))
    sender = str(q.get('from', {}).get('id', ''))
    cbid = q.get('id')
    if not chat:
        answer_callback(cbid)
        return
    users.add(chat)
    if sender in banned or chat in banned:
        answer_callback(cbid, 'دسترسی شما محدود شده است.')
        return
    answer_callback(cbid)
    if data == 'noop': return
    if data == 'home':
        active.pop(chat, None)
        send(chat, 'منوی اصلی:', main_menu(is_admin(sender))); return
    if data == 'ai': start_ai(chat); return
    if data == 'mystats':
        send(chat, '📊 آمار شخصی در نسخه بعدی با ذخیره‌سازی دائمی اضافه می‌شود.', main_menu(is_admin(sender))); return
    if data == 'admin': admin_panel(sender); return
    if data == 'duel':
        if waiting is None:
            waiting = {'chat': chat, 'user': sender}
            send(chat, '⏳ منتظر بازیکن دوم هستیم. وقتی دوستت هم «بازی دونفره» را بزند، بازی شروع می‌شود.', main_menu(is_admin(sender)))
        elif waiting['chat'] == chat:
            send(chat, 'هنوز منتظر بازیکن دیگری هستیم.')
        else:
            first = waiting
            waiting = None
            gid = str(random.randrange(100000, 999999))
            game = {'id': gid, 'mode': 'duel', 'board': ['']*9, 'turn': 'X', 'players': {'X': first['user'], 'O': sender}, 'chats': [first['chat'], chat]}
            for target in game['chats']:
                active[target] = game
                render_game(target, game, '🎮 حریف پیدا شد! توکن بازیکن: ' + ('❌' if target == first['chat'] else '⭕'))
        return
    if data.startswith('move:'):
        parts = data.split(':')
        if len(parts) != 3: return
        _, gid, pos_s = parts
        try: pos = int(pos_s)
        except ValueError: return
        game = active.get(chat)
        if not game or game['id'] != gid or not 0 <= pos < 9: return
        if game['board'][pos]: return
        if game['mode'] == 'duel':
            mark = 'X' if game['players']['X'] == sender else 'O' if game['players']['O'] == sender else None
            if not mark or mark != game['turn']:
                send(chat, 'الان نوبت شما نیست یا این بازی متعلق به شما نیست.'); return
        else:
            mark = 'X'
            if game['turn'] != 'X': return
        game['board'][pos] = mark
        result = outcome(game['board'])
        if result:
            targets = game.get('chats', [chat])
            board_text = 'نتیجه بازی:\n' + '\n'.join(' | '.join(game['board'][r*3:r*3+3]) for r in range(3))
            if game['mode'] == 'duel':
                global games_finished
                games_finished += 1
                if result == 'draw': outcome_text = '🤝 بازی مساوی شد!'
                else: outcome_text = f'🏆 بازیکن {game["players"][result]} برنده شد!'
                for target in targets:
                    send(target, board_text + '\n' + outcome_text, main_menu(is_admin(target)))
                    active.pop(target, None)
            else:
                send(chat, board_text)
                finish(chat, game, result)
            return
        if game['mode'] == 'ai':
            game['turn'] = 'O'
            ai = ai_move(game['board'])
            if ai is not None: game['board'][ai] = 'O'
            result = outcome(game['board'])
            if result:
                send(chat, 'نتیجه بازی:\n' + '\n'.join(' | '.join(game['board'][r*3:r*3+3]) for r in range(3)))
                finish(chat, game, result); return
            game['turn'] = 'X'
            render_game(chat, game)
        else:
            game['turn'] = 'O' if mark == 'X' else 'X'
            for target in game['chats']:
                render_game(target, game, 'حرکت ثبت شد.')


def main():
    global offset
    logging.info('DOZ Gold bot starting')
    while True:
        try:
            data = api('getUpdates', params={'offset': offset, 'timeout': 25})
            for update in data.get('result', []):
                offset = update.get('update_id', offset) + 1
                if update.get('message'):
                    handle_message(update['message'])
                if update.get('callback_query'):
                    handle_callback(update['callback_query'])
        except Exception as exc:
            logging.exception('Polling error: %s', exc)
            time.sleep(4)

if __name__ == '__main__':
    main()
