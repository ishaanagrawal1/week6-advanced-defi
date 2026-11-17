# Week 6 · Advanced DeFi (marimo notebook)

An interactive version of the Week 6 lesson: Uniswap v3 and v4, DeFi governance, and MEV. It keeps the original lesson's structure, fixes errors, and adds interactive models next to the ideas they explain.

## Files

| File | What it is |
|---|---|
| `week6_advanced_defi.py` | The lesson notebook |
| `requirements.txt` | Pinned dependencies |
| `CONTENT_UPDATE_LOG.md` | Every correction and addition, with sources |
| `SECTION_CHECKLIST.md` | Where each original section lives in the notebook |

No other data or assets are needed. All charts are generated in the notebook.

## Setup

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run it

As a reader (code hidden, app layout):

```bash
marimo run week6_advanced_defi.py
```

To edit, or to see the code behind any cell:

```bash
marimo edit week6_advanced_defi.py
```

If you have `uv`, this works without a manual install: `uvx marimo run --sandbox week6_advanced_defi.py`. The notebook declares its own dependencies at the top of the file, so it also runs on [molab](https://molab.marimo.io) with no setup.

## Interactive pieces

| Where | Experience | Type |
|---|---|---|
| Uniswap v3 → Concentrated liquidity | Alice and Bob checker (change Bob's range, see the capital he needs) | Small calculator |
| Uniswap v3 → Ticks | Tick calculator (price → tick → usable boundaries per fee tier) | Small calculator |
| Uniswap v3 → Providing liquidity | **Concentrated liquidity explorer**: range, later price and capital → token mix, capital efficiency, liquidity chart, IL curve | **Main explorable model** |
| Uniswap v3 → Swapping | Swap across ticks: trade size → buckets crossed, end price, average price | Explorable |
| Governance → Attack sandbox | **Governance attack sandbox**: turnout, delegation, flash loan, Sybil wallets, snapshot, quadratic voting, quorum, timelock → pass/fail with reasons | **Simulation** |
| MEV → AMM sandwich attacks | **Sandwich simulator**: trade size, slippage, pool depth, fee, gas, competition → optimal front-run, profit curve, step-through block, comparison of three ordering systems | **Simulation** |
| Throughout | Five quick-check questions and one MEV sorting exercise with explanations for every answer | Feedback |

## Testing done

- Ran from a clean virtual environment with `marimo check` (no issues) and a full `marimo export html` (every cell ran with no errors).
- Checked the model calculations against known values, including the Alice and Bob numbers from Uniswap's example, the v2 impermanent loss formula, tick conversion, and the snapshot defence in the governance sandbox.
- Opened in the browser with `marimo run`. Checked that the charts render, and that the explorer, governance sandbox and sandwich simulator update when the controls change.
- Still to do: have someone outside the group work through it unguided, as the assignment asks.

The homework section is added in Phase 3.
