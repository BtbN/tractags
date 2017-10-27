# -*- coding: utf-8 -*-
#
# Copyright (C) 2012-2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from trac.db import Table, Column, Index, DatabaseManager

schema = [
    Table('tags', key=('tagspace', 'name', 'tag'))[
        Column('tagspace'),
        Column('name'),
        Column('tag'),
        Index(['tagspace', 'name']),
        Index(['tagspace', 'tag']),
    ]
]


def do_upgrade(env, ver, cursor):
    """Move to new, tractags db schema."""

    connector = DatabaseManager(env).get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            cursor.execute(stmt)
    # Migrate ancient wiki tags table.
    cursor.execute("""
        INSERT INTO tags
               (tagspace, name, tag)
            SELECT 'wiki', name, namespace
              FROM wiki_namespace
        """)
    # Drop old table `wiki_namespace` (including index `wiki_namespace_idx`).
    cursor.execute("DROP TABLE wiki_namespace")
