#!/usr/bin/env python3
from src import trezor as trezorapi
from src import crypto as cryptomodul
import click
import os
import subprocess
import sys
import csv
import tempfile
import pyperclip
import time
import re
try:
    import simplejson as json
except:
    import json
    
ICONS = {'home': {'emoji': '🏠'}, 'person-stalker': {'emoji': '👩‍👩‍👦'}, 'social-bitcoin': {'emoji': '₿'}, 'person': {'emoji': '😀'}, 'star': {'emoji': '⭐'}, 'flag': {'emoji': '🏳️'}, 'heart':{'emoji':'❤'}, 'settings': {'emoji':'⚙️'}, 'email':{'emoji':'✉️'},'cloud': {'emoji': '☁️'}, 'alert-circled': {'emoji':'⚠️'}, 'android-cart': {'emoji': '🛒'}, 'image': {'emoji': '🖼️'}, 'card': {'emoji': '💳'}, 'earth': {'emoji': '🌐'}, 'wifi': {'emoji': '📶'}}
DROPBOX_PATH = os.path.join(os.path.expanduser('~'), 'Dropbox', 'Apps', 'TREZOR Password Manager')
GOOGLE_DRIVE_PATH = os.path.join(os.path.expanduser('~'), 'Google Drive', 'Apps', 'TREZOR Password Manager')
DEFAULT_PATH = os.path.join(os.path.expanduser('~'), '.tpassword-store')
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.tpass')
CONFIG_FILE = os.path.join(CONFIG_PATH, 'config.json')
DICEWARE_FILE = os.path.join(CONFIG_PATH, 'wordlist.txt')
DEV_SHM = os.path.join('/', 'dev', 'shm')
CLIPBOARD_CLEAR_TIME = 15
CONFIG = {'fileName': '', 'path': DEFAULT_PATH, 'useGit': False, 'pinentry': False, 'defaultEditor': '', 'clipboardClearTimeSec': CLIPBOARD_CLEAR_TIME, 'storeMetaDataOnDisk': True, 'showIcons': False}
DB_FILE = os.path.join(CONFIG['path'], CONFIG['fileName'])
TMP_FILE = os.path.join(DEV_SHM, CONFIG['fileName'], '.json')

tag_new = ('',{'title': '', 'icon': 'home'})
entry_new = ('',{'title': '', 'username': '', 'password': {'type': 'String', 'data': ''}, 'nonce': '', 'tags': [], 'safe_note': {'type': 'String', 'data': ''}, 'note': '', 'success': True, 'export': True})
tags = {'0': {'title': 'All', 'icon': 'home'}, }
entries = {}
db_json = {'version': '0.0.1', 'extVersion': '0.6.0', 'config': {'orderType': 'date'}, 'tags': tags, 'entries': entries}
client = None

'''
Core Methods
'''
def loadConfig():
    global CONFIG
    global TMP_FILE
    if not os.path.isfile(CONFIG_FILE):
        writeConfig()
    with open(CONFIG_FILE) as f:
        CONFIG = json.load(f)
    if 'fileName' not in CONFIG or 'path' not in CONFIG or 'storeMetaDataOnDisk' not in CONFIG:
        sys.exit('Error: config parse error: ' + CONFIG_PATH)
    if CONFIG['storeMetaDataOnDisk'] is True:
        if not os.path.exists(DEV_SHM):
            TMP_FILE = os.path.join(os.path.join(tempfile.gettempdir()), CONFIG['fileName'] + '.json')
            click.echo('warning: /dev/shm not found on host, using not as secure /tmp/ for plain metadata')

def writeConfig():
    if not os.path.exists(CONFIG_PATH):    
        os.mkdir(CONFIG_PATH)
    with open(CONFIG_FILE, 'w', encoding='utf8') as f:
        json.dump(CONFIG, f, indent=4)
 
