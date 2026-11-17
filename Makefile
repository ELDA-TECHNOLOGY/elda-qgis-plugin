.PHONY: venv test zip link

# create the development environment (pytest), once
venv:
	python3 -m venv .venv
	.venv/bin/python -m pip install -q -r requirements-dev.txt

# run the whole test suite; anything after -- goes to pytest: make test -- -k upload -x
test:
	.venv/bin/python -m pytest -q $(ARGS) $(filter-out $@,$(MAKECMDGOALS))

# build dist/elda_qgis-<version>.zip and its sha256
zip:
	python3 scripts/package.py

# symlink the plugin into the local QGIS profile
link:
	python3 scripts/link_dev.py

# swallow the extra words given after -- so make does not look for such targets
%:
	@:
