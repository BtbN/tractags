# -*- coding: utf-8 -*-
#
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#


def do_upgrade(env, ver, cursor):
    """Register tractags db schema in `system` db table."""

    cursor.execute("""
        SELECT COUNT(*)
          FROM system
         WHERE name='tags_version'
    """)
    exists = cursor.fetchone()
    if not exists[0]:
        # Play safe for upgrades from tags<0.7, that had no version entry.
        cursor.execute("""
            INSERT INTO system
                   (name, value)
            VALUES ('tags_version', '2')
            """)
