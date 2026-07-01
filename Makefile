.PHONY: install handoff backfill daily test
install:
	pip install -r requirements.txt
handoff:
	python -m chipflow.cli build-handoff --end $(END) --window 32
backfill:
	python -m chipflow.cli backfill --start $(START) --end $(END)
daily:
	python -m chipflow.cli run-daily --date $(DATE)
test:
	python -m pytest -q
