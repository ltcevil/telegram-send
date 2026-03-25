#!/usr/bin/env python3
import re
from setuptools import setup

with open("telegram_send/version.py") as f:
    __version__ = re.search('"(.+)"', f.read()).group(1)

with open("README.md") as f:
    long_description = f.read()

setup(
    name="telegram-send",
    version=__version__,
    description="Send messages and files over Telegram from the command-line.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jarina/telegram-send",
    license="GPLv3+",

    python_requires=">=3.7",    # also update classifier below
    packages=["telegram_send"],
    install_requires=[
        "python-telegram-bot>=22.7",
        "colorama>=0.4.6",
        "appdirs>=1.4.4",
    ],
    entry_points={"console_scripts": ["telegram-send=telegram_send.telegram_send:main"]},

    author="Jarina Bot",
    author_email="jarina@vagyok.hu",
    classifiers=[
        "Development Status :: 6 - Mature",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3.12",
        "Topic :: Communications :: Chat",
        "Topic :: Utilities"
    ],
    keywords="telegram send message file"
)
