# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "marimo>=0.25.2",
#     "altair>=6.3.0",
#     "numpy>=2.0",
#     "pandas>=2.0",
# ]
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Week 6 · Advanced DeFi")

with app.setup:
    import math

    import altair as alt
    import marimo as mo
    import numpy as np
    import pandas as pd

    # Chart colours: the first three slots of a colour-blind-checked palette.
    BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
    MUTED = "#8a8984"


# ---------------------------------------------------------------------------
# Model code. Everything below is plain Python with no marimo UI, so it can be
# imported and unit-tested:  from week6_advanced_defi import amounts_for_liquidity
# ---------------------------------------------------------------------------


@app.function
def amounts_for_liquidity(L, P, pa, pb):
    """Token amounts (x = ETH, y = USDC) held by a Uniswap v3 position.

    L is the position's liquidity, P the current price (USDC per ETH) and
    [pa, pb] the position's range. Formulas from the Uniswap v3 whitepaper (§6.2.3).
    Use pa=0 and pb=math.inf for a full-range (v2-style) position.
    """
    sp = math.sqrt(P)
    sa = math.sqrt(pa)
    sb = math.inf if pb == math.inf else math.sqrt(pb)
    inv_sb = 0.0 if sb == math.inf else 1 / sb
    if P <= pa:  # below range: all ETH
        return L * (1 / sa - inv_sb), 0.0
    if P >= pb:  # above range: all USDC
        return 0.0, L * (sb - sa)
    return L * (1 / sp - inv_sb), L * (sp - sa)


@app.function
def position_value(L, P, pa, pb):
    """Value of a v3 position in USDC at price P."""
    x, y = amounts_for_liquidity(L, P, pa, pb)
    return x * P + y


@app.function
def liquidity_for_capital(capital, P, pa, pb):
    """How much liquidity L a given amount of USDC buys at price P."""
    return capital / position_value(1.0, P, pa, pb)


@app.function
def capital_efficiency(P, pa, pb):
    """How many times more liquidity per dollar a [pa, pb] position has than a
    full-range position, at price P. While the price stays in range, fee income
    per dollar scales by the same factor."""
    return position_value(1.0, P, 0.0, math.inf) / position_value(1.0, P, pa, pb)


@app.function
def range_il(P0, P1, pa, pb):
    """Impermanent loss of a position opened at P0 and valued at P1, compared
    with simply holding the tokens it started with. Fees are excluded.
    Returns a fraction: -0.05 means the LP is worth 5% less than holding."""
    x0, y0 = amounts_for_liquidity(1.0, P0, pa, pb)
    hold = x0 * P1 + y0
    return position_value(1.0, P1, pa, pb) / hold - 1


@app.function
def price_to_tick(price):
    """Uniswap v3 tick index for a price: price = 1.0001 ** tick."""
    return math.floor(math.log(price) / math.log(1.0001))


@app.function
def tick_to_price(tick):
    return 1.0001**tick


@app.function
def swap_across_buckets(edges, liquidity, start_price, usdc_in):
    """Buy ETH with USDC in a simplified v3 pool made of price buckets.

    edges: bucket boundaries (ascending prices); liquidity[i] is the liquidity
    between edges[i] and edges[i+1]. Fees are ignored. Returns the end price,
    ETH received and the USDC used inside each bucket.
    """
    sp = math.sqrt(start_price)
    remaining = usdc_in
    eth_out = 0.0
    used = [0.0] * len(liquidity)
    for i, L in enumerate(liquidity):
        lo, hi = math.sqrt(edges[i]), math.sqrt(edges[i + 1])
        if sp >= hi or remaining <= 0:
            continue
        sp = max(sp, lo)
        need = L * (hi - sp)  # USDC to push price to the top of this bucket
        spend = min(need, remaining)
        new_sp = sp + spend / L
        eth_out += L * (1 / sp - 1 / new_sp)
        used[i] = spend
        remaining -= spend
        sp = new_sp
    return {"end_price": sp**2, "eth_out": eth_out, "used": used, "unfilled": remaining}


@app.function
def cpmm_out(amount_in, reserve_in, reserve_out, fee):
    """Output of a constant-product (x*y=k) swap. The fee is taken from the input."""
    a = amount_in * (1 - fee)
    return reserve_out * a / (reserve_in + a)


@app.function
def run_sandwich(eth_res, usdc_res, victim_usdc, slippage, fee, attack_usdc):
    """Front-run, victim, back-run against an ETH/USDC constant-product pool.

    The victim buys ETH with `victim_usdc` and will accept at most `slippage`
    less ETH than they were quoted. The attacker buys first with `attack_usdc`
    and sells everything right after. Returns every step plus the outcome.
    """
    quote = cpmm_out(victim_usdc, usdc_res, eth_res, fee)
    min_out = quote * (1 - slippage)
    E, U = eth_res, usdc_res
    steps = [("Start", 0.0, 0.0, E, U)]

    a_eth = cpmm_out(attack_usdc, U, E, fee)
    E, U = E - a_eth, U + attack_usdc
    steps.append(("1. Attacker buys ETH", attack_usdc, a_eth, E, U))

    v_eth = cpmm_out(victim_usdc, U, E, fee)
    ok = v_eth >= min_out - 1e-12
    if ok:
        E, U = E - v_eth, U + victim_usdc
        steps.append(("2. Victim buys ETH", victim_usdc, v_eth, E, U))
    else:
        steps.append(("2. Victim's trade reverts (slippage limit)", 0.0, 0.0, E, U))

    back = cpmm_out(a_eth, E, U, fee)
    E, U = E + a_eth, U - back
    steps.append(("3. Attacker sells ETH", a_eth, back, E, U))

    return {
        "steps": steps,
        "quote": quote,
        "min_out": min_out,
        "victim_eth": v_eth if ok else 0.0,
        "victim_ok": ok,
        "gross_profit": back - attack_usdc,
    }


@app.function
def max_safe_frontrun(eth_res, usdc_res, victim_usdc, slippage, fee):
    """Largest front-run that still leaves the victim's trade inside their
    slippage limit (found by bisection: the victim's output falls as the
    front-run grows)."""
    lo, hi = 0.0, usdc_res
    for _ in range(80):
        mid = (lo + hi) / 2
        if run_sandwich(eth_res, usdc_res, victim_usdc, slippage, fee, mid)["victim_ok"]:
            lo = mid
        else:
            hi = mid
    return lo


@app.function
def backrun_arbitrage(eth_res, usdc_res, external_price, fee):
    """Profit (USDC) from selling ETH into a pool whose price is above the
    external market price, sized optimally. Closed form for x*y=k with a fee."""
    # Optimal effective input: dx*(1-fee) = sqrt(E*U*(1-fee)/P) - E
    dx_eff = math.sqrt(eth_res * usdc_res * (1 - fee) / external_price) - eth_res
    if dx_eff <= 0:
        return 0.0
    dx = dx_eff / (1 - fee)
    return cpmm_out(dx, eth_res, usdc_res, fee) - dx * external_price


@app.function
def governance_holders(seed=6):
    """A fictional DAO with 100M tokens. Returns a DataFrame of wallets."""
    rng = np.random.default_rng(seed)
    retail = rng.lognormal(mean=0, sigma=1.6, size=2000)
    retail = retail / retail.sum() * 35_000_000
    rows = [{"group": "Retail", "tokens": t} for t in retail]
    rows += [{"group": "Early investors", "tokens": 10_000_000} for _ in range(4)]
    rows += [{"group": "Treasury (cannot vote)", "tokens": 15_000_000}]
    rows += [{"group": "Lending pools (flash-loanable)", "tokens": 10_000_000}]
    df = pd.DataFrame(rows)
    df["random"] = rng.random(len(df))
    return df


@app.function
def tally_vote(
    holders,
    retail_turnout,
    investor_delegated,
    attacker_own,
    flash_loan,
    attacker_wallets,
    snapshot,
    quadratic,
    quorum_tokens,
):
    """Tally a malicious proposal (attacker votes For, everyone else Against).

    - Retail wallets vote if their random draw is below `retail_turnout`.
    - Investors only vote with the share they delegated to active delegates.
    - Flash-loaned tokens only count when votes use *current* balances
      (no snapshot), because the loan is repaid in the same transaction.
    - Quadratic voting gives each wallet sqrt(tokens) votes; the attacker
      can split tokens across many wallets (a Sybil attack).
    - Quorum is measured in raw tokens voting For.
    """
    retail = holders[holders.group == "Retail"]
    voters = retail[retail.random < retail_turnout].tokens.to_numpy()
    investors = holders[holders.group == "Early investors"].tokens.to_numpy() * investor_delegated
    against_wallets = np.concatenate([voters, investors[investors > 0]])

    borrowed_counts = 0.0 if snapshot else flash_loan
    attacker_tokens = attacker_own + borrowed_counts
    per_wallet = attacker_tokens / max(attacker_wallets, 1)

    if quadratic:
        votes_for = attacker_wallets * math.sqrt(per_wallet) if attacker_tokens > 0 else 0.0
        votes_against = float(np.sqrt(against_wallets).sum())
    else:
        votes_for = attacker_tokens
        votes_against = float(against_wallets.sum())

    reached_quorum = attacker_tokens >= quorum_tokens
    passes = reached_quorum and votes_for > votes_against
    return {
        "votes_for": votes_for,
        "votes_against": votes_against,
        "for_tokens": attacker_tokens,
        "against_tokens": float(against_wallets.sum()),
        "flash_counted": borrowed_counts,
        "reached_quorum": reached_quorum,
        "passes": passes,
    }


@app.function
def answer_feedback(choice, correct, explanations):
    """Callout for a multiple-choice question. `explanations` maps every
    option to the reason it is right or wrong."""
    if choice is None:
        return mo.md("")
    kind = "success" if choice == correct else "danger"
    lead = "**Correct.** " if choice == correct else "**Not quite.** "
    return mo.callout(mo.md(lead + explanations[choice]), kind=kind)


