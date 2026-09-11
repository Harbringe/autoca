"""Root pytest configuration.

``banking.tests.support`` is loaded as a plugin so its fixtures -- chiefly
``fixture_adapters``, which points the pdf and storage adapters at a captured
statement and a temp directory -- are available to the classification suite as
well. The classification tests need real parsed rows to work on, and a second
copy of the same wiring would drift from this one.
"""

pytest_plugins = ["banking.tests.support"]
