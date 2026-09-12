# Token Usage and Cost Report

## Final full-dataset run

- Run command: `python code/main.py`
- Requests processed: 250
- Model providers: none
- Model names: none
- Model calls: 0
- Input tokens: 0
- Output tokens: 0
- Total tokens: 0
- Average tokens per request: 0
- Estimated total model cost: USD 0.00
- Estimated model cost per request: USD 0.00

The submitted engine is deterministic and uses only Python's standard library.
It does not call an LLM, OCR API, banking API, market-data API, or exchange-rate
API during execution. The 16 fixed challenge images were reviewed once and their
relevant amounts are stored as traceable evidence facts in
`code/buy_or_wait/evidence.py`; all dated currency conversions come from the
provided `dataset/exchange_rates.csv`.
