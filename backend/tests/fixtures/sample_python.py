import logging

logger = logging.getLogger(__name__)


def deploy_app():
    logger.info("Starting deployment")
    run_migrations()
    start_server()


def run_migrations():
    logger.warning("Running database migrations")
    execute_sql()


def execute_sql():
    logger.error("Executing SQL statements")
    print("SQL execution complete")


class DatabaseManager:
    def connect(self):
        logger.info("Connecting to database")

    def disconnect(self):
        logger.info("Disconnecting from database")
