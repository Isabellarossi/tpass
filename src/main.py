#!/usr/bin/env python3
import click
import csv
import logging
import os
import pyperclip
import re
import subprocess
import sys
import tempfile
import time
import uuid
try:
    import simplejson as json
except:
    import json
from src import trezor
from src import crypto
from src import password

ICONS = {'home':u'\U0001f3e0', 'person-stalker':u'\U0001F469\u200D\U0001F467', 'social-bitcoin':'₿', 'person':u'\U0001F642', 'star':u'\u2B50', 'flag':u'\U0001F3F3', 'heart':u'\u2764', 'settings':u'\u2699', 'email':u'\u2709', 'cloud':u'\u2601', 'alert-circled':u'\u26a0', 'android-cart':u'\U0001f6d2', 'image':u'\U0001F5BC', 'card':u'\U0001f4b3', 'earth':u'\U0001F310', 'wifi':u'\U0001f4f6'}
DROPBOX_PATH = os.path.join(os.path.expanduser('~'), 'Dropbox', 'Apps', 'TREZOR Password Manager')
GOOGLE_DRIVE_PATH = os.path.join(os.path.expanduser('~'), 'Google Drive', 'Apps', 'TREZOR Password Manager')
DEFAULT_PATH = os.path.join(os.path.expanduser('~'), '.tpassword-store')
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.tpass')
CONFIG_FILE = os.path.join(CONFIG_PATH, 'config.json')
LOG_FILE = os.path.join(CONFIG_PATH, 'tpass.log')
LOCK_FILE = os.path.join(CONFIG_PATH, 'tpass.lock')
UUID = uuid.uuid4().int
LOCK = {'uuid':UUID, 'pwd_last_change_time':''} # TODO make empty file:: get timestamp of lockfile instead of uuid; write pwd_last_change_time in var instead LOCK --> spead up start
DICEWARE_FILE = os.path.join(CONFIG_PATH, 'wordlist.txt')
DEV_SHM = os.path.join('/', 'dev', 'shm')
CLIPBOARD_CLEAR_TIME = 15
CONFIG = {'fileName': '', 'path': DEFAULT_PATH, 'useGit': False, 'pinentry': False, 'clipboardClearTimeSec': CLIPBOARD_CLEAR_TIME, 'storeMetaDataOnDisk': True, 'showIcons': False}
PWD_FILE = os.path.join(CONFIG['path'], CONFIG['fileName'])
TMP_FILE = os.path.join(DEV_SHM, CONFIG['fileName'] + '.json')
TAG_NEW = ('',{'title': '', 'icon': 'home'})
ENTRY_NEW = ('',{'title': '', 'username': '', 'password': {'type': 'String', 'data': ''}, 'nonce': '', 'tags': [], 'safe_note': {'type': 'String', 'data': ''}, 'note': '', 'success': True, 'export': True})
client = None
pwd = None

'''
Core Methods
'''

def load_config():
    global CONFIG; global TMP_FILE; global PWD_FILE
    if not os.path.isfile(CONFIG_FILE):
        write_config()
    with open(CONFIG_FILE) as f:
        CONFIG = json.load(f)
    if 'fileName' not in CONFIG or 'path' not in CONFIG or 'storeMetaDataOnDisk' not in CONFIG:
        handle_exception('Config parse error: ' + CONFIG_PATH, 6)
    PWD_FILE = os.path.join(CONFIG['path'], CONFIG['fileName'])
    if CONFIG['storeMetaDataOnDisk'] is True:
        TMP_FILE = os.path.join(DEV_SHM, CONFIG['fileName'] + '.json')
        if not os.path.exists(DEV_SHM):
            TMP_FILE = os.path.join(tempfile.gettempdir(), CONFIG['fileName'] + '.json')
            logging.warning('/dev/shm not found on host, using not as secure /tmp for metadata')

def write_config():
    if not os.path.exists(CONFIG_PATH):    
        os.mkdir(CONFIG_PATH)
    with open(CONFIG_FILE, 'w', encoding='utf8') as f:
        json.dump(CONFIG, f, indent=4)
 
