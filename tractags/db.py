#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2012 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from trac.core import Component, TracError, implements
from trac.db.api import DatabaseManager
from trac.env import IEnvironmentSetupParticipant

from tractags import db_default
from tractags.api import _
from tractags.ticket import TicketTagProvider


class TagSetup(Component):
    """[main] Plugin setup and upgrade handler."""

    implements(IEnvironmentSetupParticipant)

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        pass

    def environment_needs_upgrade(self, db=None):
        schema_ver = self.get_schema_version()
        if schema_ver == db_default.schema_version:
            return False
        elif schema_ver > db_default.schema_version:
            raise TracError(_("A newer plugin version has been installed "
                              "before, but downgrading is unsupported."))
        self.log.info("TracTags database schema version is %d, should be %d",
                      schema_ver, db_default.schema_version)
        return True

    def upgrade_environment(self, db=None):
        """Each schema version should have its own upgrade module, named
        upgrades/dbN.py, where 'N' is the version number (int).
        """
        db_mgr = DatabaseManager(self.env)
        schema_ver = self.get_schema_version()

        with self.env.db_transaction as db:
            # Is this a new installation?
            if not schema_ver:
                # Perform a single-step install: Create plugin schema and
                # insert default data into the database.
                connector = db_mgr.get_connector()[0]
                for table in db_default.schema:
                    for stmt in connector.to_sql(table):
                        db(stmt)
                for table, cols, vals in db_default.get_data(db):
                    db.executemany("INSERT INTO %s (%s) VALUES (%s)"
                                   % (table, ','.join(cols),
                                      ','.join(['%s'] * len(cols))), vals)
            else:
                # Perform incremental upgrades.
                for i in range(schema_ver + 1, db_default.schema_version + 1):
                    name = 'db%i' % i
                    try:
                        upgrades = __import__('tractags.upgrades', globals(),
                                              locals(), [name])
                        script = getattr(upgrades, name)
                    except AttributeError:
                        raise TracError(_("No upgrade module for version "
                                          "%(num)i (%(version)s.py)", num=i,
                                          version=name))
                    cursor = db.cursor()
                    script.do_upgrade(self.env, i, cursor)
            db("""UPDATE system SET value=%s
                  WHERE name='tags_version'
                  """, (db_default.schema_version,))
            self.log.info("Upgraded TracTags db schema from version %d to %d",
                          schema_ver, db_default.schema_version)

            TicketTagProvider(self.env)._fetch_tkt_tags()
            self.log.info("Synchronized ticket attributes to tags table")

    def get_db_version(self):
        for version, in self.env.db_query("""
                SELECT value FROM system
                WHERE name='tags_version'
                """):
            return int(version)

    def get_schema_version(self):
        """Return the current schema version for this plugin."""
        version = self.get_db_version()
        if not version or version < 2:
            # Care for pre-tags-0.7 installations.
            tables = self._get_tables()
            if 'tags' in tables:
                self.env.log.debug("TracTags needs to register schema version")
                return 2
            if 'wiki_namespace' in tables:
                self.env.log.debug("TracTags needs to migrate old data")
                return 1
            # This is a new installation.
            return 0
        # The expected outcome for any up-to-date installation.
        return version or 0

    # Internal methods

    def _get_tables(self):
        """Code from TracMigratePlugin by Jun Omae (see tracmigrate.admin)."""
        dburi = self.config.get('trac', 'database')
        if dburi.startswith('sqlite:'):
            sql = """
                SELECT name FROM sqlite_master
                WHERE type='table' AND NOT name='sqlite_sequence'
                """
        elif dburi.startswith('postgres:'):
            sql = """
                SELECT tablename FROM pg_tables
                WHERE schemaname = ANY (current_schemas(false))
                """
        elif dburi.startswith('mysql:'):
            sql = "SHOW TABLES"
        else:
            raise TracError('Unsupported database type "%s"'
                            % dburi.split(':')[0])
        with self.env.db_transaction as db:
            cursor = db.cursor()
            cursor.execute(sql)
            return sorted(name for name, in cursor.fetchall())
