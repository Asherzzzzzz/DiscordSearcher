import time
import datetime
import json
import requests
from fake_useragent import UserAgent
import sqlite3
import random
import discord
import asyncio


# Constants
REQUEST_TIMEOUT = 10
RETRY_INTERVAL_TIME = 20

# To avoid error 429(too many requests)
# Updating delay time
MIN_UPDATE_INTERVAL_TIME = 60
MAX_UPDATE_INTERVAL_TIME = 120
FREQUENT_MODE_UPDATE_INTERVAL_TIME = 10
FREQUENT_MODE_LIMIT_TIME = 5 * 60

# Variable
frequent_mode = 0
program_stop = 0

# To interact with discord bot
client = discord.Client(intents=discord.Intents.all())


# Output error when the status code is less than 400
def check_status_code(response):
    if not response.ok:
        print('ERROR ', response.status_code, ', failed to request ', response.url)
        with open('log/error.log', 'a') as file:
            file.write(time.asctime(time.localtime(time.time())) 
                       + ' - ' + response.reason 
                       + ' - ' + response.url + '\n\n')
        
    return response.ok


# Login and fetch the token(authorization)
def fetch_token(fail_counter = 0):
    try:
        # Send request to get the data with a token inside
        response = session_requests.post('https://discord.com/api/v9/auth/login', 
                                         headers=login_headers,
                                         json=post_data)
        # If fail then retry
        if not check_status_code(response):
            print('fail to login...')
            time.sleep(RETRY_INTERVAL_TIME)
            fail_counter += 1
            print('\nretry ', fail_counter)
            return fetch_token(fail_counter)
        else:
            response_dict = response.json();
            with open('secret/secret_token.json', 'r+') as file:
                # Update token
                token = json.load(file)
                token['authorization'] = response_dict['token']
                file.seek(0)
                json.dump(token, file)
                file.truncate()

            with open('json/search_headers.json', 'r') as file:
                # Renew the token in search_headers
                search_headers = json.load(file)
                search_headers['authorization'] = token['authorization']
                print('login & fetch token successfully')
                return search_headers
            
    except Exception as e:
        print('ERROR, login & fetching token process error, check the error.log for more information')
        with open('log/error.log', 'a') as file:
            file.write('{} - {} - {}\n'.format(time.asctime(time.localtime(time.time())),
                                               e,
                                               response.reason))
            time.sleep(RETRY_INTERVAL_TIME)
            fail_counter += 1
            print('\nretry ', fail_counter)
            return fetch_token(fail_counter)
    

# Send request to the discord message searcher to get the messages
async def search_request():
    while not program_stop:
        search_headers['user-agent'] = UserAgent().random

        try:
            response = session_requests.get(search_target['request_url'], 
                                            headers=search_headers, 
                                            timeout=REQUEST_TIMEOUT)    
            if check_status_code(response):
                response_dict = response.json();

                current_time = datetime.datetime.now()
                print(current_time.strftime("[%Y-%m-%d %H:%M:%S] "), 'search successfully')

                db_storing(response_dict['messages']) 
                                
        except Exception as e:
            print('ERROR, searching process error, check the error.log for more information')
            bot_send_error('ERROR, searching process error, check the error.log for more information')

            with open('log/error.log', 'a') as file:
                file.write('{} - {} - {}\n'.format(time.asctime(time.localtime(time.time())), 
                                                   e,
                                                   response.reason))
                
        if not frequent_mode:
            await asyncio.sleep(random.randint(MIN_UPDATE_INTERVAL_TIME, 
                                               MAX_UPDATE_INTERVAL_TIME))
        else:
            await asyncio.sleep(FREQUENT_MODE_UPDATE_INTERVAL_TIME)


