#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2012,2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from datetime import datetime

from trac.resource import Resource
from trac.util.compat import groupby, set
from trac.util.datefmt import to_datetime, utc
from trac.util.text import to_unicode

from tractags.compat import to_datetime, to_utimestamp


# Public functions (not yet)


# Utility functions

def tag_changes(env, resource):
    """Return tag history for a Trac resource."""
    db = _get_db(env)
    cursor = db.cursor()
    cursor.execute("""
        SELECT time,author,oldtags,newtags
          FROM tags_change
         WHERE tagspace=%s
           AND name=%s
         ORDER BY time DESC
    """, (resource.realm, to_unicode(resource.id)))
    return [(to_datetime(row[0]), row[1], row[2], row[3])
            for row in cursor.fetchall()]

def tag_frequency(env, realm, filter=None, db=None):
    """Return tags and numbers of their occurrence."""
    if filter:
        sql = ''.join([" AND %s" % f for f in filter])
    db = _get_db(env, db)
    cursor = db.cursor()
    cursor.execute("""
        SELECT tag,count(tag)
          FROM tags
         WHERE tagspace=%%s%s
         GROUP BY tag
    """ % (filter and sql or ''), (realm,))
    for row in cursor:
        yield (row[0], row[1])

def tag_resource(env, resource, old_id=None, author='anonymous', tags=None,
                 log=False, db=None):
    """Save tags and tag changes for a Trac resource.

    This function combines delete, reparent and set actions now, but it could
    possibly be still a bit more efficient.
    """
    db = _get_db(env, db)
    cursor = db.cursor()

    if old_id:
        cursor.execute("""
            UPDATE tags
               SET name=%s
             WHERE tagspace=%s
               AND name=%s
        """, (to_unicode(resource.id), resource.realm, to_unicode(old_id)))
        cursor.execute("""
            UPDATE tags_change
               SET name=%s
             WHERE tagspace=%s
               AND name=%s
        """, (to_unicode(resource.id), resource.realm, to_unicode(old_id)))
        
    else:
        if log:
            old_tags = u' '.join(sorted(map(to_unicode,
                                            resource_tags(env, resource,
                                                          db=db))))
        # DEVEL: Work out the difference instead of stupid delete/re-insertion.
        cursor.execute("""
            DELETE FROM tags
             WHERE tagspace=%s
               AND name=%s
        """, (resource.realm, to_unicode(resource.id)))
    if tags:
        cursor.executemany("""
            INSERT INTO tags
                   (tagspace, name, tag)
            VALUES (%s,%s,%s)
        """, [(resource.realm, to_unicode(resource.id), tag) for tag in tags])
    if log and not old_id:
        cursor.execute("""
            INSERT INTO tags_change
                   (tagspace, name, time, author, oldtags, newtags)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (resource.realm, to_unicode(resource.id),
              to_utimestamp(datetime.now(utc)), author, old_tags,
              tags and u' '.join(sorted(map(to_unicode, tags))) or ''))
    db.commit()

def tagged_resources(env, perm_check, perm, realm, tags=None, filter=None,
                     db=None):
    """Return Trac resources including their associated tags.

    This is currently known to be a major performance hog.
    """
    db = _get_db(env, db)
    cursor = db.cursor()

    args = [realm]
    sql = """
        SELECT DISTINCT name
          FROM tags
         WHERE tagspace=%s"""
    if filter:
        sql += ''.join([" AND %s" % f for f in filter])
    if tags:
        sql += " AND tags.tag IN (%s)" % ','.join(['%s' for tag in tags])
        args += tags
    sql += " ORDER by name"
    cursor.execute(sql, args)

    # Inlined permission check for efficiency.
    resources = {}
    for name, in cursor:
        resource = Resource(realm, name)
        if perm_check(perm(resource), 'view'):
            resources[resource.id] = resource
    if not resources:
        return

    args = [realm] + resources.keys()
    # DEVEL: Is this going to be excruciatingly slow?
    #        The explicite resource ID list might even grow beyond some limit.
    sql = """
        SELECT DISTINCT name, tag
          FROM tags
         WHERE tagspace=%%s
           AND name IN (%s)
         ORDER BY name
    """ % ', '.join(['%s' for resource in resources])
    cursor.execute(sql, args)

    for name, tags in groupby(cursor, lambda row: row[0]):
        resource = resources[name]
        yield resource, set([tag[1] for tag in tags])

def resource_tags(env, resource, db=None):
    """Return all tags for a Trac resource by realm and ID."""
    db = _get_db(env, db)
    cursor = db.cursor()

    cursor.execute("""
        SELECT tag
          FROM tags
         WHERE tagspace=%s
           AND name=%s
    """, (resource.realm, to_unicode(resource.id)))
    for row in cursor:
        yield row[0]

# Internal functions

def _get_db(env, db=None):
    return db or env.get_db_cnx()
