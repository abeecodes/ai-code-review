import os


def get_headers():
    key = os.environ["API_KEY"]
    return {"Authorization": "Bearer " + key}