def db_storing(data):  
    conn = sqlite3.connect("database/data.db")
    cursor = conn.cursor()     
    
    for i in range(len(data) - 1, -1 , -1):
        message_id = data[i][0]['id']
        timestamp = data[i][0]['timestamp']
        edited_timestamp = data[i][0]['edited_timestamp']
        channel_id = data[i][0]['channel_id']
        message_url = 'https://discord.com/channels/{}/{}/{}'.format(search_target['server_id'], 
                                                                     data[i][0]['channel_id'], 
                                                                     data[i][0]['id'])
        content = content_modify(data[i][0]['content'])
        has_attachment = 0
        
        # Insert new data into db
        if cursor.execute("SELECT NOT EXISTS (SELECT 1 FROM Namin_message_content WHERE id = ?)", 
                           (message_id,)
                           ).fetchone()[0]:
            # When the data is updating, open the frequent mode
            asyncio.create_task(frequent_mode_timer())

            # Check if it has attachments
            if len(data[i][0]['attachments']) > 0:
                has_attachment = 1
                
                for attachment in data[i][0]['attachments']:
                    attachment_url = 'https://media.discordapp.net/attachments/{}/{}/{}'.format(channel_id, 
                                                                                                attachment['id'], 
                                                                                                attachment['filename'])
                    
                    cursor.execute("INSERT INTO Namin_message_attachment (id, attachment_url) VALUES (?, ?)", (message_id, 
                                                                       attachment_url))
                    conn.commit()
            
            elif 'sticker_items' in data[i][0]:
                has_attachment = 1
                attachment_url = 'https://media.discordapp.net/stickers/{}.webp='.format(data[i][0]['sticker_items'][0]['id'])
                cursor.execute("INSERT INTO Namin_message_attachment (id, attachment_url) VALUES (?, ?)", (message_id, 
                                                                                                           attachment_url))
                conn.commit()
                
            cursor.execute("INSERT INTO Namin_message_content (id, timestamp, url, content, has_attachment) VALUES (?, ?, ?, ?, ?)", (message_id, 
                                                                                                                                      timestamp, 
                                                                                                                                      message_url, 
                                                                                                                                      content, 
                                                                                                                                      has_attachment))
            conn.commit()

        # Update data in db
        elif cursor.execute("SELECT EXISTS (SELECT 1 FROM Namin_message_content WHERE id = ? AND edited_timestamp <> ?)", (message_id, 
                                                                                                                           edited_timestamp)
                                                                                                                          ).fetchone()[0]:
            # When the data is updating, open the frequent mode
            asyncio.create_task(frequent_mode_timer())
            
            cursor.execute("UPDATE Namin_message_content SET edited_timestamp = ?, content = ?, has_sent = ? WHERE id = ?", (edited_timestamp, 
                                                                                                                             content, 
                                                                                                                             0, 
                                                                                                                             message_id))
            conn.commit()


def content_modify(data):
    data = data.replace('"', '""')
    data = data.replace("'", "''")
    return data


async def frequent_mode_timer():
    global frequent_mode

    if frequent_mode:
        return
    else:
        frequent_mode = 1
        print('frequent mode on')
    
        await asyncio.sleep(FREQUENT_MODE_LIMIT_TIME)

        frequent_mode = 0
        print('frequent mode off')

'''
def detect_user_command():
    global program_stop

    while not program_stop:
        try:
            if input() == "/q":
                program_stop = 1
                print('program terminated')
        except:
            print('no input')
        time.sleep(0.01)
'''


'''
main section

1.loading json file
2.request_session setup
3.fetch authorization token
4.Run Discord Bot
5.(waiting for Bot, it will continue after bot is on ready)
6.make search_request, fetch messages
7.store them into database
8.if there's new or updated data, send to Discord via Bot
'''


# Headers json file
with open('json/login_headers.json', 'r') as file:
    login_headers = json.load(file)
    
with open('secret/secret_post_data.json', 'r') as file:
    post_data = json.load(file)
    
with open('secret/secret_search_target.json', 'r') as file:
    search_target = json.load(file)

file = open('log/error.log', 'w')
file.close()


# Make requesting session to discord
session_requests = requests.session()

