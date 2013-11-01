from trac.db import Table, Column, Index, DatabaseManager

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

    connector = DatabaseManager(env)._get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            cursor.execute(stmt)