def unlockStorage():
    global db_json; global entries; global tags
    tmpNeedUpdate = False
    if CONFIG['fileName'] == '' or not os.path.isfile(DB_FILE):
        sys.exit('Password store is not initialized')
    if CONFIG['storeMetaDataOnDisk'] is True:
        tmpNeedUpdate = not os.path.isfile(TMP_FILE) or (os.path.isfile(TMP_FILE) and (os.path.getmtime(TMP_FILE) < os.path.getmtime(DB_FILE)))
    if CONFIG['storeMetaDataOnDisk'] is False or tmpNeedUpdate:
        getClient()
        try:
            keys = trezorapi.getTrezorKeys(client)
            encKey = keys[2]
        except:
            sys.exit('Error while getting keys from device')
        try:
            db_json = cryptomodul.decryptStorage(DB_FILE, encKey)
        except:
            sys.exit('Error while decrypting storage')
        entries = db_json['entries']; tags = db_json['tags']
        if CONFIG['storeMetaDataOnDisk'] is True:
            with open(TMP_FILE, 'w') as f:  
                json.dump(db_json, f)
    if CONFIG['storeMetaDataOnDisk'] is True:
        with open(TMP_FILE) as f:
            db_json = json.load(f)
            entries = db_json['entries']; tags = db_json['tags']

def saveStorage():
    global CONFIG
    getClient()
    try:
        keys = trezorapi.getTrezorKeys(client)
        encKey = keys[2]
    except:
        sys.exit('Error while accessing trezor device')
    try:
        cryptomodul.encryptStorage(db_json, DB_FILE, encKey)
    except:
        sys.exit('Error while encrypting storage')
    if CONFIG['storeMetaDataOnDisk'] is True:
        with open(TMP_FILE, 'w') as f:
            json.dump(db_json, f) 
    if CONFIG['useGit'] is True:
        subprocess.call('git commit -m "update db"', cwd=CONFIG['path'], shell=True)

def loadWordlist():
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
    except:
        sys.exit('Error: while processing wordlist.txt file')
    return words

def clearClipboard():
    with click.progressbar(length=CONFIG['clipboardClearTimeSec'], label='Clipboard will clear', show_percent=False, fill_char='#', empty_char='-') as bar:
        for i in bar:
            time.sleep(1)
    pyperclip.copy('')

def getClient():
    global client
    if client is None:
        try:
            client = trezorapi.getTrezorClient()
        except:
            sys.exit('Error while accessing trezor device')

def parseName(input_str):
    tag = ''; note = ''; username = ''; entry_id = ''
    if input_str.startswith('#') or '#' in input_str:
        entry_id = input_str.split('#')[1]
    elif not '/' in input_str:
        tag = note = input_str
    else:
        if not ':' in input_str:
            tag = input_str.split('/')[0]
            note = input_str.split('/')[1]
        else:
            tag = input_str.split('/')[0]
            username = input_str.split(':')[1]
            note = input_str.split('/')[1].split(':')[0]
    return tag, note, username, entry_id

def getEntry(name):
    names = parseName(name)
    note = names[1]; username = names[2]; entry_id = names[3]
    if entry_id != '' and entries.get(entry_id):
        return entry_id, entries[entry_id]
    for k, v in entries.items():
        if note.lower() == v['note'].lower():
            if username == '' or username.lower() == v['username'].lower():
                return k, v
    sys.exit('Error: ' + name + ' is not in the password store')

def getTag(tag_name):
    tag_name = parseName(tag_name)[0]
    for k, v in tags.items():
        if tag_name.lower() == v['title'].lower():
            return k, v
    sys.exit('Error: ' + tag_name + ' is not a tag in the password store')

def getEntriesByTag(tag_id):#TODO optimze
    es = {}
    for k, v in entries.items():
        if int(tag_id) in v['tags'] or int(tag_id) == 0 and v['tags'] == []:
            es.update( {k : v} )  
    return es

