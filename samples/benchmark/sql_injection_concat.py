def get_user(conn, username):
    query = "SELECT id, name FROM users WHERE name = '" + username + "'"
    return conn.execute(query).fetchall()
