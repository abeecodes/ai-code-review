import subprocess


def archive(folder_name):
    cmd = "tar -czf backup.tar.gz " + folder_name
    subprocess.run(cmd, shell=True, check=False)
    return "backup.tar.gz"