def printEntries(es, includeTree=False):#TODO optimze
    if includeTree:
        start = '  ├── ';start_end = '  └── '
    else:
        start = ''; start_end = ''
    i = 0
    for k,v in es.items():
        if i == len(es)-1:
            click.echo(start_end + v['note'] + ':' + click.style(v['username'], fg='green') + click.style('#' + k, fg='magenta'))
        else:
            click.echo(start + v['note'] + ':' + click.style(v['username'], fg='green') + click.style('#' + k, fg='magenta'))
        i = i + 1

def printTags(ts, includeEntries=False):
    for k,v in ts.items():
        if CONFIG['showIcons'] is True:
            icon = ICONS.get(v['icon'])['emoji'] + ' ' or '? '
        else:
            icon = ''
        click.echo(icon + click.style(v['title'] + '/',bold=True , fg='blue'))
        if includeEntries:
            es = getEntriesByTag(k)
            printEntries(es, True)

def tagsToString(ts, includeIds=False):
    tags_str = ''
    for k,v in ts.items():
        if CONFIG['showIcons'] is True:
            icon = ICONS.get(v['icon'])['emoji'] + ' ' or '? '
        else:
            icon = ''
        if includeIds:
            tags_str = tags_str + k + ':' + icon + v['title'] + ' '
        else:
            tags_str = tags_str + icon + v['title'] + ' '
    return tags_str.strip()

def iconsToString():
    icon_str = ''
    for k,v in ICONS.items():
        icon_str = icon_str + k + ':' + v['emoji'] + ', '
    return icon_str

def unlockEntry(e):
    entry_id = e[0]; entry = e[1]
    if entry['success'] is False or entry['export'] is True:
        sys.exit('Error: while unlocking entry')
    entry['success'] = False; entry['export'] = True
    try:   
        getClient()
        plain_nonce = trezorapi.getDecryptedNonce(client, entry)
    except:
        sys.exit('Error: while accessing trezor device')    
    try:
        entry['password']['data'] = cryptomodul.decryptEntryValue(plain_nonce, entry['password']['data'])
        entry['safe_note']['data'] = cryptomodul.decryptEntryValue(plain_nonce, entry['safe_note']['data'])
        entry['password']['type'] = 'String'; entry['safe_note']['type'] = 'String'
        entry['success'] = True
    except:
        sys.exit('Error: while decrypting entry')
    return e

def lockEntry(e):
    entry_id = e[0]; entry = e[1]
    if entry['success'] is False or entry['export'] is False:
        sys.exit('Error: while locking entry')
    entry['success'] = False; entry['export'] = False
    try:
        getClient()
        entry['nonce'] = trezorapi.getEncryptedNonce(client, entry)
        plain_nonce = trezorapi.getDecryptedNonce(client, entry)
    except:
        sys.exit('Error: while accessing trezor device')
    try:
        entry['password']['data'] = cryptomodul.encryptEntryValue(plain_nonce, json.dumps(entry['password']['data']))
        entry['safe_note']['data'] = cryptomodul.encryptEntryValue(plain_nonce, json.dumps(entry['safe_note']['data']))
        entry['password']['type'] = 'Buffer'; entry['safe_note']['type'] = 'Buffer'
        entry['success'] = True
    except:
        sys.exit('Error: while decrypting entry')
    return e

def insertEntry(e):
    global entries
    entry_id = e[0]; entry = e[1]
    if entry['success'] is False or entry['export'] is True:
        sys.exit('Error: while inserting entry')
    if entry_id == '':
        for k in entries.keys():
            entry_id = str(int(k) + 1)
        if entry_id == '':
            entry_id = '0'
    entries.update( {entry_id : entry} )