def unlock_storage():
    global LOCK; global pwd
    if os.path.isfile(LOCK_FILE):
        sys.exit('Error: password store is locked by another instance, remove lockfile to proceed: ' + LOCK_FILE)
    if CONFIG['fileName'] == '' or not os.path.isfile(PWD_FILE):
        handle_exception('Password store is not initialized', 7)

    tmp_need_update = False
    if CONFIG['storeMetaDataOnDisk'] is True:
        tmp_need_update = not os.path.isfile(TMP_FILE) or (os.path.isfile(TMP_FILE) and (os.path.getmtime(TMP_FILE) < os.path.getmtime(PWD_FILE)))
    if CONFIG['storeMetaDataOnDisk'] is False or tmp_need_update:
        pwd = password.PasswordStore.fromFile(PWD_FILE)
        if CONFIG['storeMetaDataOnDisk'] is True:
            with open(TMP_FILE, 'w') as f:
                json.dump(pwd.db_json, f)

    if CONFIG['storeMetaDataOnDisk'] is True and not tmp_need_update:
        with open(TMP_FILE) as f:
            db_json = json.load(f)
        pwd = password.PasswordStore(db_json['entries'], db_json['tags'])

    LOCK['pwd_last_change_time'] = os.path.getmtime(PWD_FILE)
    with open(LOCK_FILE, 'w', encoding='utf8') as f:
        json.dump(LOCK, f, indent=4)

def save_storage():
    global CONFIG
    if not os.path.isfile(LOCK_FILE):
        handle_exception('Lockfile deleted, aborting', 9)
    with open(LOCK_FILE) as f:
        LOCK = json.load(f)
    if LOCK['uuid'] != UUID:
        handle_exception('Lockfile changed, aborting', 10)
    if not os.path.isfile(PWD_FILE) or os.path.getmtime(PWD_FILE) != LOCK['pwd_last_change_time']:
        handle_exception('Password file changed, aborting', 11)
    get_client()
    try:
        keys = trezor.getTrezorKeys(client)
        encKey = keys[2]
        iv = trezor.getEntropy(client, 12)
    except Exception as ex:
        handle_exception('Error while accessing trezor device', 2, ex)
    try:
        crypto.encryptStorage(pwd.db_json, PWD_FILE, encKey, iv)
    except Exception as ex:
        handle_exception('Error while encrypting storage', 12, ex)
    if CONFIG['storeMetaDataOnDisk'] is True:
        with open(TMP_FILE, 'w') as f:
            json.dump(pwd.db_json, f) 
    if CONFIG['useGit'] is True:
        subprocess.call('git commit -m "update db"', cwd=CONFIG['path'], shell=True)

def load_wordlist():
    wordlist = DICEWARE_FILE
    if not os.path.isfile(DICEWARE_FILE):
        wordlist = os.path.join('wordlist.txt')
    words = {}
    try:
        with open(wordlist) as f:
            for line in f.readlines():
                if re.compile('^([1-6]){5}\t(.)+$').match(line):
                    key, value = line.rstrip('\n').split('\t')
                    if(not key in words):
                        words[key] = value
    except Exception as ex:
        handle_exception('Error while processing wordlist.txt file', 14, ex)
    return words

def clear_clipboard():
    with click.progressbar(length=CONFIG['clipboardClearTimeSec'], label='Clipboard will clear', show_percent=False, fill_char='#', empty_char='-') as bar:
        for i in bar:
            time.sleep(1)
    pyperclip.copy('')

def get_client():
    global client
    if client is None:
        try:
            client = trezor.getTrezorClient()
        except Exception as ex:
            handle_exception('Error while accessing trezor device', 2, ex)
    return client

