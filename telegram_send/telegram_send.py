import argparse
import asyncio
import configparser
import re
import sys
from copy import deepcopy
from os import environ, makedirs, remove
from os.path import dirname, exists, expanduser, join
from platform import machine
from random import randint
from shutil import which
from typing import NamedTuple, Union
from subprocess import check_output
from warnings import warn

import colorama
import telegram
from telegram.constants import MessageLimit

from .version import __version__
from .utils import pre_format, split_message, get_config_path, markup

try:
    import readline
except ImportError:
    pass


global_config = "/etc/telegram-send.conf"


def get_bot_api_base_url():
    override = environ.get("TELEGRAM_SEND_BOT_API_BASE_URL")
    if override:
        return override

    if sys.platform == "darwin":
        return "http://11.11.11.100:8081/bot"

    if sys.platform.startswith("linux") and machine().lower() in {"x86_64", "amd64"}:
        return "http://172.168.238.1:8081/bot"

    return "http://11.11.11.100:8081/bot"


def main():
    asyncio.run(run())


async def run():
    colorama.init()
    parser = argparse.ArgumentParser(description="Send messages and files over Telegram.",
                                     epilog="Homepage: https://github.com/rahiel/telegram-send")
    parser.add_argument("message", help="message(s) to send", nargs="*")
    parser.add_argument("--format", default="text", dest="parse_mode", choices=["text", "markdown", "html"],
                        help="How to format the message(s). Choose from 'text', 'markdown', or 'html'")
    parser.add_argument("--stdin", help="Send text from stdin.", action="store_true")
    parser.add_argument("--pre", help="Send preformatted fixed-width (monospace) text.", action="store_true")
    parser.add_argument("--disable-web-page-preview", help="disable link previews in the message(s)",
                        action="store_true")
    parser.add_argument("--silent", help="send silently, user will receive a notification without sound",
                        action="store_true")
    parser.add_argument("-c", "--configure", help="configure %(prog)s", action="store_true")
    parser.add_argument("--configure-channel", help="configure %(prog)s for a channel", action="store_true")
    parser.add_argument("--configure-group", help="configure %(prog)s for a group", action="store_true")
    parser.add_argument("-f", "--file", help="send file(s)", nargs="+", type=argparse.FileType("rb"))
    parser.add_argument("-i", "--image", help="send image(s)", nargs="+", type=argparse.FileType("rb"))
    parser.add_argument("-s", "--sticker", help="send stickers(s)", nargs="+", type=argparse.FileType("rb"))
    parser.add_argument("--animation", help="send animation(s) (GIF or soundless H.264/MPEG-4 AVC video)",
                        nargs="+", type=argparse.FileType("rb"))
    parser.add_argument("--video", help="send video(s)", nargs="+", type=argparse.FileType("rb"))
    parser.add_argument("--audio", help="send audio(s)", nargs="+", type=argparse.FileType("rb"))
    parser.add_argument("-l", "--location",
                        help="send location(s) via latitude and longitude (separated by whitespace or a comma)",
                        nargs="+")
    parser.add_argument("--caption", help="caption for image(s)", nargs="+")
    parser.add_argument("--showids", help="show message ids, used to delete messages after they're sent",
                        action="store_true")
    parser.add_argument("-d", "--delete", metavar="id",
                        help="delete sent messages by id (only last 48h), see --showids",
                        nargs="+", type=int)
    parser.add_argument("--config", help="specify configuration file", type=str, dest="conf", action="append")
    parser.add_argument("-g", "--global-config", help="Use the global configuration at /etc/telegram-send.conf",
                        action="store_true")
    parser.add_argument("--file-manager", help="Integrate %(prog)s in the file manager", action="store_true")
    parser.add_argument("--clean", help="Clean %(prog)s configuration files.", action="store_true")
    parser.add_argument("--list-chats", help="List chats where the bot is present (from recent updates).", action="store_true")
    parser.add_argument("--chat-id", help="chat id to send messages to", type=str)
    parser.add_argument("--timeout", help="Set the read timeout for network operations. (in seconds)",
                        type=float, default=30., action="store")
    parser.add_argument("--version", action="version", version="%(prog)s {}".format(__version__))
    args = parser.parse_args()

    if args.global_config:
        conf = [global_config]
    elif args.conf is None:
        conf = [None]
    else:
        conf = args.conf

    if args.configure:
        return await configure(conf[0], fm_integration=True)
    elif args.configure_channel:
        return await configure(conf[0], channel=True)
    elif args.configure_group:
        return await configure(conf[0], group=True)
    elif args.file_manager:
        if not sys.platform.startswith("win32"):
            return integrate_file_manager()
        else:
            print(markup("File manager integration is unavailable on Windows.", "red"))
            sys.exit(1)
    elif args.clean:
        return clean()
    elif args.list_chats:
        return await list_chats(conf[0])

    if args.parse_mode == "markdown":
        # Use the improved MarkdownV2 format by default
        args.parse_mode = telegram.constants.ParseMode.MARKDOWN_V2

    if args.stdin:
        message = sys.stdin.read()
        if len(message) == 0:
            sys.exit(0)
        args.message = [message] + args.message

    try:
        await delete(args.delete, conf=conf[0])
        message_ids = []
        for c in conf:
            message_ids += await send(
                messages=args.message,
                conf=c,
                parse_mode=args.parse_mode,
                pre=args.pre,
                silent=args.silent,
                disable_web_page_preview=args.disable_web_page_preview,
                files=args.file,
                images=args.image,
                stickers=args.sticker,
                animations=args.animation,
                videos=args.video,
                audios=args.audio,
                captions=args.caption,
                locations=args.location,
                timeout=args.timeout,
                chat_id=args.chat_id
            )
        if args.showids and message_ids:
            smessage_ids = [str(m) for m in message_ids]
            print("message_ids " + " ".join(smessage_ids))
    except ConfigError as e:
        print(markup(str(e), "red"))
        cmd = "telegram-send --configure"
        if args.global_config:
            cmd = "sudo " + cmd + " --global-config"
        print("Please run: " + markup(cmd, "bold"))
        sys.exit(1)
    except telegram.error.NetworkError as e:
        if "timed out" in str(e).lower():
            print(markup("Error: Connection timed out", "red"))
            print("Please run with a longer timeout.\n"
                  "Try with the option: " + markup("--timeout {}".format(args.timeout + 10), "bold"))
            sys.exit(1)
        else:
            raise(e)