def editEntry(e): #TODO correct, simplify, use editor from CONFIG
    entry_id = e[0]; entry = e[1]
    if entry['export'] is False:
        e = unlockEntry(e)
    if entry['success'] is False:
        sys.exit('Error: while editing entry')
    entry['success'] = False
    # TODO print Tags without ID to choose from + inUse
    edit_json = {'item/url*':entry['note'], 'title':entry['title'], 'username':entry['username'], 'password':entry['password']['data'], 'secret':entry['safe_note']['data'], 'tags': {"inUse:":entry['tags'], "chooseFrom:": tagsToString(tags, True)}}
    edit_json = click.edit(json.dumps(edit_json, indent=4), require_save=True, extension='.json', editor=CONFIG['defaultEditor'])
    if edit_json:
        try:
            edit_json = json.loads(edit_json)
        except:
            sys.exit('Error: edit gone wrong')
        if edit_json['item/url*'] is None or edit_json['item/url*'] == '':
            sys.exit('item/url* field is mandatory')
        entry['note'] = edit_json['item/url*'];entry['title'] = edit_json['title'];entry['username'] = edit_json['username'];entry['password']['data'] = edit_json['password'];entry['safe_note']['data'] = edit_json['secret']
        entry['success'] = True
        return lockEntry(e)
    sys.exit('Aborted!')

def editTag(t):
    tag_id = t[0]; tag = t[1]
    edit_json = {"title": tag['title'], "icon":tag['icon'], "chooseIconFrom:":iconsToString()}
    edit_json = click.edit(json.dumps(edit_json, indent=4), require_save=True, extension='.json', editor=CONFIG['defaultEditor'])
    if edit_json:
        tag['title'] = edit_json['title']; tag['icon'] = edit_json['icon']
        return t
    sys.exit('Aborted!')

def insertTag(t):
    global tags
    tag_id = t[0]; tag = t[1]
    if tag_id == '':
        for k in tags.keys():
            tag_id = str(int(k) + 1)
        if tag_id == '':
            tag_id = '0'
    tags.update( {tag_id : tag} )

def removeTag(t):
    global db_json; global entries
    tag_id = t[0]; tag = t[1]
    if tag_id == '0':
        sys.exit('Error: cannot remove <all> tag')
    del db_json['tags'][tag_id]
    es = getEntriesByTag(tag_id)
    for e in es:
        entries[e]['tags'].remove(int(tag_id))

def tabCompletionEntries(ctx, args, incomplete):
    loadConfig()
    unlockStorage()
    tabs = []
    for k,v in tags.items():
        selEntries = getEntriesByTag(k)
        for kk,vv in selEntries.items():
            tabs.append(v['title'].lower() + '/' + vv['note'].lower() + ':' + vv['username'].lower() + '#' + kk)
    return [k for k in tabs if incomplete.lower() in k]

def tabCompletionTags(ctx, args, incomplete):
    loadConfig()
    unlockStorage()
    tabs = []
    for t in tags:
        tabs.append(tags[t]['title'].lower() + '/')
    return [k for k in tabs if incomplete.lower() in k]

def tabCompletionConfig(ctx, args, incomplete):
    loadConfig()
    return [k for k in CONFIG if incomplete.lower() in k]
'''
CLI Methods
'''

@click.group()
@click.version_option()
def cli():
    '''
    ~+~#~+~~+~#~+~~+~#~+~~+~#~+~~+~#~+~\n
            tpass\n
    +~#~+~~+~#~+~~+~#~+~~+~#~+~~+~#~+~~\n

    CLI for Trezor Password Manager inspired by pass\n
    Untested Beta Software! - Do not use it\n
        
    @author: makk4 <manuel.kl900@gmail.com>\n

    https://github.com/makk4/tpass
    '''

    loadConfig()
    pass

