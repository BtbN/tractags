# -*- coding: utf-8 -*-
#
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from trac.db import Table, Column, DatabaseManager

schema = [
    Table('tags_change', key=('tagspace', 'name', 'time'))[
        Column('tagspace'),
        Column('name'),
        Column('time', type='int64'),
        Column('author'),
        Column('oldtags'),
        Column('newtags'),
    ]
]


def do_upgrade(env, ver, cursor):
    """Add new table for tag change records."""

    connector = DatabaseManager(env).get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            cursor.execute(stmt)
