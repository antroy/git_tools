#!/usr/bin/env bash

DIR=`dirname $0`
SCRIPT=$1
shift

if [ ! -d .pyenv ]
then
    python3 -m venv $DIR/.pyenv
    . $DIR/.pyenv/bin/activate

    if [ -f requirements.txt ]
    then
        pip install -r requirements.txt
    fi
else
    . $DIR/.pyenv/bin/activate
fi

python3 $SCRIPT $*
