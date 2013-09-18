#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2012,2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from trac.resource import Resource
from trac.wiki.web_ui import WikiModule
from trac.util.compat import groupby, set


# Public functions (not yet)


# Utility functions

def tag_frequency(env, realms, db=None):
    """Return tags and numbers of their occurrence."""
    db = _get_db(env, db)
    cursor = db.cursor()
    filter = ' OR '.join(["tagspace='%s'" % r for r in realms])
    if 'wiki' in realms and \
            env.config.getbool('tags', 'query_exclude_wiki_templates'):
        like_templates = ''.join(
            ["'", db.like_escape(WikiModule.PAGE_TEMPLATES_PREFIX), "%%'"])
        filter = '(%s) AND (%s)' % (filter,
                                    ' '.join(['name NOT',
                                              db.like() % like_templates]))
    cursor.execute("""
        SELECT tag,count(tag)
          FROM tags%s
         GROUP BY tag
    """ % (filter and ' WHERE %s' % filter or ''))
    for row in cursor:
        yield (row[0], row[1])

def tag_resource(env, realm, id, new_id=None, tags=None, db=None):
    """Change recorded tags for a Trac resource.

    This function combines delete, reparent and set actions now, but it could
    possibly be still a bit more efficient.
    """
    db = _get_db(env, db)
    cursor = db.cursor()

    if new_id:
        cursor.execute("""
            UPDATE tags
               SET name=%s
             WHERE tagspace=%s
               AND name=%s
        """, (new_id, realm, id))
    else:
        # DEVEL: Work out the difference instead of stupid delete/re-insertion.
        cursor.execute("""
            DELETE FROM tags
             WHERE tagspace=%s
               AND name=%s
        """, (realm, id))
    if tags:
        cursor.executemany("""
            INSERT INTO tags
                   (tagspace, name, tag)
            VALUES (%s,%s,%s)
        """, [(realm, id, tag) for tag in tags])
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

def resource_tags(env, realm, id, db=None):
    """Return all tags for a Trac resource by realm and ID."""
    db = _get_db(env, db)
    cursor = db.cursor()

    cursor.execute("""
        SELECT tag
          FROM tags
         WHERE tagspace=%s
           AND name=%s
    """, (realm, id))
    for row in cursor:
        yield row[0]

# Internal functions

def _get_db(env, db=None):
    return db or env.get_db_cnx()
