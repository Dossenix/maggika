#!/bin/bash
set -e

export PYTHONPATH="/home/container/.local/lib/python3.12/site-packages:${PYTHONPATH}"

/usr/local/bin/python -c "import discord, dotenv, aiohttp" 2>/dev/null || /usr/local/bin/python -m pip install --disable-pip-version-check --no-cache-dir --prefix .local -r requirements.txt
/usr/local/bin/python main.py