def edit_entry(e):#TODO parse tags as string, not number; don't show <All>
    entry = e[1]
    if entry['export'] is False:
        e = unlock_entry(e, get_client())
    if entry['success'] is False:
        handle_exception('Error while editing entry', 20)
    entry['success'] = False
    edit_json = {'item/url*':entry['note'], 'title':entry['title'], 'username':entry['username'], 'password':entry['password']['data'], 'secret':entry['safe_note']['data'], 'tags': {"inUse":entry['tags'], "chooseFrom": tags_to_string(tags, True, False)}}
    edit_json = click.edit(json.dumps(edit_json, indent=4), require_save=True, extension='.json')
    if edit_json:
        try:
            edit_json = json.loads(edit_json)
        except Exception as ex:
            handle_exception('Edit gone wrong', 21, ex)
        if 'title' not in edit_json or 'item/url*' not in edit_json or 'username' not in edit_json or 'password' not in edit_json or 'secret' not in edit_json or 'tags' not in edit_json or 'inUse' not in edit_json['tags']:
            handle_exception('Edit gone wrong', 22)
        if not isinstance(edit_json['item/url*'],str) or not isinstance(edit_json['title'],str) or not isinstance(edit_json['username'],str) or not isinstance(edit_json['password'],str) or not isinstance(edit_json['secret'],str):
            handle_exception('Edit gone wrong', 23)
        if edit_json['item/url*'] == '':
            handle_exception('item/url* field is mandatory', 24)
        entry['note'] = edit_json['item/url*']; entry['title'] = edit_json['title']; entry['username'] = edit_json['username']; entry['password']['data'] = edit_json['password']; entry['safe_note']['data'] = edit_json['secret']
        for i in edit_json['tags']['inUse']:
            if str(i) not in tags:
                handle_exception('Tag not exist: ' + str(i), 25)
        if 0 in edit_json['tags']['inUse']:
            edit_json['tags']['inUse'].remove(0)
        entry['tags'] = edit_json['tags']['inUse']
        entry['success'] = True
        return lock_entry(e, get_client())
    handle_exception('Aborted!', 0)

def edit_tag(t):
    tag_id = t[0]; tag = t[1]
    edit_json = {'title': tag['title'], 'icon': {"inUse":tag['icon'], 'chooseFrom:':', '.join(ICONS)}}
    edit_json = click.edit(json.dumps(edit_json, indent=4), require_save=True, extension='.json')
    if edit_json:
        try:
            edit_json = json.loads(edit_json)
        except Exception as ex:
            handle_exception('Edit gone wrong', 26, ex)
        if 'title' not in edit_json or edit_json['title'] == '' or not isinstance(edit_json['title'],str):
            handle_exception('Title field is mandatory', 27)
        if 'icon' not in edit_json or 'inUse' not in edit_json['icon'] or edit_json['icon']['inUse'] not in ICONS or not isinstance(edit_json['icon']['inUse'],str):
            handle_exception('Icon not exists: ' + edit_json['icon']['inUse'], 28)
        tag['title'] = edit_json['title']; tag['icon'] = edit_json['icon']['inUse'] 
        return t
    handle_exception('Aborted!', 0)

def handle_exception(message, code=None, ex=None):
    logging.error(message)
    if ex is not None:
        logging.debug(ex)
    clean_exit(1)

def clean_exit(exit_code=0):
    if os.path.isfile(LOCK_FILE):#TODO only delete own lockfile
        os.remove(LOCK_FILE)
    sys.exit(exit_code)

'''
CLI Methods
'''

def tab_completion_entries(ctx, args, incomplete):
    load_config()
    unlock_storage()
    if os.path.isfile(LOCK_FILE):
        os.remove(LOCK_FILE)
    tabs = []
    for k,v in pwd.tags.items():
        es = pwd.get_entries_by_tag(k)
        for kk,vv in es.items():
            tabs.append(v['title'] + '/' + vv['note'] + ':' + vv['username'] + '#' + kk)
    return [k for k in tabs if incomplete.lower() in k.lower()]

def tab_completion_tags(ctx, args, incomplete):
    load_config()
    unlock_storage()
    if os.path.isfile(LOCK_FILE):
        os.remove(LOCK_FILE)
    tabs = []
    for t in pwd.tags:
        tabs.append(pwd.tags[t]['title'] + '/')
    return [k for k in tabs if incomplete.lower() in k.lower()]

def tab_completion_config(ctx, args, incomplete):
    load_config()
    return [k for k in CONFIG if incomplete.lower() in k]

class EntryName(click.ParamType):
    def convert(self, value, param, ctx):
        tag = ''; note = ''; username = ''; entry_id = ''
        if value.startswith('#') or '#' in value:
            entry_id = value.split('#')[1]
        elif not '/' in value:
            tag = note = value
        else:
            if not ':' in value:
                tag = value.split('/')[0]
                note = value.split('/')[1]
            else:
                tag = value.split('/')[0]
                username = value.split(':')[1]
                note = value.split('/')[1].split(':')[0]
        return (tag, note, username, entry_id)

