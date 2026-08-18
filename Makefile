PYTHON ?= python3
THEMES ?= ocean forest plum graphite

.PHONY: build privacy privacy-history test ci

build:
	THEMES="$(THEMES)" ./scripts/build_themes.sh

privacy:
	$(PYTHON) ./scripts/privacy_check.py .

privacy-history:
	$(PYTHON) ./scripts/privacy_check.py . --history

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

ci: test privacy-history build
