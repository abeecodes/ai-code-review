import os


def ping_host(host):
    return os.system("ping -c 1 " + host)
