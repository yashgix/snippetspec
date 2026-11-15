import json
import tempfile
import unittest
from pathlib import Path

from experiment import experiment, main
from snippetcheck.metrics import CODES
from snippetcheck.mutate import BREAKING

METRICS: dict = {}
DETAILS: dict = {}


 def setUpModule() -> None:  # placeholder replaced below
    pass
