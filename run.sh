#!/bin/zsh

pipenv run gunicorn app:app -k eventlet -w 1 --bind 127.0.0.1:5000