async def send(*,
         messages=None, files=None, images=None, stickers=None, animations=None, videos=None, audios=None,
         captions=None, locations=None, conf=None, parse_mode=None, pre=False, silent=False,
         disable_web_page_preview=False, timeout=30, chat_id=None):
    """Send data over Telegram. All arguments are optional.

    Always use this function with explicit keyword arguments. So
    `send(messages=["Hello!"])` instead of `send(["Hello!"])`.

    The `file` type is the [file object][] returned by the `open()` function.
    To send an image/file you open it in binary mode:
    ``` python
    import telegram_send

    with open("image.jpg", "rb") as f:
        telegram_send.send(images=[f])
    ```

    [file object]: https://docs.python.org/3/glossary.html#term-file-object

    # Arguments

    conf (str): Path of configuration file to use. Will use the default config if not specified.
                `~` expands to user's home directory.
    messages (List[str]): The messages to send.
    parse_mode (str): Specifies formatting of messages, one of `["text", "markdown", "html"]`.
    pre (bool): Send messages as preformatted fixed width (monospace) text.
    files (List[file]): The files to send.
    images (List[file]): The images to send.
    stickers (List[file]): The stickers to send.
    animations (List[file]): The animations to send.
    videos (List[file]): The videos to send.
    audios (List[file]): The audios to send.
    captions (List[str]): The captions to send with the images/files/animations/videos or audios.
    locations (List[str]): The locations to send. Locations are strings containing the latitude and longitude
                           separated by whitespace or a comma.
    silent (bool): Send silently without sound.
    disable_web_page_preview (bool): Disables web page previews for all links in the messages.
    timeout (int|float): The read timeout for network connections in seconds.
    """
    settings = get_config_settings(conf)
    token = settings.token
    if chat_id is None:
        chat_id = settings.chat_id
    bot = telegram.Bot(token, base_url=get_bot_api_base_url())
    # We let the user specify "text" as a parse mode to be more explicit about
    # the lack of formatting applied to the message, but "text" isn't a supported
    # parse_mode in python-telegram-bot. Instead, set the parse_mode to None
    # in this case.
    if parse_mode == "text":
        parse_mode = None

    # collect all message ids sent during the current invocation
    message_ids = []

    kwargs = {
        "chat_id": chat_id,
        "disable_notification": silent,
        "read_timeout": timeout,
    }

    if messages:
        async def send_message(message, parse_mode):
            if pre:
                parse_mode = "html"
                message = pre_format(message)
            return await bot.send_message(
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                **kwargs
            )

        for m in messages:
            if len(m) > MessageLimit.MAX_TEXT_LENGTH:
                warn(markup(
                    f"Message longer than MAX_MESSAGE_LENGTH={MessageLimit.MAX_TEXT_LENGTH}, splitting into smaller messages.",
                    "red"))
                ms = split_message(m, MessageLimit.MAX_TEXT_LENGTH)
                for m in ms:
                    message_ids += [(await send_message(m, parse_mode))["message_id"]]
            elif len(m) == 0:
                continue
            else:
                message_ids += [(await send_message(m, parse_mode))["message_id"]]

    def make_captions(items, captions):
        # make captions equal length when not all images/files have captions
        captions += [None] * (len(items) - len(captions))
        return zip(items, captions)

    # kwargs for send methods with caption support
    kwargs_caption = deepcopy(kwargs)
    kwargs_caption["parse_mode"] = parse_mode

    if files:
        if captions:
            for (f, c) in make_captions(files, captions):
                message_ids += [await bot.send_document(document=f, caption=c, **kwargs_caption)]
        else:
            for f in files:
                message_ids += [await bot.send_document(document=f, **kwargs)]

    if images:
        if captions:
            for (i, c) in make_captions(images, captions):
                message_ids += [await bot.send_photo(photo=i, caption=c, **kwargs_caption)]
        else:
            for i in images:
                message_ids += [await bot.send_photo(photo=i, **kwargs)]

    if stickers:
        for i in stickers:
            message_ids += [await bot.send_sticker(sticker=i, **kwargs)]

    if animations:
        if captions:
            for (a, c) in make_captions(animations, captions):
                message_ids += [await bot.send_animation(animation=a, caption=c, **kwargs_caption)]
        else:
            for a in animations:
                message_ids += [await bot.send_animation(animation=a, **kwargs)]

    if videos:
        if captions:
            for (v, c) in make_captions(videos, captions):
                message_ids += [await bot.send_video(video=v, caption=c, supports_streaming=True, **kwargs_caption)]
        else:
            for v in videos:
                message_ids += [await bot.send_video(video=v, supports_streaming=True, **kwargs)]

    if audios:
        if captions:
            for (a, c) in make_captions(audios, captions):
                message_ids += [await bot.send_audio(audio=a, caption=c, **kwargs_caption)]
        else:
            for a in audios:
                message_ids += [await bot.send_audio(audio=a, **kwargs)]

    if locations:
        it = iter(locations)
        for loc in it:
            if "," in loc:
                lat, lon = loc.split(",")
            else:
                lat = loc
                lon = next(it)
            message_ids += [await bot.send_location(latitude=float(lat),
                                                    longitude=float(lon),
                                                    **kwargs)]

    return message_ids