class TagName(click.ParamType): # TODO check for String
    def convert(self, value, param, ctx):
        tag = value.split('/')[0]
        return tag

class SettingValue(click.ParamType): # TODO check for String
    def convert(self, value, param, ctx):
        return value

class AliasedGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        try:
            cmd_name = ALIASES[cmd_name].name
        except KeyError:
            pass
        return super().get_command(ctx, cmd_name)

@click.group(cls=AliasedGroup, invoke_without_command=True)
@click.option('--debug', is_flag=True, help='Show debug info')
@click.version_option()
@click.pass_context
def cli(ctx, debug):
    '''
    ~+~#~+~~+~#~+~~+~#~+~~+~#~+~~+~#~+~\n
            tpass\n
    +~#~+~~+~#~+~~+~#~+~~+~#~+~~+~#~+~~\n

    CLI for Trezor Password Manager inspired by pass\n
    Untested Beta Software! - Do not use it\n
        
    @author: makk4 <manuel.kl900@gmail.com>\n

    https://github.com/makk4/tpass
    '''
    
    logging.basicConfig(level=logging.DEBUG, filename=LOG_FILE, filemode='w', format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s', datefmt='%m-%d %H:%M')
    console = logging.StreamHandler()
    if debug:
        console.setLevel(logging.DEBUG)
    else:
        console.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    logging.info('tpass started')

    load_config()
    if ctx.invoked_subcommand is None:
        ctx = list_command()

@cli.command()
@click.option('-p', '--path', default=DEFAULT_PATH, type=click.Path(), help='path to database')
@click.option('-c', '--cloud', default='offline', type=click.Choice(['dropbox', 'googledrive', 'git', 'offline']), help='cloud provider: <dropbox> <googledrive> <git>')
@click.option('-a', '--pinentry', is_flag=True, help='ask for password on device')
@click.option('-d', '--no-disk', is_flag=True, help='do not store metadata on disk')
def init(path, cloud, pinentry, no_disk):
    '''Initialize new password store'''
    global CONFIG; global PWD_FILE; global TMP_FILE
    CONFIG['path'] = path; CONFIG['storeMetaDataOnDisk'] = not no_disk; CONFIG['pinentry'] = pinentry
    if cloud == 'googledrive':
        CONFIG['path'] = GOOGLE_DRIVE_PATH
    elif cloud == 'dropbox':
        CONFIG['path'] = DROPBOX_PATH
    if not os.path.exists(CONFIG['path']):
        os.makedirs(CONFIG['path'])
    if len(os.listdir(CONFIG['path'])) != 0:
        handle_exception(CONFIG['path'] + ' is not empty, not initialized', 1)
    if cloud == 'git':
        CONFIG['useGit'] = True
        subprocess.call('git init', cwd=CONFIG['path'], shell=True)
    get_client()
    try:
        keys = trezor.getTrezorKeys(client)
        CONFIG['fileName'] = keys[0]
    except Exception as ex:
        handle_exception('Error while getting keys from device', 2, ex)
    PWD_FILE = os.path.join(CONFIG['path'], CONFIG['fileName'])
    write_config()
    load_config()
    save_storage()
    if cloud == 'git':
        subprocess.call('git add *.pswd', cwd=CONFIG['path'], shell=True)
    click.echo('password store initialized in ' + CONFIG['path'])
    clean_exit()

@cli.command()
@click.argument('name', type=click.STRING, nargs=1)
def find(name):
    '''List entries and tags that match names'''
    unlock_storage()
    es = {}; ts = {}
    for k,v in pwd.entries.items():
        if name.lower() in v['note'].lower() or name.lower() in v['title'].lower() or name.lower() in v['username'].lower():
            es.update({k : v})
    for k,v in pwd.tags.items():
        if name.lower() in v['title'].lower():
            ts.update({k : v}) 
    pwd.print_entries(es)
    pwd.print_tags(ts)
    clean_exit()

@cli.command()
@click.argument('name', type=click.STRING, nargs=1)
@click.option('-i', '--case-insensitive', is_flag=True, help='not case sensitive search')
def grep(name, case_insensitive):
    '''Search for names in decrypted entries'''
    unlock_storage()
    for k, v in pwd.entries.items():
        v = pwd.unlock_entry((k,v), get_client())[1]
        for kk, vv in v.items():
            if kk in ['note', 'title', 'username']:
                if name.lower() in vv.lower():
                    click.echo(click.style(v['note'] + ':', bold=True) + click.style(v['username'], bold=True, fg='green') + click.style('#' + k, bold=True, fg='magenta') + click.style('//<' + kk + '>//: ', fg='blue') + vv)
        if name.lower() in v['password']['data'].lower():    
            click.echo(click.style(v['note'] + ':', bold=True) + click.style(v['username'], bold=True, fg='green') + click.style('#' + k, bold=True, fg='magenta') + click.style('//<password>//: ', fg='blue') + v['password']['data'])
        if name.lower() in v['safe_note']['data'].lower():  
            click.echo(click.style(v['note'] + ':', bold=True) + click.style(v['username'], bold=True, fg='green') + click.style('#' + k, bold=True, fg='magenta') + click.style('//<secret>//: ', fg='blue') + v['safe_note']['data'])
    clean_exit()

@cli.command(name='list')
@click.argument('tag-name', default='', type=TagName(), nargs=1, autocompletion=tab_completion_tags)
def list_command(tag_name):
    '''List entries by tag'''
    unlock_storage()
    if tag_name == '':
        pwd.print_tags(pwd.tags, True)
    else:
        t = pwd.get_tag(tag_name)
        pwd.print_tags({t[0] : t[1]}, True)
    clean_exit()
    
@cli.command()
@click.argument('entry-names', type=EntryName(), nargs=-1, autocompletion=tab_completion_entries)
@click.option('-s', '--secrets', is_flag=True, help='show password and secret notes')
@click.option('-j', '--json', is_flag=True, help='json format')
def show(entry_names, secrets, json):
    '''Show entries'''
    unlock_storage()
    for name in entry_names:
        e = pwd.get_entry(name)
        entry = e[1]; entry_id = e[0]

        if not secrets:
            password = '********'
            safeNote = '********'
        else:
            e = pwd.unlock_entry(e, get_client())
            password = entry['password']['data']
            safeNote = entry['safe_note']['data']
        if json:
            click.echo(e)
        else:
            ts = {}
            for i in entry['tags']:
                ts[i] = pwd.tags.get(str(i))

            click.echo(click.style('#' + entry_id, bold=True, fg='magenta') + '\n' +
                click.style('item/url*: ', bold=True) + entry['note'] + '\n' +
                click.style('title:     ', bold=True) + entry['title'] + '\n' +
                click.style('username:  ', bold=True) + entry['username'] + '\n' +
                click.style('password:  ', bold=True) + password + '\n' +
                click.style('secret:    ', bold=True) + safeNote  + '\n' +
                click.style('tags:      ', bold=True) + pwd.tags_to_string(ts))
    clean_exit()

@cli.command()
@click.option('-u', '--user', is_flag=True, help='copy user')
@click.option('-i', '--url', is_flag=True, help='copy item/url*')
@click.option('-s', '--secret', is_flag=True, help='copy secret')
@click.argument('entry-name', type=EntryName(), nargs=1, autocompletion=tab_completion_entries)
def clip(user, url, secret, entry_name):
    '''Decrypt and copy line of entry to clipboard'''
    unlock_storage()
    e = pwd.get_entry(entry_name)
    entry = e[1]; entry_id = e[0]
    if user:
        pyperclip.copy(entry['username'])
    elif url:
        pyperclip.copy(entry['title'])
    else:
        e = pwd.unlock_entry(e, get_client())
        if secret:
            pyperclip.copy(entry['safe_note']['data'])
        else:
            pyperclip.copy(entry['password']['data'])
        clear_clipboard()
    clean_exit()     
    
@cli.command()# TODO callback eager options
@click.argument('length', default=15, type=int)
@click.option('-i', '--insert', default=None, type=EntryName(), nargs=1, autocompletion=tab_completion_entries)
@click.option('-c', '--clip', is_flag=True, help='copy to clipboard')
@click.option('-t', '--type','type_', default='password', type=click.Choice(['password', 'wordlist', 'pin']), help='type of password')
@click.option('-s', '--seperator', default=' ', type=click.STRING, help='seperator for passphrase')
@click.option('-f', '--force', is_flag=True, help='force without confirmation')
@click.option('-d', '--entropy', is_flag=True, help='entropy from trezor device and host mixed')
def generate(length, insert, type_, clip, seperator, force, entropy):
    '''Generate new password'''
    global db_json
    if (length < 6 and type_ is 'password') or (length < 3 and type_ is 'wordlist') or (length < 4 and type_ is 'pin'):
        if not click.confirm('Warning: ' + length + ' is too short for password with type ' + type_ + '. Continue?'):
            handle_exception('Aborted', 0)
    if entropy:
        get_client()
        entropy = trezor.getEntropy(client, length)
    else:
        entropy = None
    if type_ == 'wordlist':
        words = load_wordlist()
        password = crypto.generatePassphrase(length, words, seperator, entropy)
    elif type_ == 'pin':
        password = crypto.generatePin(length, entropy)
    elif type_ == 'password':
        password = crypto.generatePassword(length, entropy)
    if insert:
        unlock_storage()
        e = pwd.get_entry(insert)
        e = pwd.unlock_entry(e, get_client())
        e[1]['password']['data'] = password
        e = edit_entry(e)
        pwd.insert_entry(e)
        if force or click.confirm('Insert password in entry ' + click.style(e[1]['title'], bold=True)):
            save_storage()
    if clip:
        pyperclip.copy(password)
        clear_clipboard()
    else:
        click.echo(password)
    clean_exit()

@cli.command()
@click.option('--tag', '-t', type=TagName(), help='remove tag', nargs=1, autocompletion=tab_completion_tags)
@click.option('--recursive', '-r', is_flag=True, help='recursive remove entries in tag')
@click.option('--force', '-f', is_flag=True, help='force without confirmation')
@click.argument('entry-names', type=EntryName(), nargs=-1, autocompletion=tab_completion_entries)
def remove(entry_names, tag, recursive, force):# TODO make options TRU/FALSE tag and -1 all args
    '''Remove entry or tag'''
    unlock_storage()
    global db_json
    if tag:
        t = pwd.get_tag(tag)
        pwd.remove_tag(t, recursive)
        if force or click.confirm('Delete tag: ' + click.style(t[1]['title'], bold=True)):
            save_storage()
    else:
        names = []
        for name in entry_names:
            entry_id = pwd.get_entry(name)[0]
            names.append(pwd.entries[entry_id]['title'])
            del pwd.db_json['entries'][entry_id]
        if force or click.confirm('Delete entries ' + click.style(', '.join(names), bold=True)):
            save_storage()
    clean_exit()

@cli.command()
@click.option('--tag', '-t', is_flag=True, help='insert tag')
def insert(tag):
    '''Insert entry or tag'''
    unlock_storage()
    if tag:
        t = edit_tag(TAG_NEW)
        pwd.insert_tag(t)
        save_storage()
    else:
        e = edit_entry(ENTRY_NEW)
        pwd.insert_entry(e)
        save_storage()
    clean_exit()

@cli.command()
@click.argument('entry-name', type=EntryName(), default='', nargs=1, autocompletion=tab_completion_entries)
@click.option('--tag', '-t', type=TagName(), default='', nargs=1, help='edit tag', autocompletion=tab_completion_tags)
def edit(entry_name, tag):#TODO option --entry/--tag with default
    '''Edit entry or tag'''
    unlock_storage()
    if tag:
        t = pwd.get_tag(tag)
        t = edit_tag(t)
        pwd.insert_tag(t)
        save_storage()
    else:
        e = pwd.get_entry(entry_name)
        e = edit_entry(e)
        pwd.insert_entry(e)
        save_storage()
    clean_exit()

@cli.command()
@click.argument('commands', type=click.STRING, nargs=-1)
def git(commands):
    '''Call git commands on password store'''
    subprocess.call('git '+ ' '.join(commands), cwd=CONFIG['path'], shell=True)
    clean_exit()

@cli.command()
@click.option('--edit', '-e', is_flag=True, help='edit config')
@click.option('--reset', '-r', is_flag=True, help='reset config')
@click.argument('setting-name', type=click.STRING, default='', nargs=1, autocompletion=tab_completion_config)
@click.argument('setting-value', type=SettingValue(), default='', nargs=1) # TODO autocompletion based on setting-name
def config(edit, reset, setting_name, setting_value):
    '''Configuration settings'''
    global CONFIG
    if edit:
        click.edit(filename=CONFIG_FILE, require_save=True)
    elif reset:
        if os.path.isfile(CONFIG_FILE):
            if click.confirm('Reset config?'):
                os.remove(CONFIG_FILE)
    else:
        if CONFIG.get(setting_name):
            CONFIG[setting_name] = setting_value
            write_config()
    clean_exit()

@cli.command()
@click.option('-f', '--force', is_flag=True, help='omnit dialog')
def unlock(force):
    '''Unlock and write metadata to disk'''
    unlock_storage()
    clean_exit()

@cli.command()
def lock():
    '''Remove metadata from disk'''
    if os.path.isfile(TMP_FILE):
        os.remove(TMP_FILE)
        click.echo(click.style('metadata deleted: ', bold=True) + TMP_FILE)
    else:
        click.echo(click.style('nothing to delete', bold=True)) 
    clean_exit()

@cli.command(name='export')# TODO CSV
@click.argument('tag-name', default='all', type=click.STRING, nargs=1, autocompletion=tab_completion_tags)
@click.argument('entry-name', type=click.STRING, nargs=-1, autocompletion=tab_completion_entries)
@click.option('-p', '--path', default=os.path.expanduser('~'), type=click.Path(), help='path for export')
@click.option('-f', '--file-format', default='json', type=click.Choice(['json', 'csv','txt']), help='file format')
def export_command(tag_name, entry_name, path, file_format):
    '''Export password store'''
    global entries
    unlock_storage()
    export_passwords = {}
    with click.progressbar(pwd.entries.items(), label='Decrypt entries', show_eta=False, fill_char='#', empty_char='-') as bar:
        for e in bar:
            e = pwd.unlock_entry(e, get_client())
            export_passwords.update( {str(e[0]) : {'item/url*':e[1]['note'], 'username':e[1]['username'], 'password':e[1]['password']['data'], 'secret':e[1]['safe_note']['data']}} )
    if file_format == 'json':
        with open(os.path.join(CONFIG_PATH, 'export.json'), 'w', encoding='utf8') as f:
            json.dump(export_passwords, f)
    elif file_format == 'csv':
        return
    clean_exit()

@cli.command(name='import')# TODO CSV; check for file extension
@click.argument('path-to-file', type=click.Path(), nargs=1)
def import_command(path_to_file):
    '''Import password store'''
    unlock_storage()
    try:
        if os.path.isfile(path_to_file):
            with open(path_to_file) as f:
                es = json.load(f)
    except Exception as ex:
        handle_exception('', 4, ex)
    with click.progressbar(es.items(), label='Decrypt entries', show_eta=False, fill_char='#', empty_char='-') as bar:    
        for k,v in bar:
            if 'item/url*' not in v or 'username' not in v or 'password' not in v or 'secret' not in v:
                handle_exception('Import gone wrong', 5)
            if not isinstance(v['item/url*'],str) or not isinstance(v['username'],str) or not isinstance(v['password'],str) or not isinstance(v['secret'],str):
                handle_exception('Import gone wrong', 5)
            if v['item/url*'] == '':
                handle_exception('item/url* field is mandatory', 6)
            e = ('',{'title': v['item/url*'], 'username': v['username'], 'password': {'type': 'String', 'data': v['password']}, 'nonce': '', 'tags': [], 'safe_note': {'type': 'String', 'data': v['secret']}, 'note': v['item/url*'], 'success': True, 'export': True})
            e = pwd.lock_entry(e, get_client())
            pwd.insert_entry(e)
    save_storage()
    clean_exit()

ALIASES = {
    'cp': clip,
    'copy': clip,
    'conf': config,
    'search': find,
    'ins': insert,
    'ls': list_command,
    'del': remove,
    'delete': remove,
    'rm': remove,
    'cat': show,
}