@cli.command()
@click.option('-p', '--path', default=DEFAULT_PATH, type=click.Path(), help='path to database')
@click.option('-c', '--cloud', default='offline', type=click.Choice(['dropbox', 'googledrive', 'git', 'offline']), help='cloud provider: <dropbox> <googledrive> <git>')
@click.option('-a', '--pinentry', is_flag=True, help='ask for password on device')
@click.option('-d', '--no-disk', is_flag=True, help='do not store metadata on disk')
def init(path, cloud, pinentry, no_disk):
    '''Initialize new password store'''
    global CONFIG; global DB_FILE; global TMP_FILE
    CONFIG['path'] = path; CONFIG['storeMetaDataOnDisk'] = not no_disk; CONFIG['pinentry'] = pinentry
    if cloud == 'googledrive':
        CONFIG['path'] = GOOGLE_DRIVE_PATH
    elif cloud == 'dropbox':
        CONFIG['path'] = DROPBOX_PATH
    if not os.path.exists(path):
        os.makedirs(path)
    if len(os.listdir(path)) != 0:
        sys.exit(path + ' is not empty, not initialized')
    if cloud == 'git':
        CONFIG['useGit'] = True
        subprocess.call('git init', cwd=CONFIG['path'], shell=True)
    getClient()
    try:
        keys = trezorapi.getTrezorKeys(client)
        CONFIG['fileName'] = keys[0]
    except:
        sys.exit('Error while getting keys from device')
    DB_FILE = os.path.join(CONFIG['path'], CONFIG['fileName'])
    writeConfig()
    loadConfig()
    saveStorage()
    if cloud == 'git':
        subprocess.call('git add *.pswd', cwd=CONFIG['path'], shell=True)    
    click.echo('password store initialized in ' + path)
    sys.exit(0)

@cli.command()
@click.argument('name', type=click.STRING, nargs=1)
def find(name):# TODO alias
    '''List entries and tags that match names'''
    unlockStorage()
    es = {}; ts = {}
    for k,v in entries.items():
        if name.lower() in v['note'].lower() or name.lower() in v['title'].lower() or name.lower() in v['username'].lower():
            es.update( {k : v} ) 
    for k,v in tags.items():
        if name.lower() in v['title'].lower():
            ts.update( {k : v} ) 
    printEntries(es)
    printTags(ts)
    sys.exit(0)

@cli.command()
@click.argument('name', type=click.STRING, nargs=1)
@click.option('-i', '--case-insensitive', is_flag=True, help='not case sensitive search')
def grep(name, case_insensitive):
    '''Search for names in decrypted entries'''
    unlockStorage()
    for k, v in entries.items():
        v = unlockEntry((k,v))[1]
        for kk, vv in v.items():
            if kk in ['note', 'title', 'username']:
                if name.lower() in vv.lower():
                    click.echo(click.style(v['note'] + ':', bold=True) + click.style(v['username'], bold=True, fg='green') + click.style('#' + k, bold=True, fg='magenta') + click.style('//<' + kk + '>//: ', fg='blue') + vv)
        if name.lower() in v['password']['data'].lower():    
            click.echo(click.style(v['note'] + ':', bold=True) + click.style(v['username'], bold=True, fg='green') + click.style('#' + k, bold=True, fg='magenta') + click.style('//<password>//: ', fg='blue') + v['password']['data'])
        if name.lower() in v['safe_note']['data'].lower():  
            click.echo(click.style(v['note'] + ':', bold=True) + click.style(v['username'], bold=True, fg='green') + click.style('#' + k, bold=True, fg='magenta') + click.style('//<secret>//: ', fg='blue') + v['safe_note']['data'])
    sys.exit(0)

@cli.command()
@click.argument('tag-name', default='', type=click.STRING, nargs=1, autocompletion=tabCompletionTags)
def ls(tag_name):# TODO alias
    '''List entries by tag'''
    unlockStorage()
    if tag_name == '':
        printTags(tags, True)
    else:
        t = getTag(tag_name)
        printTags({t[0] : t[1]}, True)
    sys.exit(0)
    