# Login(fetch_token function)
search_headers = fetch_token()

# Setup sending search_request loop 


'''
Bot section
'''


@client.event
async def on_ready():
    global sys_channel
    global error_channel
    global command_channel
    global m_channel

    # Bot's status
    activity = discord.Game(name = "I'm working...")
    await client.change_presence(status = discord.Status.online, activity = activity)
    
    # Find the target channel by name
    sys_channel = discord.utils.get(client.get_all_channels(), name="system-notice")
    error_channel = discord.utils.get(client.get_all_channels(), name="error-log")
    command_channel = discord.utils.get(client.get_all_channels(), name="user-commands")
    m_channel = discord.utils.get(client.get_all_channels(), name="💌messages")

    # Send a message to the channel
    # And execute search function concurrently
    asyncio.gather(bot_send_notice("DiscordSearcher is on & Bot connect successfully"),
                   search_request(),
                   check_if_new_data())


@client.event
async def on_message(message):
    global program_stop

    if message.author == client.user:
        return

    if message.channel == command_channel and message.content == '/terminate':
        activity = discord.Game(name = "Sleeping...zzZ")
        await client.change_presence(status = discord.Status.idle, activity = activity)

        print('Program is terminated by user.')
        await bot_send_notice('Program is terminated by user.')

        program_stop = 1
    elif message.channel == command_channel and message.content == '/reboot':
        #reboot
        print('Program is rebooted by user.')
        await bot_send_notice('Program is rebooted by user.')

        program_stop = 0
        await client.change_presence(status = discord.Status.online, activity = None)

        asyncio.gather(search_request(),
                       check_if_new_data())


@client.event
async def on_disconnect():
    print('Discord bot disconnected...')

    while not client.is_ready():
        try:
            with open('secret/secret_token.json', 'r') as file:  
                await client.start(json.load(file)['bot_token'])
            print('reconnected successfully')
        except Exception as e:
            print(f'Failed to reconnect: {e}')

    
async def bot_send_notice(text):
    await client.wait_until_ready()
    await sys_channel.send(text)


async def bot_send_error(text):
    await client.wait_until_ready()
    await error_channel.send(text) 

async def bot_send_message(text):
    await client.wait_until_ready()
    await m_channel.send(text)

# Send unsent message
async def check_if_new_data():
    while not program_stop:
        conn = sqlite3.connect("database/data.db")
        cursor = conn.cursor()
    
        if cursor.execute("SELECT EXISTS (SELECT 1 FROM Namin_message_content WHERE has_sent = ?)", (0,)).fetchone()[0]:
            print('messages uploading')

            messages = cursor.execute("SELECT * FROM Namin_message_content WHERE has_sent = ? ORDER BY timestamp ASC", (0,)).fetchall()

            for message in messages:
                message_id = message[1]
                timestamp = message[2]
                edited_timestamp = message[3]
                message_url = message[4]
                content = message[5]
                has_attachment = message[6]

                entire_message = '> {timestamp}\n> {edited_timestamp}\n> {message_url}\n```{content}```'.format(timestamp = timestamp, 
                                                                                                                edited_timestamp = edited_timestamp, 
                                                                                                                message_url = message_url, 
                                                                                                                content = content)

                await asyncio.create_task(bot_send_message(entire_message))

                if has_attachment:
                    attachments = cursor.execute("SELECT * FROM Namin_message_attachment WHERE id = ?", (message_id,))

                    for attachment in attachments:
                        attachment_url = attachment[2]
                        await asyncio.create_task(bot_send_message('\n' + attachment_url))
                
                await asyncio.create_task(bot_send_message('\n=======================================\n'))

                cursor.execute("UPDATE Namin_message_content SET has_sent = ? WHERE id = ? ", (1, 
                                                                                               message_id))
                conn.commit()
        
        await asyncio.sleep(10)

with open('secret/secret_token.json', 'r') as file:
    # Run Bot
    client.run(json.load(file)['bot_token'])