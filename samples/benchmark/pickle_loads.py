import pickle


def load_session(blob):
    return pickle.loads(blob)
