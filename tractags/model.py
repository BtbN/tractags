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
from trac.util.datefmt import utc
from trac.util.text import to_unicode

from tractags.compat import to_datetime, to_utimestamp
from tractags.util import split_into_tags


# Public functions (not yet)


# Utility functions

def delete_tags(env, resource, tags=None, db=None):
    """Delete tags and tag changes for a Trac resource."""
    do_commit = db is None or False
    db = _get_db(env, db)
    cursor = db.cursor()
    args = [resource.realm, to_unicode(resource.id)]
    sql = ''
    if tags:
        args += list(tags)
        sql += " AND tags.tag IN (%s)" % ','.join(['%s' for tag in tags])
    cursor.execute("""
        DELETE FROM tags
         WHERE tagspace=%%s
           AND name=%%s%s
    """ % sql, args)
    if do_commit:
        # Call outside of another db transaction means resource destruction,
        # so purge change records too.
        cursor.execute("""
            DELETE FROM tags_change
             WHERE tagspace=%s
               AND name=%s
        """, (resource.realm, to_unicode(resource.id)))
        db.commit()

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
            for row in cursor]

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

def tag_resource(env, resource, old_id=None, author='anonymous', tags=[],
                 log=False):
    """Save tags and tag changes for a Trac resource.

    This function combines delete, reparent and set actions now, but it could
    possibly be still a bit more efficient.
    """
    db = _get_db(env)
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
        # Calculate effective tag changes.
        old_tags = set(resource_tags(env, resource, db=db))
        tags = set(tags)
        remove = old_tags - tags
        if remove:
            if tags:
                delete_tags(env, resource, remove, db=db)
            else:
                # Delete all resource's tags - simplified transaction.
                delete_tags(env, resource, db=db)
        add = tags - old_tags
        if add:
            cursor.executemany("""
                INSERT INTO tags
                       (tagspace, name, tag)
                VALUES (%s,%s,%s)
            """, [(resource.realm, to_unicode(resource.id), tag)
                  for tag in add])
        if log:
            cursor.execute("""
                INSERT INTO tags_change
                       (tagspace, name, time, author, oldtags, newtags)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (resource.realm, to_unicode(resource.id),
                  to_utimestamp(datetime.now(utc)), author,
                  u' '.join(sorted(map(to_unicode, old_tags))),
                  u' '.join(sorted(map(to_unicode, tags))),))
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

def resource_tags(env, resource, db=None, when=None):
    """Return all tags for a Trac resource by realm and ID."""
    db = _get_db(env, db)
    cursor = db.cursor()
    id = to_unicode(resource.id)
    if when is None:
        cursor.execute("""
            SELECT tag
              FROM tags
             WHERE tagspace=%s
               AND name=%s
        """, (resource.realm, id))
        for row in cursor:
            yield row[0]
    else:
        if isinstance(when, datetime):
            when = to_utimestamp(when)
        cursor.execute("SELECT newtags FROM tags_change "
                       "WHERE tagspace=%s AND name=%s AND time<=%s "
                       "ORDER BY time DESC LIMIT 1",
                       (resource.realm, id, when))
        row = cursor.fetchone()
        if row and row[0]:
            for tag in split_into_tags(row[0]):
                yield tag

# Internal functions

def _get_db(env, db=None):
    return db or env.get_db_cnx()
