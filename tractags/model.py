#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 Jun Omae <jun66j5@gmail.com>
# Copyright (C) 2012,2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from datetime import datetime
from itertools import groupby

from trac.resource import Resource
from trac.util.datefmt import to_datetime, to_utimestamp, utc
from trac.util.text import to_unicode

from tractags.util import split_into_tags


# Public functions (not yet)


# Utility functions

def delete_tags(env, resource, tags=None, purge=False):
    """Delete tags and tag changes for a Trac resource.

    :param purge: if `True`, delete the change history.
    """
    args = [resource.realm, to_unicode(resource.id)]
    sql = ''
    if tags:
        args += list(tags)
        sql += " AND tags.tag IN (%s)" % ','.join(['%s'] * len(tags))
    with env.db_transaction as db:
        db("""DELETE FROM tags
              WHERE tagspace=%%s AND name=%%s%s
              """ % sql, args)
        if purge:
            # Call outside of another db transaction means resource destruction,
            # so purge change records too.
            db("""DELETE FROM tags_change
                  WHERE tagspace=%s AND name=%s
                  """, (resource.realm, to_unicode(resource.id)))


def tag_changes(env, resource, start=None, stop=None):
    """Return tag history for one or all tagged Trac resources."""
    if resource:
        # Resource changelog events query.
        return [(to_datetime(row[0]), row[1], row[2], row[3])
                for row in env.db_query("""
                    SELECT time,author,oldtags,newtags FROM tags_change
                    WHERE tagspace=%s AND name=%s
                    ORDER BY time DESC
                    """, (resource.realm, to_unicode(resource.id)))]
    # Timeline events query.
    return [(to_datetime(row[0]), row[1], row[2], row[3], row[4], row[5])
            for row in env.db_query("""
                SELECT time,author,tagspace,name,oldtags,newtags
                FROM tags_change WHERE time>%s AND time<%s
                """, (to_utimestamp(start), to_utimestamp(stop)))]


def tag_frequency(env, realm, filter=None, db=None):
    """Return tags and numbers of their occurrence."""
    if filter:
        sql = ''.join(" AND %s" % f for f in filter)
    for row in env.db_query("""
            SELECT tag,count(tag) FROM tags
            WHERE tagspace=%%s%s GROUP BY tag
            """ % (filter and sql or ''), (realm,)):
        yield row[0], row[1]


def tag_resource(env, resource, old_id=None, author='anonymous', tags=None,
                 log=False, when=None):
    """Save tags and tag changes for a Trac resource.

    This function combines delete, reparent and set actions now, but it could
    possibly be still a bit more efficient.
    """
    tags = tags or []
    if when is None:
        when = datetime.now(utc)
    if isinstance(when, datetime):
        when = to_utimestamp(when)

    if old_id:
        with env.db_transaction as db:
            db("""
               UPDATE tags SET name=%s
               WHERE tagspace=%s AND name=%s
               """, (to_unicode(resource.id), resource.realm,
                     to_unicode(old_id)))
            db("""
               UPDATE tags_change SET name=%s
               WHERE tagspace=%s AND name=%s
               """, (to_unicode(resource.id), resource.realm,
                     to_unicode(old_id)))
    else:
        # Calculate effective tag changes.
        old_tags = set(resource_tags(env, resource))
        tags = set(tags)
        remove = old_tags - tags
        with env.db_transaction as db:
            if remove:
                if tags:
                    delete_tags(env, resource, remove)
                else:
                    # Delete all resource's tags - simplified transaction.
                    delete_tags(env, resource)
            add = tags - old_tags
            if add:
                db.executemany("""
                    INSERT INTO tags (tagspace, name, tag)
                    VALUES (%s,%s,%s)
                    """, [(resource.realm, to_unicode(resource.id), tag)
                          for tag in add])
            if log:
                db("""
                  INSERT INTO tags_change
                   (tagspace, name, time, author, oldtags, newtags)
                  VALUES (%s,%s,%s,%s,%s,%s)
                  """, (resource.realm, to_unicode(resource.id),
                        when, author,
                        u' '.join(sorted(map(to_unicode, old_tags))),
                        u' '.join(sorted(map(to_unicode, tags))),))


def tagged_resources(env, perm_check, perm, realm, tags=None, filter=None,
                     db=None):
    """Return Trac resources including their associated tags.

    This is currently known to be a major performance hog.
    """
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

    # Inline permission check for efficiency.
    resources = {}
    for name, in env.db_query(sql, args):
        resource = Resource(realm, name)
        if perm_check(perm(resource), 'view'):
            resources[resource.id] = resource
    if not resources:
        return

    # DEVEL: Is this going to be excruciatingly slow?
    #        The explicite resource ID list might even grow beyond some limit.
    for name, tags in groupby(env.db_query("""
            SELECT DISTINCT name, tag FROM tags
            WHERE tagspace=%%s AND name IN (%s)
            ORDER BY name
            """ % ', '.join(['%s'] * len(resources)),
            [realm] + resources.keys()), lambda row: row[0]):
        resource = resources[name]
        yield resource, set([tag[1] for tag in tags])


def resource_tags(env, resource, when=None):
    """Return all tags for a Trac resource by realm and ID."""
    id = to_unicode(resource.id)
    if when is None:
        for tag, in env.db_query("""
                SELECT tag FROM tags
                WHERE tagspace=%s AND name=%s
                """, (resource.realm, id)):
            yield tag
    else:
        if isinstance(when, datetime):
            when = to_utimestamp(when)
        for newtags, in env.db_query("""
                SELECT newtags FROM tags_change
                WHERE tagspace=%s AND name=%s AND time<=%s
                ORDER BY time DESC LIMIT 1
                """, (resource.realm, id, when)):
            for tag in split_into_tags(newtags):
                yield tag