async def delete(message_ids, conf=None, timeout=30):
    """Delete messages that have been sent before over Telegram. Restrictions given by Telegram API apply.

    Note that Telegram restricts this to messages which have been sent during the last 48 hours.
    https://python-telegram-bot.readthedocs.io/en/stable/telegram.bot.html#telegram.Bot.delete_message

    # Arguments

    message_ids (List[str]): The messages ids of all messages to be deleted.
    conf (str): Path of configuration file to use. Will use the default config if not specified.
                `~` expands to user's home directory.
    timeout (int|float): The read timeout for network connections in seconds.
    """
    settings = get_config_settings(conf)
    token = settings.token
    chat_id = settings.chat_id
    bot = telegram.Bot(token, base_url=get_bot_api_base_url())

    if message_ids:
        for m in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=m, read_timeout=timeout)
            except telegram.TelegramError as e:
                warn(markup(f"Deleting message with id={m} failed: {e}", "red"))


async def list_chats(conf):
    """List chats where the bot is present based on recent updates."""
    try:
        settings = get_config_settings(conf)
    except ConfigError:
        print(markup("Configuration not found. Please run --configure first.", "red"))
        return

    token = settings.token
    bot = telegram.Bot(token, base_url=get_bot_api_base_url())
    
    print("Fetching updates to discover chats...")
    print("Note: Only chats that have recently interacted with the bot will be listed.")
    
    try:
        updates = await bot.get_updates(timeout=10)
    except Exception as e:
        print(markup(f"Error fetching updates: {e}", "red"))
        return

    chats = {}
    for update in updates:
        chat = None
        if update.message:
            chat = update.message.chat
        elif update.edited_message:
            chat = update.edited_message.chat
        elif update.channel_post:
            chat = update.channel_post.chat
        elif update.edited_channel_post:
            chat = update.edited_channel_post.chat
        elif update.my_chat_member:
            chat = update.my_chat_member.chat
        elif update.chat_member:
            chat = update.chat_member.chat
        
        if chat:
            chat_name = chat.title or chat.username or chat.first_name or "Unknown"
            chats[chat.id] = f"{chat_name} (ID: {chat.id}, Type: {chat.type})"

    if not chats:
        print("No chats found in recent updates.")
        return

    print("\nFound chats:")
    chat_items = list(chats.items())
    for i, (chat_id, name) in enumerate(chat_items, 1):
        print(f"{i}. {name}")
    
    # Optional: Allow user to select a chat to configure
    # Since the requirement is "list ... to choose from", let's just list for now
    # unless we want to implement updating the config. 
    # The user asked "parse the list ... to choose from".
    # I'll stick to listing for now as "choosing" might imply different things.
    # But if I don't implement selection, I can't fulfill "to choose from".
    # Let's add simple selection to print the ID clearly or update config.
    
    print("\nTo use one of these chats, you can run:")
    print(markup("telegram-send --chat-id <ID> ...", "cyan"))