@cli.command()
@click.argument('entry-names', type=click.STRING, nargs=-1, autocompletion=tabCompletionEntries)
@click.option('-s', '--secrets', is_flag=True, help='show password and secret notes')
@click.option('-j', '--json', is_flag=True, help='json format')
def show(entry_names, secrets, json): # TODO alias
    '''Show entries'''
    unlockStorage()
    for name in entry_names:
        e = getEntry(name)
        entry = e[1]; entry_id = e[0]

        if not secrets:
            pwd = '********'
            safeNote = '********'
        else:
            e = unlockEntry(e)
            pwd = entry['password']['data']
            safeNote = entry['safe_note']['data']
        if json:
            click.echo(e)
        else:
            ts = {}
            for i in entry['tags']:
                ts[i] = tags.get(str(i))

            click.echo(click.style('#' + entry_id, bold=True, fg='magenta') + '\n' +
                click.style('item/url*: ', bold=True) + entry['note'] + '\n' +
                click.style('title:     ', bold=True) + entry['title'] + '\n' +
                click.style('username:  ', bold=True) + entry['username'] + '\n' +
                click.style('password:  ', bold=True) + pwd + '\n' +
                click.style('secret:    ', bold=True) + safeNote  + '\n' +
                click.style('tags:      ', bold=True) + tagsToString(ts))
    sys.exit(0)

@cli.command()
@click.option('-u', '--user', is_flag=True, help='copy user')
@click.option('-i', '--url', is_flag=True, help='copy item/url*')
@click.option('-s', '--secret', is_flag=True, help='copy secret')
@click.argument('entry-name', type=click.STRING, nargs=1, autocompletion=tabCompletionEntries)
def clip(user, url, secret, entry_name):# TODO alias
    '''Decrypt and copy line of entry to clipboard'''
    unlockStorage()
    e = getEntry(entry_name)
    entry = e[1]; entry_id = e[0]
    if user:
        pyperclip.copy(entry['username'])
    elif url:
        pyperclip.copy(entry['title'])
    else:
        e = unlockEntry(e)
        if secret:
            pyperclip.copy(entry['password']['data'])
        else:
            pyperclip.copy(entry['safe_note']['data'])
        clearClipboard()
    sys.exit(0)     
    
@cli.command()# TODO callback eager options
@click.argument('length', default=15, type=int)
@click.option('-i', '--insert', default=None, type=click.STRING, nargs=1, autocompletion=tabCompletionEntries)
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
            sys.exit(-1)
    if entropy:
        getClient()
        entropy = trezorapi.getEntropy(client, length)
    else:
        entropy = None
    if type_ == 'wordlist':
        words = loadWordlist()
        pwd = cryptomodul.generatePassphrase(length, words, seperator, entropy)
    elif type_ == 'pin':
        pwd = cryptomodul.generatePin(length)
    elif type_ == 'password':
        pwd = cryptomodul.generatePassword(length)
    if insert:
        unlockStorage()
        e = getEntry(insert)
        e = unlockEntry(e)
        e[1]['password']['data'] = pwd
        e = editEntry(e)
        insertEntry(e)
        if force or click.confirm('Insert password in entry ' + click.style(e[1]['title'], bold=True)):
            saveStorage()
    if clip:
        pyperclip.copy(pwd)
        clearClipboard()
    else:
        click.echo(pwd)
    sys.exit(0)

@cli.command()
@click.option('--tag', '-t', type=click.STRING, help='remove tag', nargs=1, autocompletion=tabCompletionTags)
@click.option('--force', '-f', is_flag=True, help='force without confirmation')
@click.argument('entry-name', type=click.STRING, default='', nargs=1, autocompletion=tabCompletionEntries)
def rm(entry_name, tag, force):# TODO alias; make options TRU/FALSE tag and -1 all args
    '''Remove entry or tag'''
    unlockStorage()
    global db_json
    if tag:
        t = getTag(tag)
        removeTag(t)
        if force or click.confirm('Delete tag: ' + click.style(t[1]['title'], bold=True)):
            saveStorage()
    else:
        entry_id = getEntry(entry_name)[0]
        del db_json['entries'][entry_id]
        if force or click.confirm('Delete entry ' + click.style(entries[entry_id]['title'], bold=True)):
            saveStorage()
    sys.exit(0)

@cli.command()
@click.option('--tag', '-t', is_flag=True, help='insert tag')
def insert(tag):
    '''Insert entry or tag'''
    unlockStorage()
    if tag:
        t = editTag(tag_new)
        insertTag(t)
        saveStorage()
    else:
        e = editEntry(entry_new)
        insertEntry(e)
        saveStorage()
    sys.exit(0)

