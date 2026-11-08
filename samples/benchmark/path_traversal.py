import os

BASE_DIR = "/var/app/uploads"


def read_upload(filename):
    path = os.path.join(BASE_DIR, filename)
    with open(path) as fh:
        return fh.read()
