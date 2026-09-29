"""Small transactional database boundary for account-owned Work records."""
import sqlite3

import db


def connect():
    if db.BACKEND == "postgres":
        return db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    conn = sqlite3.connect(db.SQLITE_PATH, timeout=5)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE")
    return conn


def one(conn, statement, params=()):
    if db.BACKEND == "postgres":
        with conn.cursor() as cur:
            cur.execute(db._adapt_placeholders(statement), params)
            return cur.fetchone()
    return conn.execute(statement, params).fetchone()


def rows(conn, statement, params=()):
    if db.BACKEND == "postgres":
        with conn.cursor() as cur:
            cur.execute(db._adapt_placeholders(statement), params)
            return cur.fetchall()
    return conn.execute(statement, params).fetchall()


def run(conn, statement, params=()):
    if db.BACKEND == "postgres":
        with conn.cursor() as cur:
            cur.execute(db._adapt_placeholders(statement), params)
            return cur.rowcount
    return conn.execute(statement, params).rowcount


def insert_id(conn, statement, params=()):
    if db.BACKEND == "postgres":
        return one(conn, statement + " RETURNING id", params)[0]
    return conn.execute(statement, params).lastrowid


def lock_user(conn, user_id):
    if db.BACKEND == "postgres":
        if not one(conn, "SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,)):
            raise ValueError("account_not_found")
    elif not one(conn, "SELECT id FROM users WHERE id=?", (user_id,)):
        raise ValueError("account_not_found")
