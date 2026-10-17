import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# collect() turns timestamps into naive datetimes in the local timezone. Glue runs
# in UTC, so the tests do too, whatever the machine running them is set to.
os.environ["TZ"] = "UTC"
time.tzset()
# Spark's Python workers must match the driver's Python version.
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)


@pytest.fixture(scope="session")
def spark():
    from pyspark.sql import SparkSession
    s = (SparkSession.builder.master("local[2]").appName("edge-etl-tests")
         .config("spark.sql.shuffle.partitions", "2").config("spark.ui.enabled", "false")
         .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    yield s
    s.stop()
