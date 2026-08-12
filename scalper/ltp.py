"""LTP quotes logger

Provides a small utility to periodically fetch LTPs for a list of
instrument tokens and append them to a CSV. The function is lightweight
and safe to run in a daemon thread from the monitor.
"""

import os
import csv
import threading
import datetime
from typing import List, Dict, Any


def _parse_quotes_response(resp: Any) -> Dict[str, float]:
	"""Return mapping instrument_token -> ltp from typical quote responses.

	Supports responses that are either a list of dicts or a dict with
	a `data` list. Each item is expected to contain `instrument_token`
	and `ltp` keys (best-effort extraction).
	"""
	items = []
	if isinstance(resp, dict):
		data = resp.get("data")
		if isinstance(data, list):
			items = data
	elif isinstance(resp, list):
		items = resp

	out = {}
	for it in items:
		if not isinstance(it, dict):
			continue
		tok = it.get("instrument_token") or it.get("instrumentToken") or it.get("token")
		ltp = it.get("ltp") or it.get("last_price") or it.get("last")
		if tok is None:
			continue
		try:
			out[str(tok)] = float(ltp) if ltp is not None else None
		except Exception:
			out[str(tok)] = None

	return out


def fetch_quotes_once(client, instrument_tokens: List[Dict[str, str]]) -> Dict[str, float]:
	"""Fetch quotes via client.quotes and return token->ltp mapping.

	`instrument_tokens` should be the same structure passed to the API
	(list of dicts with `instrument_token` and `exchange_segment`).
	"""
	try:
		resp = client.quotes(instrument_tokens=instrument_tokens, quote_type="ltp")
	except Exception as e:
		return {"__error__": str(e)}

	return _parse_quotes_response(resp)


def start_quotes_logger(client, instrument_tokens: List[Dict[str, str]],
						csv_path: str = "logs/ltp_quotes.csv", interval: int = 10,
						stop_event: threading.Event = None) -> None:
	"""Periodically fetch LTPs and append to `csv_path` every `interval` seconds.

	Safe to run as a daemon thread. Each fetch appends one row per
	instrument with columns: timestamp, instrument_token, exchange_segment, ltp
	"""
	os.makedirs(os.path.dirname(csv_path), exist_ok=True)

	# prepare header if needed
	header = ["timestamp", "instrument_token", "exchange_segment", "ltp"]
	if not os.path.exists(csv_path):
		try:
			with open(csv_path, "w", newline="") as f:
				writer = csv.writer(f)
				writer.writerow(header)
		except Exception:
			pass

	if stop_event is None:
		stop_event = threading.Event()

	while not stop_event.is_set():
		ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		try:
			parsed = fetch_quotes_once(client, instrument_tokens)

			rows = []
			for itm in instrument_tokens:
				tok = str(itm.get("instrument_token"))
				exch = itm.get("exchange_segment", "")
				ltp = parsed.get(tok)
				rows.append([ts, tok, exch, ltp])

			with open(csv_path, "a", newline="") as f:
				writer = csv.writer(f)
				writer.writerows(rows)

		except Exception as e:
			# write an error row so we have visibility
			try:
				with open(csv_path, "a", newline="") as f:
					writer = csv.writer(f)
					writer.writerow([ts, "ERROR", "", str(e)])
			except Exception:
				pass

		stop_event.wait(interval)