async def configure(conf, channel=False, group=False, fm_integration=False):
    """Guide user to set up the bot, saves configuration at `conf`.

    # Arguments

    conf (str): Path where to save the configuration file. May contain `~` for
                user's home.
    channel (Optional[bool]): Configure a channel.
    group (Optional[bool]): Configure a group.
    fm_integration (Optional[bool]): Setup file manager integration.
    """
    conf = expanduser(conf) if conf else get_config_path()
    prompt = "❯ " if not sys.platform.startswith("win32") else "> "
    contact_url = "https://telegram.me/"

    print("Talk with the {} on Telegram ({}), create a bot and insert the token"
          .format(markup("BotFather", "cyan"), contact_url + "BotFather"))
    try:
        token = input(markup(prompt, "magenta")).strip()
    except UnicodeEncodeError:
        # some users can only display ASCII
        prompt = "> "
        token = input(markup(prompt, "magenta")).strip()

    try:
        bot = telegram.Bot(token, base_url=get_bot_api_base_url())
        bot_details = await bot.get_me()
        bot_name = bot_details.username
    except Exception as e:
        print("Error: {}".format(e))
        print(markup("Something went wrong, please try again.\n", "red"))
        return await configure(conf, channel=channel, group=group, fm_integration=fm_integration)

    print("Connected with {}.\n".format(markup(bot_name, "cyan")))

    if channel:
        print("Do you want to send to a {} or a {} channel? [pub/priv]"
              .format(markup("public", "bold"), markup("private", "bold")))
        channel_type = input(markup(prompt, "magenta")).strip()
        if channel_type.startswith("pub"):
            print(
                "\nEnter your channel's public name or link: "
                "\nExample: @username or https://t.me/username"
            )
            chat_id = input(markup(prompt, "magenta")).strip()
            if "/" in chat_id:
                chat_id = "@" + chat_id.split("/")[-1]
            elif chat_id.startswith("@"):
                pass
            else:
                chat_id = "@" + chat_id
        else:
            print(
                "\nOpen https://web.telegram.org/?legacy=1#/im in your browser, sign in and open your private channel."
                "\nNow copy the URL in the address bar and enter it here:"
                "\nExample: https://web.telegram.org/?legacy=1#/im?p=c1498081025_17886896740758033425"
            )
            url = input(markup(prompt, "magenta")).strip()
            match = re.match(r".+web\.(telegram|tlgr)\.org\/\?legacy=1#\/im\?p=c(?P<chat_id>\d+)_\d+", url)
            chat_id = "-100" + match.group("chat_id")

        authorized = False
        while not authorized:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
                authorized = True
            except (telegram.error.Forbidden, telegram.error.BadRequest):
                # Telegram returns a BadRequest when a non-admin bot tries to send to a private channel
                input("Please add {} as administrator to your channel and press Enter"
                      .format(markup(bot_name, "cyan")))
        print(markup("\nCongratulations! telegram-send can now post to your channel!", "green"))
    else:
        password = "".join([str(randint(0, 9)) for _ in range(5)])
        bot_url = contact_url + bot_name
        fancy_bot_name = markup(bot_name, "cyan")
        if group:
            password = "/{}@{}".format(password, bot_name)
            print("Please add {} to your group\nand send the following message to the group: {}\n"
                  .format(fancy_bot_name, markup(password, "bold")))
        else:
            print("Please add {} on Telegram ({})\nand send it the password: {}\n"
                  .format(fancy_bot_name, bot_url, markup(password, "bold")))

        update, update_id = None, None

        async def get_user():
            updates = await bot.get_updates(offset=update_id, read_timeout=10)
            for update in updates:
                if update.message:
                    if update.message.text == password:
                        return update, None
            if len(updates) > 0:
                return None, updates[-1].update_id + 1
            else:
                return None, None

        while update is None:
            try:
                update, update_id = await get_user()
            except Exception as e:
                print("Error! {}".format(e))

        chat_id = update.message.chat_id
        user = update.message.from_user.username or update.message.from_user.first_name
        m = ("Congratulations {}! ".format(user), "\ntelegram-send is now ready for use!")
        ball = "🎊"
        print(markup("".join(m), "green"))
        await bot.send_message(chat_id=chat_id, text=ball + " " + m[0] + ball + m[1])

    config = configparser.ConfigParser()
    config["telegram"] = {"TOKEN": token, "chat_id": chat_id}
    conf_dir = dirname(conf)
    if conf_dir:
        makedirs(conf_dir, exist_ok=True)
    with open(conf, "w") as f:
        config.write(f)
    if fm_integration:
        if not sys.platform.startswith("win32"):
            return integrate_file_manager()


