# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Odd Simon Simonsen <oddsimons@gmail.com>
# Copyright (C) 2012 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.db import Table, Column, Index
from trac.db.api import DatabaseManager
from trac.test import EnvironmentStub

from tractags import db_default
from tractags.db import TagSetup


class TagSetupTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*'])
        self.env.path = tempfile.mkdtemp()
        self.db_mgr = DatabaseManager(self.env)

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _get_cursor_description(self, cursor):
        return cursor.cursor.description

    def _revert_tractags_schema_init(self):
        with self.env.db_transaction as db:
            db("DROP TABLE IF EXISTS tags")
            db("DROP TABLE IF EXISTS tags_change")
            db("DELETE FROM system WHERE name='tags_version'")
            db("DELETE FROM permission WHERE action %s" % db.like(),
               ('TAGS_%',))

    def get_db_version(self):
        for version, in self.env.db_query("""
                SELECT value FROM system
                WHERE name='tags_version'
                """):
            return int(version)

    # Tests

    def test_new_install(self):
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for clean install testing.
        self._revert_tractags_schema_init()
        self.assertEquals(0, setup.get_schema_version())
        self.assertTrue(setup.environment_needs_upgrade())

        setup.upgrade_environment()
        self.assertFalse(setup.environment_needs_upgrade())
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM tags")
            cols = [col[0] for col in self._get_cursor_description(cursor)]
            self.assertEquals([], cursor.fetchall())
            self.assertEquals(['tagspace', 'name', 'tag'], cols)
        self.assertEquals(db_default.schema_version, self.get_db_version())

    def test_upgrade_schema_v1(self):
        # Ancient, unversioned schema - wiki only.
        schema = [
            Table('wiki_namespace')[
                Column('name'),
                Column('namespace'),
                Index(['name', 'namespace']),
            ]
        ]
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for clean install testing.
        self._revert_tractags_schema_init()

        connector = self.db_mgr.get_connector()[0]
        with self.env.db_transaction as db:
            for table in schema:
                for stmt in connector.to_sql(table):
                    db(stmt)
            # Populate table with migration test data.
            db("""INSERT INTO wiki_namespace (name, namespace)
                  VALUES ('WikiStart', 'tag')""")

        tags = self.env.db_query("SELECT * FROM wiki_namespace")
        self.assertEquals([('WikiStart', 'tag')], tags)
        self.assertEquals(1, setup.get_schema_version())
        self.assertTrue(setup.environment_needs_upgrade())

        setup.upgrade_environment()
        self.assertFalse(setup.environment_needs_upgrade())
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM tags")
            tags = cursor.fetchall()
            cols = [col[0] for col in self._get_cursor_description(cursor)]
            # Db content should be migrated.
            self.assertEquals([('wiki', 'WikiStart', 'tag')], tags)
            self.assertEquals(['tagspace', 'name', 'tag'], cols)
            self.assertEquals(db_default.schema_version, self.get_db_version())

    def test_upgrade_schema_v2(self):
        # Just register a current, but unversioned schema.
        schema = [
            Table('tags', key=('tagspace', 'name', 'tag'))[
                Column('tagspace'),
                Column('name'),
                Column('tag'),
                Index(['tagspace', 'name']),
                Index(['tagspace', 'tag']),
            ]
        ]
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for clean install testing.
        self._revert_tractags_schema_init()

        connector = self.db_mgr.get_connector()[0]
        with self.env.db_transaction as db:
            for table in schema:
                for stmt in connector.to_sql(table):
                    db(stmt)
            # Populate table with test data.
            db("""INSERT INTO tags (tagspace, name, tag)
                  VALUES ('wiki', 'WikiStart', 'tag')""")

        tags = self.env.db_query("SELECT * FROM tags")
        self.assertEquals([('wiki', 'WikiStart', 'tag')], tags)
        self.assertEquals(2, setup.get_schema_version())
        self.assertTrue(setup.environment_needs_upgrade())

        setup.upgrade_environment()
        self.assertFalse(setup.environment_needs_upgrade())
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM tags")
            tags = cursor.fetchall()
            cols = [col[0] for col in self._get_cursor_description(cursor)]
            # Db should be unchanged.
            self.assertEquals([('wiki', 'WikiStart', 'tag')], tags)
            self.assertEquals(['tagspace', 'name', 'tag'], cols)
            self.assertEquals(db_default.schema_version, self.get_db_version())

    def test_upgrade_schema_v3(self):
        # Add table for tag change records to the schema.
        schema = [
            Table('tags', key=('tagspace', 'name', 'tag'))[
                Column('tagspace'),
                Column('name'),
                Column('tag'),
                Index(['tagspace', 'name']),
                Index(['tagspace', 'tag']),
            ]
        ]
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for clean install testing.
        self._revert_tractags_schema_init()

        connector = self.db_mgr.get_connector()[0]
        with self.env.db_transaction as db:
            for table in schema:
                for stmt in connector.to_sql(table):
                    db(stmt)
            # Preset system db table with old version.
            db("""INSERT INTO system (name, value)
                  VALUES ('tags_version', '3')""")

        self.assertEquals(3, setup.get_schema_version())
        self.assertTrue(setup.environment_needs_upgrade())

        setup.upgrade_environment()
        self.assertFalse(setup.environment_needs_upgrade())
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM tags_change")
            cols = [col[0] for col in self._get_cursor_description(cursor)]
            self.assertEquals(['tagspace', 'name', 'time', 'author',
                               'oldtags', 'newtags'], cols)
        self.assertEquals(db_default.schema_version, self.get_db_version())


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TagSetupTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
