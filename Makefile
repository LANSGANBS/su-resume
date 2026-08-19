PYTHON ?= python3
THEMES ?= ocean forest plum graphite
FIT_CONTENT ?= content.tex
FIT_THEME ?= ocean
FIT_PAGES ?= 1

.PHONY: build fit layout-test privacy privacy-history test ci

build:
	THEMES="$(THEMES)" ./scripts/build_themes.sh

fit:
	$(PYTHON) ./scripts/fit_resume.py \
		--content "$(FIT_CONTENT)" \
		--theme "$(FIT_THEME)" \
		--target-pages "$(FIT_PAGES)"

layout-test:
	$(PYTHON) ./scripts/test_layouts.py

privacy:
	$(PYTHON) ./scripts/privacy_check.py . --allow-binary .png

privacy-history:
	$(PYTHON) ./scripts/privacy_check.py . --history --allow-binary .png

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s skills/tailor-resume/scripts/tests -p 'test_*.py' -v

ci: test privacy-history build layout-test