# ---------------------------------------------------------------------------
# Lesson
# ---------------------------------------------------------------------------


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Week 6 · Advanced DeFi

    Last week you saw how a basic automated market maker (AMM) works: a pool holds two tokens, prices follow $x \cdot y = k$, and liquidity providers (LPs) earn fees for taking on impermanent loss. This week looks at what happens once real money and real adversaries show up:

    1. **Uniswap v3 and v4.** How concentrated liquidity makes LP capital work harder, and what that costs.
    2. **DeFi governance.** How token holders control a protocol, and how that control gets attacked.
    3. **MEV (maximal extractable value).** Who decides the order of transactions in a block, and how they profit from it.

    **How to use this notebook.** Read top to bottom. Each interactive section starts with a short *Try this* box telling you what to change and what to look for. Sliders and dropdowns update everything below them instantly, and nothing you do here touches a real blockchain. The code is hidden; open a cell's menu if you want to see how something is calculated.

    Expect about **75–90 minutes** for the lesson. The homework section at the end is separate.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "🎯 Learning objectives": mo.md(
                """
    By the end of this week you should be able to:

    - Explain why Uniswap v2 wastes LP capital and how concentrated liquidity fixes it.
    - Calculate the capital efficiency of a v3 position and the token amounts it needs.
    - Convert between prices and ticks, and explain what happens when a swap crosses a tick.
    - Explain why a narrower range *increases* impermanent loss, and when a position becomes a range order.
    - Describe what Uniswap v4 changes: hooks, the singleton pool manager and flash accounting.
    - Walk through a governance proposal from submission to execution, and name the defences against flash-loan voting attacks.
    - Define MEV and explain front-running, back-running, sandwich attacks, JIT liquidity and arbitrage with a worked example.
    - Describe how transaction ordering moved from miners and gas auctions to today's proposer–builder separation.
    - Argue which kinds of MEV harm users and which ones keep markets working.
    """
            ),
            "📖 Terms from earlier weeks you'll need": mo.md(
                """
    | Term | Meaning |
    |---|---|
    | **AMM** | A smart contract that trades against a pool of two tokens using a pricing formula instead of an order book. |
    | **LP (liquidity provider)** | Someone who deposits both tokens into a pool and earns a share of trading fees. |
    | **Impermanent loss (IL)** | How much less an LP position is worth than just holding the tokens you deposited, caused by the pool rebalancing as the price moves. |
    | **Slippage** | The gap between the price you were quoted and the price you actually get. You set a *slippage tolerance*: the worst price you'll accept before the trade cancels (reverts). |
    | **Mempool** | The waiting room of transactions that have been broadcast but not yet included in a block. Anyone running a node can read it. |
    | **Validator / proposer** | Since Ethereum's switch to proof of stake in September 2022, validators (not miners) take turns proposing blocks. |
    | **Flash loan** | A loan with no collateral that must be borrowed and repaid in the same transaction. If it isn't repaid, the whole transaction reverts. |
    """
            ),
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Advanced DeFi Protocols

    ### Uniswap v3

    Uniswap v2, and the many forks that copied it, have a serious problem: **they are not capital efficient.**

    A v2 LP's deposit is spread along the whole $x \cdot y = k$ curve, so the pool has liquidity at every price from 0 to infinity. But prices spend almost all their time in a narrow band. In an ETH/USDC pool, the liquidity reserved for "ETH trades at \$5" or "ETH trades at \$5,000,000" sits idle and earns nothing, while it still exposes the LP to impermanent loss. Fees earned on the small slice that *is* used often don't make up for that loss.

    Uniswap v3 (launched May 2021) asked: can LPs put their liquidity only where trading actually happens, while the pool still has enough liquidity to cover any trade?
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Concentrated liquidity

    In v3 an LP picks a **price range** $[p_a, p_b]$ and their liquidity is only used while the pool price is inside it. Different LPs pick different ranges, and one pool combines all of them, so the pool's total liquidity at each price is the sum of every position that covers that price. Each position is a separate record with its own range. In v3 that record is an NFT, because no two positions are interchangeable the way v2's LP tokens were.

    **Example (from Uniswap's v3 launch post).** ETH trades at 1,500 DAI.

    - **Alice** puts \$1M into the full range, like v2: 333.33 ETH and 500,000 DAI.
    - **Bob** concentrates between 1,000 and 2,250 DAI. To get *the same liquidity* as Alice inside that range he only needs about **\$183.5k** (61.19 ETH and 91,780 DAI).

    While ETH stays between 1,000 and 2,250 DAI, Alice and Bob earn **the same fees**, even though Alice committed about **5.45×** as much money. Bob can do something else with the other ~\$816k. If ETH leaves his range, Bob earns nothing until it comes back.

    The fee *rate* is the same for everyone in a pool (0.3% of the trade, for example). Bob doesn't pay or charge a higher rate; he earns more **per dollar deposited** because each of his dollars supplies more liquidity while the price is in range.
    """)
    return


@app.cell(hide_code=True)
def _():
    ab_upper = mo.ui.dropdown(
        options={"2,250 DAI (Uniswap's example)": 2250, "2,500 DAI (the old lesson's range)": 2500, "1,800 DAI": 1800, "1,600 DAI": 1600},
        value="2,250 DAI (Uniswap's example)",
        label="Bob's upper bound",
    )
    ab_lower = mo.ui.dropdown(
        options={"1,000 DAI": 1000, "1,200 DAI": 1200, "1,400 DAI": 1400},
        value="1,000 DAI",
        label="Bob's lower bound",
    )
    return ab_lower, ab_upper


@app.cell(hide_code=True)
def _(ab_lower, ab_upper):
    _P = 1500
    _pa, _pb = ab_lower.value, ab_upper.value
    _eff = capital_efficiency(_P, _pa, _pb)
    _L_alice = liquidity_for_capital(1_000_000, _P, 0, math.inf)
    _bob_capital = position_value(_L_alice, _P, _pa, _pb)
    _bx, _by = amounts_for_liquidity(_L_alice, _P, _pa, _pb)
    mo.vstack(
        [
            mo.md("**Check the numbers yourself.** Change Bob's range and see how much capital he needs to match Alice's liquidity at a price of 1,500."),
            mo.hstack([ab_lower, ab_upper], justify="start", gap=2),
            mo.hstack(
                [
                    mo.stat(f"${_bob_capital:,.0f}", label="Bob's capital", caption=f"{_bx:,.2f} ETH + {_by:,.0f} DAI"),
                    mo.stat(f"{_eff:.2f}×", label="Capital efficiency", caption="Alice's capital ÷ Bob's"),
                ],
                justify="start",
                gap=2,
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Why the old version of this example was wrong": mo.md(r"""
    An earlier version of this lesson used a range of 1,000–2,500, said Bob needs \$183.5k, and got **6.3×** by dividing "115.5 sqrt-price units" by $\sqrt{2500} - \sqrt{1000} = 18.38$. Three things go wrong:

    1. **The numbers don't match each other.** \$183.5k is Uniswap's figure for a 1,000–**2,250** range. For 1,000–2,500 Bob would need about \$204k, an efficiency of 4.89×. Pick "2,500" above to see this.
    2. **There is no "full range width" of 115.5.** A full-range position covers $\sqrt{p}$ from 0 to infinity. You can't compare widths in sqrt-price space when one width is infinite.
    3. **Efficiency depends on the current price, not just the range width.** The correct formula compares how much each position is worth at the same liquidity $L$, at today's price $P$:

    $$\text{capital efficiency} = \frac{2\sqrt{P}}{2\sqrt{P} - \sqrt{p_a} - P/\sqrt{p_b}}$$

    With $P = 1500$, $p_a = 1000$, $p_b = 2250$: $\frac{77.46}{77.46 - 31.62 - 31.62} = 5.45$. The derivation is in *Real and virtual reserves* below.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    q1 = mo.ui.radio(
        options=["They go up", "They stay the same", "They go down"],
        label=r"**Predict:** Bob narrows his range from 1,000–2,250 to 1,400–1,600 and keeps the same \$183.5k. While ETH stays between 1,400 and 1,600, what happens to his fee earnings?",
    )
    q1
    return (q1,)


@app.cell(hide_code=True)
def _(q1):
    answer_feedback(
        q1.value,
        "They go up",
        {
            "They go up": "The same dollars are now spread over a much smaller price range, so each dollar provides more liquidity and earns a bigger share of the fees. Pick 1,400 and 1,600 in the widget above: the capital efficiency jumps to roughly 26×. The catch: ETH only has to move about 7% to leave the range, and then he earns nothing.",
            "They stay the same": "The fee rate per trade is the same, but Bob's *share* of each trade's fee depends on how much of the active liquidity he provides. A narrower range means more liquidity per dollar, so a bigger share.",
            "They go down": "Narrowing the range concentrates his dollars where trading happens, so he provides more liquidity there, not less. The risk is that the price leaves the range more often, but while it's inside he earns more.",
        },
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Ticks and visualizing concentrated liquidity

    v3 can't track every possible price range, so it splits the price line into discrete steps called **ticks**. Tick number $i$ (any integer, positive or negative) sits at price

    $$p(i) = 1.0001^{\,i}$$

    So **each tick is 0.01% (one basis point) away from its neighbour.** The contract actually stores $\sqrt{p}$, so you will often see this written as $\sqrt{p(i)} = 1.0001^{\,i/2}$. That is the *square root* of the price, not the price itself. (An older version of this lesson mixed these two up.)

    Why store $\sqrt{p}$? Inside a single range the amount of each token moves *linearly* in $\sqrt{p}$: $\Delta y = L\,\Delta\sqrt{p}$ and $\Delta x = L\,\Delta(1/\sqrt{p})$. That keeps swap math cheap.

    Position boundaries can't sit on any tick. Each fee tier has a **tick spacing**, and ranges have to start and end on multiples of it. Wider spacing means fewer ticks to cross during a swap, which saves gas.

    | Fee tier | Tick spacing | Smallest possible range width |
    |---|---|---|
    | 0.01% | 1 | ≈ 0.01% |
    | 0.05% | 10 | ≈ 0.1% |
    | 0.30% | 60 | ≈ 0.6% |
    | 1.00% | 200 | ≈ 2% |

    Think of the space between two usable ticks as a **bucket**. The height of each bucket is how much liquidity sits in it. In v2 every bucket would be the same height, because every LP covers every price. In v3 the heights are uneven: tall near the current price, where LPs crowd in, and short far away.
    """)
    return


@app.cell(hide_code=True)
def _():
    tk_price = mo.ui.number(start=0.0001, stop=1_000_000, step=0.01, value=3000, label="Price (USDC per ETH)")
    tk_tier = mo.ui.dropdown(
        options={"0.01%": 1, "0.05%": 10, "0.30%": 60, "1.00%": 200}, value="0.30%", label="Fee tier"
    )
    return tk_price, tk_tier


@app.cell(hide_code=True)
def _(tk_price, tk_tier):
    _tick = price_to_tick(tk_price.value)
    _sp = tk_tier.value
    _lo = (_tick // _sp) * _sp
    _hi = _lo + _sp
    mo.vstack(
        [
            mo.md("**Tick calculator.** Type a price and pick a fee tier to see which tick it falls on and which usable boundaries surround it."),
            mo.hstack([tk_price, tk_tier], justify="start", gap=2),
            mo.md(
                f"""
    - Price {tk_price.value:,.4f} falls on tick **{_tick:,}** (because 1.0001^{_tick:,} = {tick_to_price(_tick):,.4f}).
    - With tick spacing {_sp}, the nearest usable boundaries are tick **{_lo:,}** (price {tick_to_price(_lo):,.4f}) and tick **{_hi:,}** (price {tick_to_price(_hi):,.4f}).
    - That smallest bucket is **{(tick_to_price(_hi) / tick_to_price(_lo) - 1) * 100:.2f}%** wide.
    """
            ),
            mo.callout(
                mo.md("Simplification: real pools price tokens in their smallest units (USDC has 6 decimals, ETH has 18), so the tick numbers you see onchain for ETH/USDC are different from these. The spacing and the percentages are the same."),
                kind="neutral",
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    q2 = mo.ui.radio(
        options=["About 0.1% higher", "About 1% higher", "About 10% higher", "100 times higher"],
        label="**Quick check:** how much higher is the price at tick 100 than at tick 0?",
    )
    q2
    return (q2,)


@app.cell(hide_code=True)
def _(q2):
    answer_feedback(
        q2.value,
        "About 1% higher",
        {
            "About 1% higher": "1.0001¹⁰⁰ ≈ 1.01005. A hundred one-basis-point steps compound to just over 1%.",
            "About 0.1% higher": "Each tick is 0.01%, and there are 100 of them: 1.0001¹⁰⁰ ≈ 1.010, so about 1%.",
            "About 10% higher": "That would need about 953 ticks. Each tick is only 0.01%, so 100 ticks is about 1%.",
            "100 times higher": "Tick numbers are exponents, not prices: p(i) = 1.0001^i. Tick 100 is 1.0001¹⁰⁰ ≈ 1.01.",
        },
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Providing liquidity in Uniswap v3

    When you open a position you choose two ticks, and **the range decides what mix of tokens you deposit**, not the price alone.

    - Buckets entirely **above** the current price hold **only ETH**. The price only gets there if traders buy ETH, so those buckets need ETH to hand out.
    - Buckets entirely **below** the current price hold **only USDC**, ready to buy ETH from sellers if the price falls.
    - Only the bucket containing the current price holds a mix.

    So the ratio you deposit isn't 50/50 like v2. A range sitting mostly *above* today's price needs mostly ETH; a range mostly *below* needs mostly USDC. As the price drops toward your lower bound, your position fills up with ETH. As it rises toward your upper bound, it fills up with USDC.

    The explorer below puts this together. It is this week's main **explorable model**.
    """)
    return


@app.cell(hide_code=True)
def _():
    cl_range = mo.ui.range_slider(
        start=500, stop=8000, step=50, value=[2400, 3750], label="Your price range (USDC per ETH)", show_value=True, full_width=True
    )
    cl_end = mo.ui.slider(start=500, stop=8000, step=50, value=3300, label="ETH price later", show_value=True, full_width=True)
    cl_capital = mo.ui.number(start=100, stop=10_000_000, step=100, value=10_000, label="Capital you deposit (USD)")
    return cl_capital, cl_end, cl_range


@app.cell(hide_code=True)
def _():
    mo.callout(
        mo.md("""
    **Concentrated liquidity explorer: try this**

    ETH starts at **3,000 USDC**. Pick a price range, then move "ETH price later" to see what your position is worth.

    1. **Predict first:** if you narrow the range to 2,900–3,100, will a 10% price move hurt you more or less than with the default range?
    2. Narrow the range and watch *capital efficiency* climb. Then move the later price to 3,300 and compare impermanent loss for your range with a full-range position.
    3. Drag the later price outside your range. Check the token mix: you now hold only one token, and you stop earning fees.
    4. Put the whole range above 3,000 (say 3,200–3,600). You deposit only ETH. That is a **range order**, covered further down.
    """),
        kind="info",
    )
    return


@app.cell(hide_code=True)
def _(cl_capital, cl_end, cl_range):
    P0 = 3000.0
    cl_pa, cl_pb = cl_range.value
    cl_pa = max(cl_pa, 1.0)
    if cl_pb <= cl_pa:
        cl_pb = cl_pa + 50
    cl_L = liquidity_for_capital(cl_capital.value, P0, cl_pa, cl_pb)
    cl_L_full = liquidity_for_capital(cl_capital.value, P0, 0, math.inf)
    cl_x0, cl_y0 = amounts_for_liquidity(cl_L, P0, cl_pa, cl_pb)
    cl_x1, cl_y1 = amounts_for_liquidity(cl_L, cl_end.value, cl_pa, cl_pb)
    cl_in_range_now = cl_pa < P0 < cl_pb
    cl_eff = cl_L / cl_L_full
    cl_il = range_il(P0, cl_end.value, cl_pa, cl_pb)
    cl_il_full = range_il(P0, cl_end.value, 0, math.inf)
    return (
        P0,
        cl_L,
        cl_L_full,
        cl_eff,
        cl_il,
        cl_il_full,
        cl_in_range_now,
        cl_pa,
        cl_pb,
        cl_x0,
        cl_x1,
        cl_y0,
        cl_y1,
    )


@app.cell(hide_code=True)
def _(P0, cl_L, cl_L_full, cl_end, cl_pa, cl_pb):
    # Chart 1: liquidity height by price ("buckets")
    _prices = np.linspace(500, 8000, 301)
    _liq = pd.DataFrame(
        {
            "price": np.concatenate([_prices, _prices]),
            "liquidity": np.concatenate(
                [np.where((_prices >= cl_pa) & (_prices <= cl_pb), cl_L, 0.0), np.full_like(_prices, cl_L_full)]
            ),
            "position": ["Your range"] * len(_prices) + ["Full range (v2-style)"] * len(_prices),
        }
    )
    _base = alt.Chart(_liq).encode(
        x=alt.X("price:Q", title="ETH price (USDC)", scale=alt.Scale(domain=[500, 8000], nice=False)),
        y=alt.Y("liquidity:Q", title="Liquidity L (same capital)"),
        color=alt.Color(
            "position:N",
            scale=alt.Scale(domain=["Your range", "Full range (v2-style)"], range=[BLUE, ORANGE]),
            legend=alt.Legend(orient="top", title=None),
        ),
        tooltip=[alt.Tooltip("position:N"), alt.Tooltip("price:Q", format=",.0f"), alt.Tooltip("liquidity:Q", format=",.0f")],
    )
    _area = _base.transform_filter(alt.datum.position == "Your range").mark_area(opacity=0.35, interpolate="step-after")
    _lines = _base.mark_line(strokeWidth=2, interpolate="step-after")
    _rules = (
        alt.Chart(pd.DataFrame({"price": [P0, cl_end.value], "label": ["Starting price", "Later price"]}))
        .mark_rule(strokeDash=[4, 3], color=MUTED)
        .encode(x="price:Q", tooltip=["label:N", alt.Tooltip("price:Q", format=",.0f")])
    )
    cl_liq_chart = (
        (_area + _lines + _rules)
        .properties(height=220, width="container", title="Where your liquidity sits (taller = more liquidity per price step)")
        .configure_scale(zero=False)
    )
    return (cl_liq_chart,)


@app.cell(hide_code=True)
def _(P0, cl_end, cl_pa, cl_pb):
    # Chart 2: impermanent loss vs later price
    _grid = np.linspace(600, 7900, 220)
    _df = pd.DataFrame(
        {
            "price": np.concatenate([_grid, _grid]),
            "il": [range_il(P0, p, cl_pa, cl_pb) * 100 for p in _grid] + [range_il(P0, p, 0, math.inf) * 100 for p in _grid],
            "position": ["Your range"] * len(_grid) + ["Full range (v2-style)"] * len(_grid),
        }
    )
    _lines = (
        alt.Chart(_df)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("price:Q", title="ETH price later (USDC)", scale=alt.Scale(domain=[500, 8000], nice=False)),
            y=alt.Y("il:Q", title="Impermanent loss vs holding (%)"),
            color=alt.Color(
                "position:N",
                scale=alt.Scale(domain=["Your range", "Full range (v2-style)"], range=[BLUE, ORANGE]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[alt.Tooltip("position:N"), alt.Tooltip("price:Q", format=",.0f"), alt.Tooltip("il:Q", format=".2f", title="IL (%)")],
        )
    )
    _band = (
        alt.Chart(pd.DataFrame({"a": [cl_pa], "b": [cl_pb]}))
        .mark_rect(opacity=0.08, color=BLUE)
        .encode(x="a:Q", x2="b:Q")
    )
    _rule = alt.Chart(pd.DataFrame({"price": [cl_end.value]})).mark_rule(strokeDash=[4, 3], color=MUTED).encode(x="price:Q")
    cl_il_chart = (
        (_band + _lines + _rule)
        .properties(height=240, width="container", title="Impermanent loss at each later price (shaded = your range, fees not included)")
        .configure_scale(zero=False)
    )
    return (cl_il_chart,)


@app.cell(hide_code=True)
def _(
    P0,
    cl_capital,
    cl_eff,
    cl_end,
    cl_il,
    cl_il_chart,
    cl_il_full,
    cl_in_range_now,
    cl_liq_chart,
    cl_pa,
    cl_pb,
    cl_range,
    cl_x0,
    cl_x1,
    cl_y0,
    cl_y1,
):
    _end = cl_end.value
    _in_range_later = cl_pa < _end < cl_pb
    if cl_in_range_now:
        _eff_text = mo.stat(f"{cl_eff:.1f}×", label="Capital efficiency", caption="fees per $ vs full range, while in range")
    else:
        _eff_text = mo.stat("—", label="Capital efficiency", caption="out of range at 3,000: earns no fees yet")
    _status = (
        mo.callout(mo.md(f"At {_end:,.0f} you're **in range**: you're earning fees, about **{cl_eff:.1f}×** what a full-range LP earns per dollar."), kind="success")
        if _in_range_later
        else mo.callout(
            mo.md(
                f"At {_end:,.0f} you're **out of range**: your position is entirely **{'USDC' if _end >= cl_pb else 'ETH'}** and earns no fees until the price comes back."
            ),
            kind="warn",
        )
    )
    _explain = mo.md(
        f"""
    **Reading the result.** You deposit **{cl_x0:,.3f} ETH + {cl_y0:,.0f} USDC** (\\${cl_capital.value:,.0f} at 3,000). At a later price of **{_end:,.0f}** the position holds **{cl_x1:,.3f} ETH + {cl_y1:,.0f} USDC**.

    Compared with just holding what you deposited, your range has an impermanent loss of **{cl_il * 100:.2f}%**. A full-range position would have lost **{cl_il_full * 100:.2f}%** over the same move. Narrower ranges lose more because the pool sells your rising token (and buys the falling one) faster over a short stretch of price.

    {"**Notice the ratio.** Your IL is about %.1f× the full-range IL, and your fees are %.1f× too. That's not a coincidence: inside the range, a concentrated position loses exactly what a full-range position with the same liquidity *L* would lose. Fees and IL scale up together, so while you're in range, concentrating makes a profitable position more profitable and a losing one lose faster. Range width starts to really hurt once the price leaves the range: fees stop, and IL keeps growing." % (cl_il / cl_il_full if cl_il_full else float("nan"), cl_eff) if cl_in_range_now and _in_range_later and abs(cl_il_full) > 1e-6 else ""}
    """
    )
    mo.vstack(
        [
            cl_range,
            cl_end,
            mo.hstack([cl_capital], justify="start"),
            mo.hstack(
                [
                    _eff_text,
                    mo.stat(f"{cl_il * 100:.2f}%", label="Your IL at later price"),
                    mo.stat(f"{cl_il_full * 100:.2f}%", label="Full-range IL at later price"),
                ],
                justify="start",
                gap=2,
            ),
            _status,
            cl_liq_chart,
            cl_il_chart,
            _explain,
        ],
        gap=1,
    )
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Assumptions and limitations of this model": mo.md("""
    - **One position against a constant price path.** We only compare the start and the end. Real fee income depends on how much trading happens while the price is in your range, which the model doesn't simulate.
    - **Fees aren't included in the IL numbers.** The "break even" line tells you how much fee income you'd need; whether you actually earn it depends on volume.
    - **No tick rounding.** Real ranges snap to the fee tier's tick spacing (see the tick calculator above); the difference is under 2%.
    - **No gas costs.** Opening, closing and re-centring a position each costs a transaction.
    - **Ignores other LPs.** Your actual fee share depends on how much liquidity others have in the same buckets.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Swapping with Uniswap v3

    Inside one bucket, a v3 pool behaves exactly like a v2 pool with that bucket's liquidity: price moves along an $x \cdot y = k$ curve. When a trade uses up a bucket, the pool **crosses a tick**: it updates its active liquidity to the next bucket's value and keeps filling the trade there.

    "Uses up" is literal. Say you're buying ETH. As the price rises through a bucket, the bucket hands out its ETH and fills with USDC. When it runs out of ETH it can't sell any more, so the trade moves into the next bucket up. That bucket is still full of ETH, becomes the active one, and starts taking USDC.

    Deep buckets (tall bars) absorb a lot of USDC with little price movement. Shallow buckets let the price jump. Try a large trade below and watch it chew through several buckets.
    """)
    return


@app.cell(hide_code=True)
def _():
    sx_trade = mo.ui.slider(
        start=0, stop=6_000_000, step=50_000, value=1_000_000, label="USDC spent buying ETH", show_value=True, full_width=True
    )
    sx_trade
    return (sx_trade,)


@app.cell(hide_code=True)
def _(sx_trade):
    _edges = list(range(2700, 3351, 50))
    _centers = [(a + b) / 2 for a, b in zip(_edges[:-1], _edges[1:])]
    _liquidity = [1.1e6 * math.exp(-(((c - 2990) / 160) ** 2)) + 1.5e5 for c in _centers]
    _start = 3010.0
    _r = swap_across_buckets(_edges, _liquidity, _start, sx_trade.value)
    _df = pd.DataFrame(
        {
            "lo": _edges[:-1],
            "hi": _edges[1:],
            "liquidity": _liquidity,
            "used": _r["used"],
            "state": [
                "Used by this trade" if u > 0 else ("Not reached" if a >= _start else "Below the starting price")
                for u, a in zip(_r["used"], _edges[:-1])
            ],
        }
    )
    _bars = (
        alt.Chart(_df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke="white", strokeWidth=2)
        .encode(
            x=alt.X("lo:Q", title="ETH price (USDC)", scale=alt.Scale(domain=[2700, 3350])),
            x2="hi:Q",
            y=alt.Y("liquidity:Q", title="Liquidity in bucket"),
            color=alt.Color(
                "state:N",
                scale=alt.Scale(domain=["Used by this trade", "Not reached", "Below the starting price"], range=[ORANGE, BLUE, "#cfcdc6"]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                alt.Tooltip("lo:Q", title="From"),
                alt.Tooltip("hi:Q", title="To"),
                alt.Tooltip("liquidity:Q", format=",.0f"),
                alt.Tooltip("used:Q", format=",.0f", title="USDC used here"),
            ],
        )
    )
    _rules = alt.Chart(pd.DataFrame({"p": [_start, _r["end_price"]], "label": ["Start", "End"]})).mark_rule(
        color="#0b0b0b", strokeDash=[4, 3]
    ).encode(x="p:Q", tooltip=["label:N", alt.Tooltip("p:Q", format=",.1f")])
    _crossed = sum(1 for u in _r["used"] if u > 0)
    _avg = sx_trade.value / _r["eth_out"] if _r["eth_out"] > 0 else _start
    mo.vstack(
        [
            (_bars + _rules).properties(height=230, width="container", title="Buckets of liquidity around the current price"),
            mo.md(
                f"Spending **{sx_trade.value:,.0f} USDC** moves the price from **{_start:,.0f}** to **{_r['end_price']:,.1f}** "
                f"({(_r['end_price'] / _start - 1) * 100:+.2f}%), touching **{_crossed}** bucket{'s' if _crossed != 1 else ''}. "
                f"You receive **{_r['eth_out']:,.2f} ETH** at an average price of **{_avg:,.1f}**."
                + (f" ⚠️ The pool ran out of liquidity in this window with {_r['unfilled']:,.0f} USDC unfilled." if _r["unfilled"] > 1 else "")
            ),
            mo.md("<small>Fictional liquidity profile, fees ignored. Real pools have many more, narrower buckets.</small>"),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Real and virtual reserves

    How do we describe a concentrated position with a curve we already understand?

    A position only holds tokens inside $[p_a, p_b]$. Imagine instead that it were a normal v2 position, with liquidity everywhere. Its reserves on that imaginary curve are called **virtual reserves** $(x_v, y_v)$. They satisfy the usual

    $$x_v \cdot y_v = L^2, \qquad P = \frac{y_v}{x_v}$$

    where $L$ is the position's **liquidity** (so $L^2$ plays the role of $k$), and prices are always "USDC per ETH", i.e. $y$ per $x$. Solving those two equations gives the virtual reserves at any price:

    $$x_v = \frac{L}{\sqrt{P}}, \qquad y_v = L\sqrt{P}$$

    The **real reserves** $(x, y)$ are what the position actually holds. The trick is that a concentrated position only needs to hold enough to get from the current price to the edge of its range:

    - At the top, $P = p_b$, it has sold all its ETH, so $x = 0$ while $x_v = L/\sqrt{p_b}$.
    - At the bottom, $P = p_a$, it has spent all its USDC, so $y = 0$ while $y_v = L\sqrt{p_a}$.

    The real reserves are the virtual reserves minus the part that's never needed:

    $$x = \frac{L}{\sqrt{P}} - \frac{L}{\sqrt{p_b}}, \qquad y = L\sqrt{P} - L\sqrt{p_a}$$

    Rearranging gives the curve for real reserves (whitepaper eq. 2.2):

    $$\left(x + \frac{L}{\sqrt{p_b}}\right)\left(y + L\sqrt{p_a}\right) = L^2$$

    Note that the **real** reserves do *not* satisfy $x \cdot y = L^2$. Only the virtual ones do. That's the shift: the real curve is the v2 curve slid toward the origin until it touches both axes at $p_a$ and $p_b$.

    **Where capital efficiency comes from.** A full-range position at price $P$ is worth $x_v P + y_v = 2L\sqrt{P}$. A concentrated one is worth $xP + y = L\left(2\sqrt{P} - \sqrt{p_a} - P/\sqrt{p_b}\right)$. Same $L$, smaller deposit. The ratio of the two is the capital efficiency formula from the Alice and Bob example.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Concentrated liquidity as a limit order

    What happens when the price leaves your range? **Your position turns entirely into one token.**

    Say you provide liquidity in the ETH/USDC pool between 2,000 and 2,200 USDC:

    - If ETH rises **above 2,200**, the pool has sold all your ETH on the way up. You hold **only USDC**.
    - If ETH falls **below 2,000**, the pool has spent all your USDC buying ETH on the way down. You hold **only ETH**.

    This is what keeps liquidity constant in $\sqrt{p}$ space and only active inside your range. It also means LPs can use v3 as a kind of limit order, called a **range order**: put a narrow range entirely above the current price, deposit only ETH, and if the price rises through it your ETH is sold for USDC.

    **Example.** DAI trades just below 1.001 USDC and you want to sell 1M DAI. You open a position on the DAI/USDC pool from 1.001 to 1.002 USDC. That is entirely above the current price, so you deposit only DAI. If DAI rises through the range, your DAI is gradually swapped for USDC, and once it's above 1.002 you hold only USDC, plus the fees you earned along the way. Withdraw then, or a fall back through the range will swap you back into DAI.

    **A correction on impermanent loss.** An older version of this lesson said this behaviour *minimizes* impermanent loss. It doesn't. Once you're out of range the pool stops rebalancing you, but that's because you've already been fully converted into the token that did worse. If ETH keeps rising, your all-USDC position falls further behind simply holding. In the explorer, move the later price far above your range and watch the IL keep growing. A narrower range reaches that point after a smaller price move. **Concentrated liquidity amplifies impermanent loss per dollar; it doesn't reduce it.** You're paid for this with higher fees while in range.
    """)
    return


@app.cell(hide_code=True)
def _():
    q3 = mo.ui.radio(
        options=["Only ETH", "Only USDC", "Half ETH, half USDC", "Whatever mix you deposited"],
        label="**Quick check:** you deposited into a 2,000–2,200 range when ETH was 2,100. ETH is now 2,500. What does your position hold?",
    )
    q3
    return (q3,)


@app.cell(hide_code=True)
def _(q3):
    answer_feedback(
        q3.value,
        "Only USDC",
        {
            "Only USDC": "As the price rose through 2,000–2,200, buyers took all your ETH and paid you USDC. Above 2,200 there's no ETH left to sell. You also hold less value than if you'd kept your original ETH: that's the impermanent loss.",
            "Only ETH": "Close, but the other way around. Rising prices mean traders are *buying* ETH, so the pool hands out your ETH and gives you USDC. You'd hold only ETH if the price had fallen below 2,000.",
            "Half ETH, half USDC": "A 50/50 split is v2 thinking. Once the price leaves a v3 range the position is entirely one token.",
            "Whatever mix you deposited": "The pool trades against your position as the price moves through your range, so your token mix changes. Above the range it's entirely USDC.",
        },
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Observations

    - **Uniswap v3 is a hybrid of an AMM and an order book.** Each LP effectively posts liquidity at a chosen set of prices, like orders on a book, but trades still execute against a formula, with no matching engine.
    - **Fee tiers.** Each token pair can have one pool per fee tier, and LPs choose which pool to join. v3 launched in May 2021 with **0.05%, 0.30% and 1%**. Uniswap governance added a **0.01%** tier in late 2021, aimed at stablecoin pairs. Those four are the defaults on Ethereum mainnet, but the factory contract lets governance enable more, so "v3 has three (or four) fee tiers" is a statement about defaults, not a rule. In **v4 a pool can use any fee, including a dynamic fee that a hook changes trade by trade.** Lower fee tiers suit pairs that barely move against each other (USDC/USDT): LPs there take little impermanent loss and compete on price. Volatile or obscure pairs need higher fees to compensate LPs.
    - **Active management costs time and gas.** A concentrated position only earns while in range, so LPs who want to stay in range must withdraw and re-deposit, which costs a few transactions each time. Earlier versions of this lesson blamed this on positions being NFTs; the NFT is just the receipt. The real cost is the repeated transactions and the attention needed. On Ethereum mainnet that gas has historically priced small LPs out of active management. On layer-2 networks, where v3 and v4 are also deployed, it's far cheaper, and automated "liquidity manager" vaults now rebalance positions for depositors in exchange for a fee.
    - **Sophisticated LPs earn more.** Studies of v3 found that a large share of fees goes to a small group of professional LPs, and that many passive LPs would have been better off holding. (Loesch et al., 2021, is a widely cited early example; see Sources.)
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Uniswap v4

    Uniswap v4 went live on Ethereum mainnet and several other chains in **January 2025**. It keeps v3's concentrated-liquidity math and changes what a pool can do and how it's stored.

    **Hooks.** A pool can be attached to a *hook*, an external contract that Uniswap calls at fixed points: before and after a pool is initialized, liquidity is added or removed, a swap happens, or tokens are donated to LPs. Hooks let developers customize pool behaviour without forking Uniswap. Examples:

    - **Dynamic fees:** raise the fee when the market is volatile and lower it when it's calm.
    - **Limit orders:** fill and remove a range order automatically when the price crosses it.
    - **Time-weighted average market makers (TWAMM):** spread a huge order over hours to reduce price impact.
    - **MEV protection or LP rewards:** for example, charge more to trades that look like arbitrage and pass the proceeds to LPs.

    A hook is chosen when the pool is created and can't be swapped out afterwards. It's arbitrary code, so a pool's safety now depends on its hook as well as on Uniswap's own contracts.

    **The singleton.** In v2 and v3 each pool was its own contract. In v4 every pool lives inside one contract, the `PoolManager`. Creating a pool is just a state update rather than a contract deployment, which makes it far cheaper.

    **Flash accounting.** During a sequence of actions (say, a swap through three pools), v4 only tracks how much each party owes or is owed and settles the net amounts once at the end. Tokens don't move between pools in between. This uses *transient storage*, storage that is wiped at the end of the transaction, added to Ethereum in the Dencun upgrade (March 2024, EIP-1153). Multi-hop trades get cheaper.

    **Native ETH.** v4 pools can hold ETH directly instead of requiring the wrapped ERC-20 version (WETH), saving a wrap and unwrap step.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Further reading: Uniswap": mo.md("""
    - [Introducing Uniswap V3](https://blog.uniswap.org/uniswap-v3) — the launch post with the Alice and Bob example (Uniswap Labs, March 2021).
    - [Uniswap v3 Core whitepaper](https://app.uniswap.org/whitepaper-v3.pdf) — sections 2 and 6 cover ticks and real/virtual reserves.
    - [Uniswap v3 concepts: concentrated liquidity](https://docs.uniswap.org/concepts/protocol/concentrated-liquidity) and [range orders](https://docs.uniswap.org/concepts/protocol/range-orders) — official docs.
    - [Uniswap v4 overview](https://docs.uniswap.org/contracts/v4/overview) and [hooks](https://docs.uniswap.org/contracts/v4/concepts/hooks) — official docs.
    - [Proposal: Add 1 Basis Point Fee Tier](https://gov.uniswap.org/t/proposal-add-1-basis-point-fee-tier/14745) — the governance thread that added 0.01% (2021).
    - Loesch, Hindman, Richardson & Welch, [Impermanent Loss in Uniswap v3](https://arxiv.org/abs/2111.09192) (2021).
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### DeFi Governance

    In DeFi governance, people who hold a protocol's **governance token** can propose and vote on changes to how the protocol works: fee levels, which assets a lending market accepts, how the treasury spends money, contract upgrades. Many DeFi projects use token governance to spread ownership and decision-making beyond the founding team.

    The vote doesn't just express an opinion. In a fully onchain system the winning proposal contains the exact contract calls to run, and the governance contract executes them. Whoever controls enough votes controls the protocol, including its treasury.

    #### Voting

    The usual rule is **one token, one vote**. A holder can vote **For**, **Against** or **Abstain**. Abstaining counts toward quorum (the minimum turnout a vote needs to be valid) but doesn't affect the outcome.

    One token, one vote gives large holders ("whales") most of the power. Alternatives have been proposed, such as **quadratic voting**, where $n$ tokens give you $\sqrt{n}$ votes. It has a big weakness onchain: wallets are free, so a whale can split their tokens across many addresses and get the votes back. (Splitting 1,000,000 tokens into 100 wallets turns 1,000 votes into 100 × √10,000 = 10,000.) This is called a **Sybil attack**, and it's why quadratic voting usually needs some proof that each voter is a distinct person.

    #### Proposals

    Anyone holding (or delegated) more than a **proposal threshold** of voting power can submit a proposal. A typical onchain proposal goes through these steps:
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.mermaid(
        """
    flowchart LR
        A[Proposal submitted<br/>proposer meets threshold] --> B[Voting delay<br/>voting power snapshot taken]
        B --> C[Voting period<br/>For / Against / Abstain]
        C -->|quorum met and For > Against| D[Queued in timelock<br/>e.g. 2 days]
        C -->|fails| X[Defeated]
        D --> E[Executed<br/>contract calls run]
    """
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Each step is there for a reason. The **snapshot** at the start fixes everyone's voting power, so buying or borrowing tokens after a proposal goes up doesn't help. The **timelock** gives users who disagree with a passed proposal time to withdraw their money before it takes effect.

    Proposals come in many forms: parameter changes, treasury grants, contract upgrades and non-binding "temperature checks". Many DAOs also vote **offchain** first on [Snapshot](https://docs.snapshot.box/), where votes are free signed messages rather than transactions, then run a binding onchain vote or let a multisig carry out the result.

    #### Delegation

    **Delegation** lets you give another address the right to vote with your tokens' voting power, while you keep the tokens. In the most common token standard (OpenZeppelin's `ERC20Votes`, and Compound's COMP before it) tokens don't count for anything in votes until they're delegated, even if you delegate to yourself.

    Many governance tokens are held by early investors (often venture capital funds) and the founding team. Partly because it looks bad for a handful of funds to control a "decentralized" protocol, and partly because voting well takes time, many of them delegate tokens to active, independent delegates. Student blockchain groups including Blockchain at Berkeley have been delegates in protocols such as Uniswap and Compound. Delegation also has a downside: a few delegates can end up holding a large share of all active votes.

    #### Governor contracts

    Most Ethereum DAOs run their onchain votes through a **Governor** contract, which handles proposing, voting, the timelock and execution.

    - **GovernorAlpha / GovernorBravo** were written by Compound in 2020. Uniswap and many other early DAOs copied them, and they remain in use (historical but still relevant).
    - **OpenZeppelin Governor** (2021) is a modular version of the same idea. Voting rules, quorum, counting and timelock are pluggable pieces. It's the common starting point for new DAOs today.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Governance attack sandbox

    In **April 2022** (historical), an attacker drained roughly **\$182 million** from the stablecoin protocol **Beanstalk**. They didn't exploit a bug. They borrowed about \$1 billion in assets with flash loans, used them to get a two-thirds supermajority, passed a proposal that sent the protocol's funds to themselves, and repaid the loans, all in one transaction. Beanstalk counted voting power from *current* balances, and its emergency path let a proposal that had waited 24 hours execute immediately with a supermajority.

    The sandbox below is a fictional DAO with 100 million tokens. A malicious proposal tries to send the 15M-token treasury to the attacker. Everyone except the attacker votes Against, if they vote at all.
    """)
    return


@app.cell(hide_code=True)
def _():
    gv_preset = mo.ui.dropdown(
        options=[
            "Healthy DAO",
            "Beanstalk-style (no snapshot, no timelock)",
            "Apathetic voters",
            "Quadratic voting with Sybil wallets",
        ],
        value="Beanstalk-style (no snapshot, no timelock)",
        label="Start from a scenario",
    )
    gv_preset
    return (gv_preset,)


@app.cell(hide_code=True)
def _(gv_preset):
    _presets = {
        "Healthy DAO": dict(turnout=0.30, deleg=0.75, own=1.0, flash=10.0, wallets=1, snap=True, quad=False, quorum=4.0, timelock=2),
        "Beanstalk-style (no snapshot, no timelock)": dict(turnout=0.10, deleg=0.10, own=0.5, flash=10.0, wallets=1, snap=False, quad=False, quorum=4.0, timelock=0),
        "Apathetic voters": dict(turnout=0.03, deleg=0.0, own=3.0, flash=0.0, wallets=1, snap=True, quad=False, quorum=2.0, timelock=2),
        "Quadratic voting with Sybil wallets": dict(turnout=0.30, deleg=0.75, own=3.0, flash=0.0, wallets=1, snap=True, quad=True, quorum=2.0, timelock=2),
    }
    _p = _presets[gv_preset.value]
    gv_turnout = mo.ui.slider(0, 1, step=0.01, value=_p["turnout"], label="Retail turnout (share of 2,000 small holders who vote)", show_value=True, full_width=True)
    gv_deleg = mo.ui.slider(0, 1, step=0.05, value=_p["deleg"], label="Share of investors' 40M tokens delegated to active voters", show_value=True, full_width=True)
    gv_own = mo.ui.slider(0, 10, step=0.25, value=_p["own"], label="Attacker's own tokens (millions)", show_value=True, full_width=True)
    gv_flash = mo.ui.slider(0, 10, step=0.5, value=_p["flash"], label="Tokens the attacker flash-borrows (millions, max 10M in lending pools)", show_value=True, full_width=True)
    gv_wallets = mo.ui.slider(1, 3000, step=10, value=_p["wallets"], label="Wallets the attacker splits tokens across", show_value=True, full_width=True)
    gv_snapshot = mo.ui.checkbox(value=_p["snap"], label="Count voting power from a snapshot taken when the proposal is created")
    gv_quadratic = mo.ui.checkbox(value=_p["quad"], label="Quadratic voting (each wallet gets √tokens votes)")
    gv_quorum = mo.ui.slider(0, 20, step=0.5, value=_p["quorum"], label="Quorum (millions of tokens voting For)", show_value=True, full_width=True)
    gv_timelock = mo.ui.slider(0, 7, step=1, value=_p["timelock"], label="Timelock before execution (days)", show_value=True, full_width=True)
    return (
        gv_deleg,
        gv_flash,
        gv_own,
        gv_quadratic,
        gv_quorum,
        gv_snapshot,
        gv_timelock,
        gv_turnout,
        gv_wallets,
    )


@app.cell(hide_code=True)
def _():
    mo.callout(
        mo.md("""
    **Try this**

    1. Start with the **Beanstalk-style** scenario. The flash loan passes the proposal. Now tick the **snapshot** box. Why does that alone stop it?
    2. Switch to **Apathetic voters**. No flash loan is needed: with almost nobody voting, 3M tokens is enough. Raise turnout or delegation until the attack fails.
    3. Switch to **Quadratic voting with Sybil wallets**. With one wallet the attacker loses badly. Drag *wallets* upward and find roughly where they win.
    4. Set the timelock to 0 and then to 2 days in a passing scenario, and read what changes in the outcome.
    """),
        kind="info",
    )
    return


@app.cell(hide_code=True)
def _(
    gv_deleg,
    gv_flash,
    gv_own,
    gv_quadratic,
    gv_quorum,
    gv_snapshot,
    gv_timelock,
    gv_turnout,
    gv_wallets,
):
    _holders = governance_holders()
    _r = tally_vote(
        _holders,
        retail_turnout=gv_turnout.value,
        investor_delegated=gv_deleg.value,
        attacker_own=gv_own.value * 1e6,
        flash_loan=gv_flash.value * 1e6,
        attacker_wallets=int(gv_wallets.value),
        snapshot=gv_snapshot.value,
        quadratic=gv_quadratic.value,
        quorum_tokens=gv_quorum.value * 1e6,
    )
    _unit = "votes (√tokens)" if gv_quadratic.value else "votes (tokens)"
    _df = pd.DataFrame(
        {"side": ["For (attacker)", "Against (everyone else)"], "votes": [_r["votes_for"], _r["votes_against"]]}
    )
    _chart = (
        alt.Chart(_df)
        .mark_bar(cornerRadiusEnd=4, height=28)
        .encode(
            y=alt.Y("side:N", title=None, sort=None),
            x=alt.X("votes:Q", title=_unit),
            color=alt.Color("side:N", scale=alt.Scale(domain=["For (attacker)", "Against (everyone else)"], range=[ORANGE, BLUE]), legend=None),
            tooltip=[alt.Tooltip("side:N"), alt.Tooltip("votes:Q", format=",.0f")],
        )
    )
    _labels = _chart.mark_text(align="left", dx=6).encode(text=alt.Text("votes:Q", format=",.0f"), color=alt.value("#3b3a37"))
    _chart = (_chart + _labels).properties(height=110, width="container", title="Vote tally")

    _reasons = []
    if _r["flash_counted"] > 0:
        _reasons.append(f"{_r['flash_counted'] / 1e6:.1f}M flash-borrowed tokens counted, because voting power is read from current balances.")
    elif gv_flash.value > 0:
        _reasons.append("The flash loan didn't count: the snapshot was taken before the attacker borrowed, and the loan has to be repaid in the same transaction.")
    if not _r["reached_quorum"]:
        _reasons.append(f"Only {_r['for_tokens'] / 1e6:.2f}M tokens voted For, below the {gv_quorum.value:.1f}M quorum.")
    if _r["reached_quorum"] and not _r["passes"]:
        _reasons.append("Quorum was met, but honest holders out-voted the attacker.")
    if gv_quadratic.value and gv_wallets.value > 1:
        _reasons.append(f"Splitting across {int(gv_wallets.value)} wallets multiplied the attacker's quadratic votes by √{int(gv_wallets.value)} ≈ {math.sqrt(gv_wallets.value):.1f}.")

    if _r["passes"] and gv_timelock.value == 0:
        _outcome = mo.callout(mo.md("### ❌ Proposal passes and executes immediately\nThe treasury is gone before anyone can react. " + " ".join(_reasons)), kind="danger")
    elif _r["passes"]:
        _outcome = mo.callout(
            mo.md(
                f"### ⚠️ Proposal passes, then waits {int(gv_timelock.value)} day{'s' if gv_timelock.value != 1 else ''} in the timelock\n"
                "The vote is lost, but everyone can see what's coming. Users can withdraw, and if the DAO has a guardian or cancel role it can stop execution. A timelock doesn't stop a bad vote; it buys time. "
                + " ".join(_reasons)
            ),
            kind="warn",
        )
    else:
        _outcome = mo.callout(mo.md("### ✅ Attack fails\n" + " ".join(_reasons)), kind="success")

    mo.vstack(
        [
            mo.hstack(
                [
                    mo.vstack([mo.md("**Voters**"), gv_turnout, gv_deleg]),
                    mo.vstack([mo.md("**Attacker**"), gv_own, gv_flash, gv_wallets]),
                ],
                widths="equal",
                gap=2,
            ),
            mo.hstack(
                [
                    mo.vstack([mo.md("**Rules and defences**"), gv_snapshot, gv_quadratic]),
                    mo.vstack([mo.md("&nbsp;"), gv_quorum, gv_timelock]),
                ],
                widths="equal",
                gap=2,
            ),
            _chart,
            _outcome,
        ],
        gap=1,
    )
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Assumptions and limitations of this model": mo.md("""
    - It's a fictional DAO: 2,000 retail wallets (35M tokens, a few large and many small), 4 early investors (10M each), a 15M treasury that can't vote, and 10M tokens sitting in lending pools that can be flash-borrowed.
    - Everyone who votes, other than the attacker, votes Against. In reality some honest holders miss the vote or misread the proposal.
    - Quorum counts raw tokens voting For, as in Compound's GovernorBravo (OpenZeppelin's default counts For + Abstain).
    - "Snapshot" means voting power is read at the block the proposal was created. A real attacker could buy tokens *before* proposing; only cost stops that.
    - Beanstalk's actual mechanism differed in detail: its emergency path required a two-thirds supermajority, and the flash loans bought LP tokens that were deposited for voting power. The lesson is the same.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    q4 = mo.ui.radio(
        options=[
            "A higher quorum",
            "Counting voting power from a snapshot taken before the proposal",
            "Quadratic voting",
            "A longer voting period",
        ],
        label="**Quick check:** which single defence makes flash-loaned tokens useless for voting?",
    )
    q4
    return (q4,)


@app.cell(hide_code=True)
def _(q4):
    answer_feedback(
        q4.value,
        "Counting voting power from a snapshot taken before the proposal",
        {
            "Counting voting power from a snapshot taken before the proposal": "A flash loan only exists inside one transaction. If voting power is read from an earlier block, borrowed tokens were never in the attacker's wallet at that block, so they count for nothing.",
            "A higher quorum": "A higher quorum raises the bar, but a big enough flash loan can still clear it, since it only needs to exist for one transaction.",
            "Quadratic voting": "Quadratic voting reduces whale power, but the attacker can split borrowed tokens across many wallets (try it in the sandbox), and borrowed tokens still count if balances are read live.",
            "A longer voting period": "If votes are counted from current balances, the attacker can still vote with a flash loan at any point during the period.",
        },
    )
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Further reading: governance": mo.md("""
    - [OpenZeppelin Governor documentation](https://docs.openzeppelin.com/contracts/5.x/governance) — how modern onchain governance contracts work.
    - [Compound Governance docs](https://docs.compound.finance/v2/governance/) — GovernorBravo and COMP delegation.
    - [Uniswap governance process](https://docs.uniswap.org/concepts/governance/process) — a real DAO's stages from forum post to onchain vote.
    - [Immunefi: Beanstalk governance attack analysis](https://immunefi.com/blog/bug-fix-reviews/hack-analysis-beanstalk-governance-attack-april-2022/) — step-by-step breakdown (2022).
    - Vitalik Buterin, [Moving beyond coin voting governance](https://vitalik.eth.limo/general/2021/08/16/voting3.html) (2021).
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Miner / Maximal Extractable Value

    ### Fundamentals

    Whoever builds a block decides **which transactions go in and in what order**. Before Ethereum moved to proof of stake (September 2022) that was miners, and the term was **miner extractable value**. Validators now propose blocks, so it's called **maximal extractable value (MEV)**: the profit available to whoever controls transaction ordering.

    Two facts make MEV possible:

    1. Transactions wait in the **public mempool** before they're included, and anyone can read them.
    2. The block builder chooses the order. Nothing in the protocol forces first-come, first-served.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Sanity check: why can block builders read and reorder transactions?": mo.md("""
    A transaction is a signed message, not an encrypted one. To be included it has to be broadcast to nodes, so its contents (which contract, which function, which amounts) are visible to anyone listening. The protocol only checks that each transaction in a block is valid; it doesn't care about the order. So the builder can put transactions in whatever order is most profitable for them, or add their own.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Over time, block producers and the bots working with them realized that knowing what's about to happen in a block is very profitable. The basic moves:

    | Move | What happens | Example |
    |---|---|---|
    | **Front-running** | Your transaction goes right *before* a target transaction. | Buy a token before someone's big buy order pushes the price up. |
    | **Back-running** | Your transaction goes right *after* a target transaction. | Arbitrage a price gap the target trade just created. |
    | **Sandwich attack** | One transaction before and one after the target. | Buy before a victim's swap, sell right after it. |
    | **Censorship** | Leave a target transaction out. | Since the U.S. sanctioned Tornado Cash (August 2022), some builders and relays exclude transactions touching sanctioned addresses. |

    Censoring a transaction normally means giving up its fee, so it's usually done for legal or political reasons rather than profit. (An earlier version of this lesson called it purely a "social attack"; since 2022 it's been a real policy question for Ethereum.)
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### AMM sandwich attacks

    Every trade against an AMM moves the pool's price. A buy removes ETH from an ETH/USDC pool and adds USDC, so ETH gets more expensive.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Sanity check: why does every trade move the price, and which trades move it most?": mo.md(r"""
    The pool's price is just the ratio of its reserves, $P = y/x$. Any trade changes both reserves, so it changes the ratio. Trades that are large **relative to the pool** move it most: 100 ETH barely moves a pool holding 100,000 ETH, but moves a 1,000-ETH pool a lot. Concentrated liquidity matters here too: a pool with deep liquidity near the current price absorbs big trades with less movement.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    If you know a trade is about to push the price up, you can buy just before it and sell just after it for a profit. If a trade will push the price down, you can do the reverse: sell the asset first, or use a flash loan to borrow and sell it, then buy it back cheaper.

    A **sandwich attack** does this to a specific victim. The attacker sees a pending swap in the mempool and arranges three transactions in a row:

    1. **Front-run:** the attacker buys ETH, pushing the price up.
    2. **Victim's trade:** the victim buys ETH at the worse price.
    3. **Back-run:** the attacker sells the ETH they just bought at the higher price.

    The attacker can only push the price so far. Every swap has a **slippage tolerance**, the minimum amount out the victim will accept. If the front-run is too big, the victim's trade reverts and the attacker is left holding ETH bought at a premium. So **the victim's slippage tolerance is the attacker's budget.**

    These days most sandwiches aren't run by block producers themselves but by independent bots called **searchers**, who pay builders to include their transactions in the right order (see *Flashbots* below).

    The simulator below runs real constant-product math. It also compares the different ways transaction ordering has worked on Ethereum.
    """)
    return


@app.cell(hide_code=True)
def _():
    sw_pool = mo.ui.slider(200, 20_000, step=100, value=1000, label="Pool depth (ETH in pool; USDC side = 3,000× this)", show_value=True, full_width=True)
    sw_victim = mo.ui.slider(1_000, 500_000, step=1_000, value=50_000, label="Victim's trade (USDC spent buying ETH)", show_value=True, full_width=True)
    sw_slip = mo.ui.slider(0.1, 5.0, step=0.1, value=1.0, label="Victim's slippage tolerance (%)", show_value=True, full_width=True)
    sw_fee = mo.ui.dropdown(options={"0.05%": 0.0005, "0.30%": 0.003, "1.00%": 0.01}, value="0.30%", label="Pool fee")
    sw_gas = mo.ui.slider(0, 50, step=1, value=5, label="Gas cost per transaction (USD)", show_value=True, full_width=True)
    sw_comp = mo.ui.slider(0, 99, step=1, value=90, label="Share of profit searchers bid away to win the block (%)", show_value=True, full_width=True)
    sw_searchers = mo.ui.slider(1, 10, step=1, value=4, label="Competing searchers", show_value=True, full_width=True)
    return sw_comp, sw_fee, sw_gas, sw_pool, sw_searchers, sw_slip, sw_victim


@app.cell(hide_code=True)
def _():
    mo.callout(
        mo.md("""
    **Sandwich simulator: try this**

    1. **Predict first:** if the victim doubles their slippage tolerance from 1% to 2%, does the attacker's profit roughly double, stay the same, or something else? Then try it.
    2. Make the pool much deeper (10,000+ ETH). Why does the attack become unprofitable?
    3. Lower the slippage tolerance until the attack stops paying for its gas.
    4. Compare the three ordering systems in the bar chart at the bottom. Which changes the *victim's* outcome, and which only changes who gets the attacker's profit?
    """),
        kind="info",
    )
    return


@app.cell(hide_code=True)
def _(sw_fee, sw_gas, sw_pool, sw_slip, sw_victim):
    sw_E = float(sw_pool.value)
    sw_U = sw_E * 3000.0
    sw_args = (sw_E, sw_U, float(sw_victim.value), sw_slip.value / 100, sw_fee.value)
    sw_best_a = max_safe_frontrun(*sw_args)
    sw_best = run_sandwich(*sw_args, sw_best_a)
    sw_net = sw_best["gross_profit"] - 2 * sw_gas.value
    sw_attack_happens = sw_net > 0
    sw_clean = run_sandwich(*sw_args, 0.0)
    return sw_E, sw_U, sw_args, sw_attack_happens, sw_best, sw_best_a, sw_clean, sw_net


@app.cell(hide_code=True)
def _(sw_args, sw_best_a, sw_gas):
    _grid = np.linspace(0, max(sw_best_a * 1.6, 1.0), 160)
    _rows = []
    for _a in _grid:
        _r = run_sandwich(*sw_args, float(_a))
        _rows.append(
            {
                "frontrun": _a,
                "profit": _r["gross_profit"] - 2 * sw_gas.value,
                "status": "Victim's trade goes through" if _r["victim_ok"] else "Victim's trade reverts",
            }
        )
    _df = pd.DataFrame(_rows)
    _line = (
        alt.Chart(_df)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("frontrun:Q", title="Attacker's front-run size (USDC)"),
            y=alt.Y("profit:Q", title="Attacker profit after gas (USDC)"),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=["Victim's trade goes through", "Victim's trade reverts"], range=[BLUE, ORANGE]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[alt.Tooltip("frontrun:Q", format=",.0f"), alt.Tooltip("profit:Q", format=",.2f"), "status:N"],
        )
    )
    _zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=MUTED).encode(y="y:Q")
    _best = alt.Chart(pd.DataFrame({"x": [sw_best_a]})).mark_rule(strokeDash=[4, 3], color="#0b0b0b").encode(x="x:Q")
    sw_profit_chart = (_zero + _line + _best).properties(
        height=230, width="container", title="Profit grows with the front-run until the victim's slippage limit (dashed line)"
    )
    return (sw_profit_chart,)


@app.cell(hide_code=True)
def _(sw_best):
    _rows = []
    for _name, _in, _out, _E, _U in sw_best["steps"]:
        _rows.append(
            {
                "Step": _name,
                "Paid in": f"{_in:,.2f} {'USDC' if 'buys' in _name else 'ETH' if 'sells' in _name else ''}".strip(),
                "Received": f"{_out:,.4f} {'ETH' if 'buys' in _name else 'USDC' if 'sells' in _name else ''}".strip(),
                "Pool ETH": f"{_E:,.3f}",
                "Pool USDC": f"{_U:,.0f}",
                "Pool price": f"{_U / _E:,.2f}",
            }
        )
    sw_step_table = pd.DataFrame(_rows)
    sw_step = mo.ui.slider(1, len(_rows) - 1, step=1, value=len(_rows) - 1, label="Show the block up to step", show_value=True)
    return sw_step, sw_step_table


@app.cell(hide_code=True)
def _(
    sw_attack_happens,
    sw_best,
    sw_best_a,
    sw_clean,
    sw_comp,
    sw_fee,
    sw_gas,
    sw_net,
    sw_pool,
    sw_profit_chart,
    sw_searchers,
    sw_slip,
    sw_step,
    sw_step_table,
    sw_victim,
):
    _quote_eth = sw_clean["quote"]
    _victim_eth = sw_best["victim_eth"] if sw_attack_happens else _quote_eth
    _loss_eth = _quote_eth - _victim_eth
    _loss_usd = _loss_eth * sw_victim.value / _quote_eth
    _summary = (
        mo.md(
            f"""
    The victim was quoted **{_quote_eth:,.4f} ETH** and accepts no less than **{sw_best['min_out']:,.4f} ETH** ({sw_slip.value:.1f}% slippage).
    The best front-run is **{sw_best_a:,.0f} USDC**. The victim ends up with **{_victim_eth:,.4f} ETH**, **{_loss_eth:,.4f} ETH (≈ \\${_loss_usd:,.2f}) less** than quoted.
    The attacker makes **\\${sw_best['gross_profit']:,.2f}** before gas and **\\${sw_net:,.2f}** after paying for two transactions.
    """
        )
        if sw_attack_happens
        else mo.callout(
            mo.md(
                f"**No profitable sandwich.** The best possible front-run makes \\${sw_best['gross_profit']:,.2f}, which doesn't cover \\${2 * sw_gas.value:,.0f} of gas. "
                "Either the slippage tolerance is too tight, the pool is too deep, or the fees eat the profit. The victim gets their full quote."
            ),
            kind="success",
        )
    )
    mo.vstack(
        [
            mo.hstack(
                [
                    mo.vstack([mo.md("**The trade**"), sw_victim, sw_slip, sw_pool, sw_fee]),
                    mo.vstack([mo.md("**The attacker's costs and competition**"), sw_gas, sw_comp, sw_searchers]),
                ],
                widths="equal",
                gap=2,
            ),
            _summary,
            sw_profit_chart,
            mo.md("**Step through the block.** Each row is one transaction, in the order the builder placed it."),
            sw_step,
            mo.Html(sw_step_table.iloc[: sw_step.value + 1].to_html(index=False, border=0)),
        ],
        gap=1,
    )
    return


@app.cell(hide_code=True)
def _(sw_E, sw_U, sw_attack_happens, sw_best, sw_clean, sw_comp, sw_fee, sw_gas, sw_net, sw_searchers, sw_victim):
    _quote = sw_clean["quote"]
    _usd_per_eth = sw_victim.value / _quote
    _victim_loss = (_quote - sw_best["victim_eth"]) * _usd_per_eth if sw_attack_happens else 0.0
    _bid = max(sw_net, 0) * sw_comp.value / 100
    _kept = max(sw_net, 0) - _bid
    _losers_gas = (sw_searchers.value - 1) * sw_gas.value if sw_attack_happens else 0.0

    # Private RPC with refunds: no sandwich; searchers back-run the victim's trade.
    _E1 = sw_E - _quote
    _U1 = sw_U + sw_victim.value
    _backrun = max(backrun_arbitrage(_E1, _U1, 3000.0, sw_fee.value) - sw_gas.value, 0.0)
    _refund = 0.9 * _backrun

    _regimes = [
        ("Public mempool, gas auction (before ~2021)", _victim_loss, _kept, _bid),
        ("Public mempool via MEV-Boost (today's default)", _victim_loss, _kept, _bid),
        ("Private RPC with back-run refunds", -_refund, 0.0, _backrun - _refund),
    ]
    _rows = []
    for _name, _vl, _sk, _bp in _regimes:
        _rows += [
            {"regime": _name, "who": "Victim's loss (negative = refund)", "usd": _vl},
            {"regime": _name, "who": "Searcher keeps", "usd": _sk},
            {"regime": _name, "who": "Block producer receives", "usd": _bp},
        ]
    _df = pd.DataFrame(_rows)
    _order = ["Victim's loss (negative = refund)", "Searcher keeps", "Block producer receives"]
    _chart = (
        alt.Chart(_df)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("who:N", title=None, sort=_order, axis=alt.Axis(labels=False, ticks=False)),
            x=alt.X("usd:Q", title="USD"),
            color=alt.Color("who:N", scale=alt.Scale(domain=_order, range=[ORANGE, BLUE, AQUA]), legend=alt.Legend(orient="top", title=None)),
            row=alt.Row("regime:N", title=None, sort=[r[0] for r in _regimes], header=alt.Header(labelAngle=0, labelAlign="left", labelFontWeight="bold")),
            tooltip=["regime:N", "who:N", alt.Tooltip("usd:Q", format=",.2f")],
        )
        .properties(height=70, width=520)
    )
    mo.vstack(
        [
            mo.md(r"""
    #### Same trade, three ways of ordering transactions

    The bars split the value from this one trade between the victim, the searcher and whoever produces the block. *Share bid away* decides how much of the searcher's profit goes to the block producer. The victim's loss is bigger than the other two bars combined: the difference goes to the pool's LPs as trading fees on the attacker's two trades, and to gas.
    """),
            _chart,
            mo.md(
                f"""
    - **Public mempool, gas auction (historical).** Searchers fought by raising gas prices in public. Only one can win; the other {sw_searchers.value - 1} still paid gas for transactions that failed onchain (≈ \\${_losers_gas:,.0f} wasted here), and the bidding drove up gas for everyone else.
    - **Public mempool via MEV-Boost (today).** The victim loses the same amount. What changes is that searchers bid privately in sealed bundles, so losing bids cost nothing and don't clog the chain. The profit goes mostly to the builder and proposer instead of being burned as wasted gas.
    - **Private RPC with refunds.** The victim sends their trade to a private endpoint such as Flashbots Protect or MEV Blocker instead of the public mempool. Searchers can't see it in time to front-run it; they can only bid to **back-run** it, arbitraging the pool back to the market price. MEV Blocker pays 90% of that back-run's value to the user. Here that's a **\\${_refund:,.2f} refund** instead of a \\${_victim_loss:,.2f} loss.
    """
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Assumptions and limitations of this model": mo.md("""
    - **One pool, constant product (Uniswap v2 math).** A v3 pool behaves the same way inside one bucket; across buckets the numbers change but the logic doesn't.
    - **The external ETH price stays at 3,000.** The back-run in the private-RPC case trades the pool back to that price.
    - **The attacker picks the largest front-run that keeps the victim's trade valid.** In this model profit always rises with front-run size up to that limit; real attackers solve the same problem.
    - **"Share bid away" is a single input.** Real bids depend on how many searchers spot the same opportunity; competitive opportunities often see over 90% bid away.
    - **The private-RPC case assumes the private endpoint keeps the trade private** and that a searcher back-runs it. Smaller trades may get no back-run and therefore no refund.
    - **The gas auction and MEV-Boost cases are shown with the same victim loss on purpose.** They differ in where the money goes and in wasted block space, not in what the victim pays.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    q5 = mo.ui.radio(
        options=[
            "Setting a tight slippage tolerance",
            "Sending the trade through a private RPC",
            "Trading through a batch auction such as CoW Swap",
            "Paying a higher gas fee",
        ],
        label="**Quick check:** which of these does **not** protect a swap from being sandwiched?",
    )
    q5
    return (q5,)


@app.cell(hide_code=True)
def _(q5):
    answer_feedback(
        q5.value,
        "Paying a higher gas fee",
        {
            "Paying a higher gas fee": "A higher fee only buys you priority. The attacker sees it and simply places their front-run ahead of you and their back-run behind you in the same bundle. The other three either shrink the attacker's budget (tight slippage) or hide your trade from them (private RPC, batch auction).",
            "Setting a tight slippage tolerance": "This one does help: slippage tolerance is the attacker's budget. Try lowering it in the simulator. The trade-off is that your trade reverts more often in volatile markets.",
            "Sending the trade through a private RPC": "This does help: if your trade never appears in the public mempool, searchers can't build a sandwich around it.",
            "Trading through a batch auction such as CoW Swap": "This does help: orders in a batch all settle at the same price, so there's no 'before' and 'after' to exploit inside the batch.",
        },
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Just-in-time (JIT) liquidity

    LPs normally carry impermanent loss risk for as long as their liquidity sits in the pool. A **JIT liquidity provider** avoids almost all of it:

    1. They spot a large swap in the mempool.
    2. Right before it, they add a big concentrated position around the current price.
    3. The swap executes, mostly against their liquidity, and they collect most of the fee.
    4. Right after, they withdraw.

    They hold the position for one block, so the price has no time to move against them beyond the swap itself. JIT is mostly seen on Uniswap v3, because concentrated liquidity lets a single position dominate the active bucket. The swapper isn't hurt (they get a better price thanks to the extra liquidity), but the pool's regular LPs lose most of that trade's fees.

    #### Liquidation front-running

    In lending protocols, whoever first calls `liquidate` on an undercollateralized loan collects the liquidation bonus. If a searcher sees someone else's liquidation transaction in the mempool, they can copy it and put theirs first, taking the bonus.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Sanity check: a builder sees an oracle price update that will push a loan below its collateral requirement. What can they do?": mo.md("""
    **Back-run** the oracle update. The loan isn't liquidatable until the new price is onchain, so a liquidation placed *before* the update would fail. Placed directly *after* it in the same block, the liquidation succeeds and the searcher is first in line for the bonus. This is why liquidations are such a competitive MEV category: everyone watches the same oracles.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### Arbitrage

    Ordinary arbitrage reacts to prices after a trade has happened: someone notices one market is cheaper than another, then trades. If you can see a trade *before* it's included, you know exactly what price gap it will create, and you can place your arbitrage directly behind it in the same block (a back-run). The market is back in line by the end of the block.

    **Worked example (from this lesson's slides).** An ETH/USDC pool holds 4,500 ETH and 10,000,000 USDC, so ETH costs 10,000,000 ÷ 4,500 ≈ \$2,222. Someone swaps 1,000,000 USDC for ETH (no fees, for simplicity). Now the pool holds 11,000,000 USDC and $45{,}000{,}000{,}000 \div 11{,}000{,}000 \approx 4{,}091$ ETH, so ETH costs about \$2,689 in this pool. If ETH is still \$2,222 elsewhere (say, on another chain or exchange), an arbitrageur buys ETH there and sells it into this pool until the two prices meet. The same numbers show how valuable it is to see that 1M swap coming: a searcher who buys before it and sells after it is running exactly the sandwich from the simulator.

    #### Generalized front-running

    Early MEV bots looked for specific patterns, like a big AMM trade to sandwich. **Generalized front-runners** don't need to understand the transaction at all:

    1. Take any pending transaction.
    2. Simulate it with the bot's own address as the sender.
    3. If the copy makes money, submit it with a higher priority fee so it lands first.

    More advanced bots simulate *internal* calls too. Say you write a contract only you can call, which calls a lending protocol to perform a liquidation. Copying your outer transaction fails because only you can call your contract, but a smarter bot spots the inner liquidation call and makes it directly. The block builder often includes your original transaction as well, which now does nothing useful, and still collects your fee.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Further reading: MEV fundamentals": mo.md("""
    - Daian et al., [Flash Boys 2.0](https://arxiv.org/abs/1904.05234) (2019) — the paper that named MEV and documented gas auctions.
    - [ethereum.org: Maximal extractable value](https://ethereum.org/en/developers/docs/mev/) — maintained overview with examples.
    - Robinson & Konstantopoulos, [Ethereum is a Dark Forest](https://www.paradigm.xyz/2020/08/ethereum-is-a-dark-forest) (2020) — a first-hand generalized front-running story.
    - [Uniswap docs: JIT liquidity](https://docs.uniswap.org/concepts/protocol/concentrated-liquidity) and [MEV Blocker docs](https://docs.cow.fi/mevblocker) — the protection and refund mechanism used in the simulator.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Priority Gas Auctions

    *This section is mostly historical: it describes Ethereum before Flashbots (2020–21). The incentives it describes still matter.*

    At first, only miners could reliably profit from transaction ordering, because only they controlled it. Then other people found they could steer where their transactions landed by bidding.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Sanity check: in what order should a block producer put transactions to make the most money? (Hint: each block has a gas limit)": mo.md("""
    By fee per unit of gas, highest first. Block space is capped by the gas limit, so the producer wants the most fee per unit of space. Since EIP-1559 (August 2021) the base fee is burned, so the producer only keeps the **priority fee** (tip): sort by tip per gas. That's the default ordering in Ethereum clients, and exactly what gas auctions exploited.
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Because miners sorted by gas price, a bot that wanted to be **right before** a target transaction could broadcast with a slightly *higher* gas price, and one that wanted to be **right after** could try a slightly *lower* one (less reliable, since other transactions could slip between). The people running these bots came to be called **searchers**.

    When several searchers spotted the same opportunity, they bid against each other in the open, re-broadcasting with higher and higher gas prices within seconds. This was named a **priority gas auction (PGA)**.

    **Problems with PGAs**

    - **Wasted block space.** Every losing bid still landed onchain as a failed or useless transaction that paid gas.
    - **Gas spikes.** Bidding wars pushed gas prices up for everyone. Ordinary users were priced out or overpaid.
    - **Consensus risk.** When one block's MEV is worth much more than the block reward, a miner is tempted to *re-org* the chain (re-mine a recent block) to capture it, which threatens finality.

    You saw the first two in the simulator: the gas-auction scenario charges losing searchers for failed transactions.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Flashbots

    **Flashbots** is a research and development organization focused on MEV. Its first major product, **Flashbots Auction** (launched January 2021, *historical*), moved the gas-auction bidding off the public chain:

    - **Searchers** send **bundles**, ordered lists of transactions that must execute together in exactly that order or not at all. A bundle can include other people's transactions from the mempool (that's how a sandwich bundle is built).
    - Each bundle carries a bid, paid to the block producer either through gas or a direct ETH transfer, and only if the bundle is included.
    - **Miners** ran a modified client (`mev-geth`) that merged the most profitable bundles into their blocks alongside normal mempool transactions.
    - Losing bundles never land onchain, so failed bids cost nothing.

    Miners in that system *could* see the bundles they received; what stopped them from stealing a searcher's strategy was reputation and the risk of being cut off from future bundles. (An earlier version of this lesson said bundle contents were hidden from miners.) Flashbots reported that miners controlling the large majority of Ethereum's hash rate had joined by 2021.

    Flashbots also offered a way for ordinary users to send transactions privately, so that they never entered the public mempool. Today's version is **Flashbots Protect**.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    #### After the Merge: proposer–builder separation

    In proof of stake there are no miners. Ethereum's **validators** take turns proposing blocks, and most of them don't build their own. Since September 2022 the dominant setup has been **MEV-Boost**, open-source software from Flashbots that implements **proposer–builder separation (PBS)**:
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.mermaid(
        """
    flowchart LR
        U[Users] -->|public mempool| S[Searchers]
        U -->|private RPC| B
        S -->|bundles + bids| B[Builders<br/>assemble whole blocks]
        B -->|block + bid| R[Relays<br/>check blocks, hide contents]
        R -->|header + bid only| P[Proposer<br/>validator picks highest bid]
        P -->|signs header| R
        R -->|full block published| N[Ethereum]
    """
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    1. **Searchers** find opportunities and send bundles to builders.
    2. **Builders** combine bundles and ordinary transactions into the most valuable block they can, and bid for the right to have it proposed.
    3. **Relays** sit in the middle. They check that blocks are valid and pay what they promise, and they show the proposer only the block *header* and the bid, not the transactions.
    4. The **proposer** signs the header with the highest bid without seeing what's inside. Only then is the full block revealed. This commit-then-reveal step is what actually stops proposers from stealing MEV.

    **Effects.** Anyone can now compete for MEV, not just block producers. Most MEV revenue ends up with validators, because builders bid against each other. Solo stakers earn about the same as large operators. When someone today says they're "doing MEV", they're most likely a searcher watching the mempool and sending bundles.

    **New problems.** MEV-Boost has been used for roughly 90% of Ethereum blocks in recent measurements (check [relayscan.io](https://www.relayscan.io/) for current numbers). A handful of builders produce most of those blocks, and a handful of relays carry them, which concentrates trust. Some builders and relays exclude transactions linked to sanctioned addresses. Ethereum researchers have proposed building PBS into the protocol itself, *enshrined PBS* ([EIP-7732](https://eips.ethereum.org/EIPS/eip-7732)), to remove the reliance on relays; it's slated for a future network upgrade, so check its status before relying on it.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Further reading: Flashbots and PBS": mo.md("""
    - [Flashbots docs: MEV-Boost](https://docs.flashbots.net/flashbots-mev-boost/introduction) and [Flashbots Protect](https://docs.flashbots.net/flashbots-protect/overview).
    - [ethereum.org: Proposer-builder separation](https://ethereum.org/en/roadmap/pbs/).
    - [Flashbots: MEV-Boost in a nutshell](https://boost.flashbots.net/) — the software and its relay list.
    - [relayscan.io](https://www.relayscan.io/) and [mevwatch.info](https://www.mevwatch.info/) — live data on relays, builders and censorship.
    - [EIP-7732: Enshrined Proposer-Builder Separation](https://eips.ethereum.org/EIPS/eip-7732).
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Bad vs Good MEV?

    For a long time MEV was simply seen as bad: it raised gas costs, gave users worse prices, destabilized the network and pushed users to bribe block producers. Most people now split it into two groups by who it affects.

    **Usually harmful:** sandwich attacks, oracle manipulation and liquidation front-running. They take value from a specific user or protocol and pass it to the searcher and block producer without improving anything.

    **Often useful:**

    - **Arbitrage** keeps prices consistent across markets. Without it, AMM prices would drift away from the real market. (The cost lands on LPs, who are the ones being arbitraged.)
    - **Liquidations** (including back-running an oracle update) close risky loans quickly, before they become bad debt.
    - **JIT liquidity** gives traders a better price, though it takes fees from regular LPs.

    Some researchers argue that even sandwiching does useful work, by routing trades toward the deepest pools. It's a minority view, and in practice sandwiches mostly cost users who set loose slippage. Another response to MEV is to **give it back to users**: order-flow auctions like MEV Blocker and Flashbots' MEV-Share sell the right to back-run your transaction and refund most of the proceeds to you, as in the simulator.

    Sort each kind below and check your reasoning.
    """)
    return


@app.cell(hide_code=True)
def _():
    _opts = ["Usually harmful", "Often useful", "Mixed"]
    mev_sort = mo.ui.dictionary(
        {
            "Sandwiching a retail swap": mo.ui.dropdown(_opts, label="Sandwiching a retail swap"),
            "Back-running a big trade to re-align prices": mo.ui.dropdown(_opts, label="Back-running a big trade to re-align prices"),
            "JIT liquidity on a large swap": mo.ui.dropdown(_opts, label="JIT liquidity on a large swap"),
            "Copying someone's liquidation and going first": mo.ui.dropdown(_opts, label="Copying someone's liquidation and going first"),
            "Liquidating a loan right after an oracle update": mo.ui.dropdown(_opts, label="Liquidating a loan right after an oracle update"),
        }
    )
    mev_sort
    return (mev_sort,)


@app.cell(hide_code=True)
def _(mev_sort):
    _key = {
        "Sandwiching a retail swap": ("Usually harmful", "The victim gets a worse price and nobody else benefits."),
        "Back-running a big trade to re-align prices": ("Often useful", "It brings the pool back in line with other markets. LPs pay for it, but traders get accurate prices."),
        "JIT liquidity on a large swap": ("Mixed", "The swapper gets a better price, but the pool's regular LPs lose most of that trade's fees."),
        "Copying someone's liquidation and going first": ("Usually harmful", "The liquidation happens either way; this only moves the reward from the person who found it to a copier."),
        "Liquidating a loan right after an oracle update": ("Often useful", "It removes a risky loan at the earliest possible moment, protecting lenders from bad debt."),
    }
    _answered = {k: v for k, v in mev_sort.value.items() if v}
    if not _answered:
        _out = mo.md("<small>Pick an answer for each to see feedback.</small>")
    else:
        _lines = []
        for _k, _v in _answered.items():
            _right, _why = _key[_k]
            _mark = "✅" if _v == _right else "❌"
            _lines.append(f"- {_mark} **{_k}**: {_right.lower()}. {_why}")
        _score = sum(1 for _k, _v in _answered.items() if _v == _key[_k][0])
        _out = mo.callout(mo.md(f"**{_score} / {len(_answered)} correct so far.**\n\n" + "\n".join(_lines)), kind="neutral")
    _out
    return


@app.cell(hide_code=True)
def _():
    mo.accordion(
        {
            "Further reading: MEV and its effects": mo.md("""
    - [Flashbots: MEV-Share](https://docs.flashbots.net/flashbots-mev-share/introduction) and [MEV Blocker: order flow auction](https://docs.cow.fi/mevblocker/concepts/order-flow-auction) — returning MEV to users.
    - Milionis, Moallemi, Roughgarden & Zhang, [Automated Market Making and Loss-Versus-Rebalancing](https://arxiv.org/abs/2208.06046) (2022) — how much LPs lose to arbitrage.
    - [CoW Protocol docs: batch auctions](https://docs.cow.fi/cow-protocol/concepts/introduction/batch-auctions).
    """)
        }
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Key takeaways

    - **Concentrated liquidity trades range for efficiency.** A narrower range gives more liquidity per dollar and more fees while in range, but it leaves the range sooner and takes larger impermanent loss over the same price move.
    - **Capital efficiency depends on the current price and both bounds**: $2\sqrt{P} / (2\sqrt{P} - \sqrt{p_a} - P/\sqrt{p_b})$. Uniswap's own example (1,000–2,250 at 1,500) gives about 5.45×.
    - **Ticks are 0.01% price steps** ($p = 1.0001^i$). Swaps move through buckets of liquidity and cross ticks when a bucket runs out.
    - **Out of range, a position is entirely one token**, the one that did worse. That makes range orders possible, and it's also why IL keeps growing.
    - **Uniswap v4 adds programmability (hooks) and cheaper accounting (singleton, flash accounting)**, at the cost of trusting each pool's hook code.
    - **Governance is only as strong as how voting power is measured.** Snapshots stop flash loans, quorum and turnout stop cheap takeovers, and timelocks give users time to leave.
    - **MEV comes from controlling transaction order.** A sandwich attacker's budget is the victim's slippage tolerance.
    - **Ordering moved from miners and public gas auctions to proposer–builder separation.** That cut wasted gas and spread MEV to validators, but concentrated power in a few builders and relays.
    - **Some MEV is a cost (sandwiches, copied liquidations); some keeps markets working (arbitrage, timely liquidations).** Private RPCs and order-flow auctions let users avoid the first kind or get paid for the second.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Homework

    *The homework section (guided coding, short questions and the onchain completion record) is added in Phase 3.*
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Sources

    Accessed November 2026. Facts that change over time are dated in the text.

    **Uniswap**
    - Uniswap Labs, [Introducing Uniswap V3](https://blog.uniswap.org/uniswap-v3) (March 2021) — Alice and Bob example, launch fee tiers.
    - Adams et al., [Uniswap v3 Core whitepaper](https://app.uniswap.org/whitepaper-v3.pdf) (2021) — ticks (§6.1), real reserves (eq. 2.2), token amounts (§6.2.3).
    - [Uniswap docs: concentrated liquidity](https://docs.uniswap.org/concepts/protocol/concentrated-liquidity), [range orders](https://docs.uniswap.org/concepts/protocol/range-orders), [fees](https://docs.uniswap.org/concepts/protocol/fees).
    - [Uniswap governance forum: Add 1 Basis Point Fee Tier](https://gov.uniswap.org/t/proposal-add-1-basis-point-fee-tier/14745) (2021).
    - [Uniswap v4 docs: overview](https://docs.uniswap.org/contracts/v4/overview), [hooks](https://docs.uniswap.org/contracts/v4/concepts/hooks), [flash accounting](https://docs.uniswap.org/contracts/v4/concepts/flash-accounting); [EIP-1153 transient storage](https://eips.ethereum.org/EIPS/eip-1153).
    - Loesch et al., [Impermanent Loss in Uniswap v3](https://arxiv.org/abs/2111.09192) (2021).

    **Governance**
    - [OpenZeppelin Governor docs](https://docs.openzeppelin.com/contracts/5.x/governance); [Compound governance docs](https://docs.compound.finance/v2/governance/); [Uniswap governance process](https://docs.uniswap.org/concepts/governance/process).
    - Immunefi, [Hack Analysis: Beanstalk Governance Attack, April 2022](https://immunefi.com/blog/bug-fix-reviews/hack-analysis-beanstalk-governance-attack-april-2022/).
    - V. Buterin, [Moving beyond coin voting governance](https://vitalik.eth.limo/general/2021/08/16/voting3.html) (2021).

    **MEV**
    - Daian et al., [Flash Boys 2.0](https://arxiv.org/abs/1904.05234) (2019).
    - [ethereum.org: MEV](https://ethereum.org/en/developers/docs/mev/) and [proposer-builder separation](https://ethereum.org/en/roadmap/pbs/).
    - [Flashbots docs](https://docs.flashbots.net/) — Flashbots Auction (historical), MEV-Boost, Protect, MEV-Share.
    - [MEV Blocker docs: order flow auction](https://docs.cow.fi/mevblocker/concepts/order-flow-auction) — 90% back-run refund.
    - [relayscan.io](https://www.relayscan.io/), [mevwatch.info](https://www.mevwatch.info/) — live MEV-Boost and censorship data.
    - [EIP-7732: Enshrined PBS](https://eips.ethereum.org/EIPS/eip-7732); [EIP-1559](https://eips.ethereum.org/EIPS/eip-1559).
    - Original Week 6 slides: *arbitrage mev* (Blockchain at Berkeley) — the 4,500 ETH / 10M USDC worked example.
    """)
    return


if __name__ == "__main__":
    app.run()
