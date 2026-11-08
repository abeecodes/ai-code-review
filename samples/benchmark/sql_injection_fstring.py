def find_orders(conn, customer_id, status):
    query = f"SELECT * FROM orders WHERE customer_id = {customer_id} AND status = '{status}'"
    cursor = conn.cursor()
    cursor.execute(query)
    return cursor.fetchall()
