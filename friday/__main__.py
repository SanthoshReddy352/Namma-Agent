"""`python -m friday` → launch the app."""
import sys

from friday.app import main

main(server_only="--server" in sys.argv)
