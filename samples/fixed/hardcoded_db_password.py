import os


def connection_string(host):
    password = os.environ["DB_PASSWORD"]
    return f"postgresql://admin:{password}@{host}/app"