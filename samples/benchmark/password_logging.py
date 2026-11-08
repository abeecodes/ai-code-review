import logging

logger = logging.getLogger(__name__)


def login(username, password):
    logger.info("login attempt user=%s password=%s", username, password)
    return username == "admin"
