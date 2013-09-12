#!/bin/bash

source $HOME/python/virtenv/bin/activate
pushd $HOME/app-root/runtime/repo
python ./brewpoll.py

