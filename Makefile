.PHONY: run install venv

VENV := venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install -q -r requirements.txt

venv: $(VENV)/bin/activate

install: venv

run: venv
	$(PYTHON) app.py