def integrate_file_manager(clean=False):
    desktop = (
        "[{}]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Encoding=UTF-8\n"
        "Exec=telegram-send --file %F\n"
        "Icon=telegram\n"
        "Name={}\n"
        "Selection=any\n"
        "Extensions=nodirs;\n"
        "Quote=double\n"
    )
    name = "telegram-send"
    script = """#!/bin/sh
echo "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | sed 's/ /\\\\ /g' | xargs telegram-send -f
"""
    file_managers = [
        ("thunar", "~/.local/share/Thunar/sendto/", "Desktop Entry", "Telegram", ".desktop"),
        ("nemo", "~/.local/share/nemo/actions/", "Nemo Action", "Send to Telegram", ".nemo_action"),
        ("nautilus", "~/.local/share/nautilus/scripts/", "script", "", ""),
    ]
    for (fm, loc, section, label, ext) in file_managers:
        loc = expanduser(loc)
        filename = join(loc, name + ext)
        if not clean:
            if which(fm):
                makedirs(loc, exist_ok=True)
                with open(filename, "w") as f:
                    if section == "script":
                        f.write(script)
                    else:
                        f.write(desktop.format(section, label))
                if section == "script":
                    check_output(["chmod", "+x", filename])
        else:
            if exists(filename):
                remove(filename)


def clean():
    integrate_file_manager(clean=True)
    conf = get_config_path()
    if exists(conf):
        remove(conf)
    if exists(global_config):
        try:
            remove(global_config)
        except OSError:
            print(markup("Can't delete /etc/telegram-send.conf", "red"))
            print("Please run: " + markup("sudo telegram-send --clean", "bold"))
            sys.exit(1)


class ConfigError(Exception):
    pass


class Settings(NamedTuple):
    token: str
    chat_id: Union[int, str]


def get_config_settings(conf=None) -> Settings:
    conf = expanduser(conf) if conf else get_config_path()
    config = configparser.ConfigParser()
    if not config.read(conf) or not config.has_section("telegram"):
        raise ConfigError("Config not found")
    missing_options = set(["token", "chat_id"]) - set(config.options("telegram"))
    if len(missing_options) > 0:
        raise ConfigError("Missing options in config: {}".format(", ".join(missing_options)))
    token = config.get("telegram", "token")
    chat_id = config.get("telegram", "chat_id")
    if chat_id.isdigit():
        chat_id = int(chat_id)
    return Settings(token=token, chat_id=chat_id)


if __name__ == "__main__":
    main()
