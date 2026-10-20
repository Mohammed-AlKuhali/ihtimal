PY=.venv/bin/python
# fetch (raw data stays private in data/raw), then build the match table and assert the counts
fetch:
	sh model/fetch_openfootball.sh
	$(PY) model/fetch_espn.py --force
	$(PY) model/build_data.py
	$(PY) model/checks.py
	$(PY) model/fetch_h2h.py
	$(PY) model/h2h.py build
# head-to-head experiment (Amendment 2): selfcheck + dev run only; the holdout is run once, by hand, and only if a pool is accepted
h2h-test:
	$(PY) model/h2h_experiment.py selfcheck
	$(PY) model/h2h_experiment.py dev
	$(PY) model/write_backtest_md.py
backtest:
	$(PY) model/backtest.py selfcheck
	$(PY) model/backtest.py eu
	$(PY) model/backtest.py spl
	$(PY) model/write_backtest_md.py
# predict = fixtures for the next 14 days, then context (ClubElo/Opta, outside the lock hash), record, meta
predict:
	cd model && ../$(PY) predict_live.py && ../$(PY) add_context.py
	$(PY) model/export_meta.py
	$(PY) model/h2h.py files
# lock the featured games (immutable once written); only run before the data is published
lock:
	cd model && ../$(PY) predict_live.py --lock && ../$(PY) add_context.py
# after full time
score:
	cd model && ../$(PY) score.py
# before every deploy: all locked files still match locks.json
verify:
	cd model && ../$(PY) verify_locks.py
# local preview on http://localhost:8000
serve:
	cd site && python3 -m http.server 8000
# deploy (needs `npx vercel login` once). ALWAYS from site/, never from the project root
deploy: verify
	cd site && npx vercel --prod
# prospective evaluation (prospective/PROTOCOL.md). Lock BEFORE every deploy, attest right AFTER it, score after full time
prospective-lock:
	$(PY) prospective/lock_week.py
prospective-attest:
	$(PY) prospective/lock_week.py --attest
prospective-score:
	$(PY) prospective/score.py --end 2026-11-01 --grace 2026-11-08   # Protocol amendment 1 (two-week period)
