# fina-trade

Trade repository boundary for FinA. It is driven by the `skills/fina-trade/SKILL.md` contract and provides a deterministic `TradeRepository` for registration, observation, corporate events, amendments, cancellations, and lifecycle event publication.

```bash
pip install -e .
pytest -q
```

The repository is included by the main FinA repository as a Git submodule at `modules/fina-trade`.
