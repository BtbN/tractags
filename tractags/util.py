# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2013,2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2014 Ryan J Ollos <ryan.j.ollos@gmail.com>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

from trac.test import Mock, MockPerm

from tractags.compat import partial

_TAG_SPLIT = re.compile('[,\s]+')


# DEVEL: This needs monitoring for possibly varying endpoint requirements.
MockReq = partial(Mock, args=dict(), authname='anonymous',
                  perm=MockPerm(), session=dict())


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

def query_realms(query, all_realms):
    realms = []
    for realm in all_realms:
        if re.search('(^|\W)realm:%s(\W|$)' % realm, query):
            realms.append(realm)
    return realms

def split_into_tags(text):
    """Split plain text into tags."""
    return set(filter(None, [tag.strip() for tag in _TAG_SPLIT.split(text)]))
