# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

_TAG_SPLIT = re.compile('[,\s]+')


def split_into_tags(text):
    """Split plain text into tags."""
    return set([tag.strip() for tag in _TAG_SPLIT.split(text)
               if tag.strip()])


def get_db_exc(env):
    if hasattr(env, 'db_exc'):
        return env.db_exc
    database = env.config.get('trac', 'database')
    if database.startswith('sqlite:'):
        from trac.db.sqlite_backend import sqlite
        return sqlite
    if database.startswith('postgres:'):
        from trac.db.postgres_backend import psycopg
        return psycopg
    if database.startswith('mysql:'):
        from trac.db.mysql_backend import MySQLdb
        return MySQLdb
