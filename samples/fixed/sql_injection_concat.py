def get_user(conn, username):
    query = "SELECT id, name FROM users WHERE name = ?"
    return conn.execute(query, (username,)).fetchall()