@cli.command()
@click.argument('entry-name', type=click.STRING, default='', nargs=1, autocompletion=tabCompletionEntries)
@click.option('--tag', '-t', type=click.STRING, default='', nargs=1, help='edit tag', autocompletion=tabCompletionTags)
def edit(entry_name, tag):#TODO option --entry/--tag with default
    '''Edit entry or tag'''
    unlockStorage()
    if tag:
        t = getTag(tag)
        t = editTag(t)
        insertTag(t)
        saveStorage()
    else:
        e = getEntry(entry_name)
        e = editEntry(e)
        insertEntry(e)
        saveStorage()
    sys.exit(0)

@cli.command()
@click.argument('commands', type=click.STRING, nargs=-1)
def git(commands):
    '''Call git commands on password store'''
    subprocess.call('git '+ ' '.join(commands), cwd=CONFIG['path'], shell=True)
    sys.exit(0)

@cli.command()
@click.option('--edit', '-e', is_flag=True, help='edit config')
@click.option('--reset', '-r', is_flag=True, help='reset config')
@click.argument('setting-name', type=click.STRING, default='', nargs=1, autocompletion=tabCompletionConfig)
@click.argument('setting-value', type=click.STRING, default='', nargs=1)
def config(edit, reset, setting_name, setting_value): # TODO parse settings
    '''Configuration settings'''
    global CONFIG
    if edit:
        click.edit(filename=CONFIG_FILE, require_save=True, editor=CONFIG['defaultEditor'])
    elif reset:
        if os.path.isfile(CONFIG_FILE):
            os.remove(CONFIG_FILE)
    else:
        writeConfig()
    sys.exit(0)

@cli.command()
@click.option('-f', '--force', is_flag=True, help='omnit dialog')
def unlock(force):
    '''Unlock and write metadata to disk'''
    unlockStorage()
    sys.exit(0)

@cli.command()
def lock():
    '''Remove metadata from disk'''
    if os.path.isfile(TMP_FILE):
        os.remove(TMP_FILE)
        click.echo(click.style('metadata deleted: ', bold=True) + TMP_FILE)
    else:
        click.echo(click.style('nothing to delete', bold=True)) 
    sys.exit(0)

@click.argument('tag-name', default='all', type=click.STRING, nargs=1, autocompletion=tabCompletionTags)
@click.argument('entry-name', type=click.STRING, nargs=-1, autocompletion=tabCompletionEntries)
@click.option('-p', '--path', default=os.path.expanduser('~'), type=click.Path(), help='path for export')
@click.option('-f', '--file-format', default='json', type=click.Choice(['json', 'csv','txt']), help='file format')
@cli.command()
def exportdb(tag_name, entry_name, path, file_format):# TODO CSV
    '''Export password store'''
    global entries
    unlockStorage()
    with click.progressbar(entries, label='Decrypt entries', show_eta=False, fill_char='#', empty_char='-') as bar:
        for e in bar:
            entries[e] = unlockEntry(e)[1]
    if file_format == 'json':
        with open(os.path.join('.', 'export.json'), 'w', encoding='utf8') as f:
            json.dump(entries, f)
    elif file_format == 'csv':
        with open(os.path.join('.', 'export.csv'), 'w') as f:
            writer = csv.writer(f, delimiter=',',quotechar='|', quoting=csv.QUOTE_MINIMAL)
            for e in entries.items():
                writer.writerow({e['note'], e['title'], e['username'],e['password']['data'],e['safe_note']['data']})
    sys.exit(0)

@cli.command()
@click.option('-p', '--path', type=click.Path(), help='path to import file')
def importdb(es):# TODO CSV   
    '''Import password store'''
    unlockStorage()
    for e in es.items():
        lockEntry(e)
        insertEntry(e)
        saveStorage()
    sys.exit(0)
