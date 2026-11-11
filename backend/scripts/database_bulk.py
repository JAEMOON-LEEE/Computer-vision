"""Bound-parameter multi-row inserts that retain PostgreSQL RLS enforcement."""
from psycopg import sql

def insert_rows(cursor, table, columns, rows, conflict=False):
    if not rows:return
    names=columns.split(',') if isinstance(columns,str) else columns
    size=min(10000,60000//len(names))
    cell=sql.SQL('(')+sql.SQL(',').join(sql.Placeholder() for _ in names)+sql.SQL(')')
    prefix=sql.SQL('INSERT INTO twinsight.{} ({}) VALUES ').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,names)))
    suffix=sql.SQL(' ON CONFLICT DO NOTHING') if conflict else sql.SQL('')
    for start in range(0,len(rows),size):
        part=rows[start:start+size]
        cursor.execute(prefix+sql.SQL(',').join(cell for _ in part)+suffix,[v for row in part for v in row])
