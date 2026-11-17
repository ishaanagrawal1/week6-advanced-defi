# Content update log

Changes from the original Notion lesson, *Week 6 - Advanced DeFi*. Sources accessed November 2026.

## Corrections

| # | Section | Original | Change | Source |
|---|---|---|---|---|
| 1 | Concentrated liquidity | Bob uses a 1,000–2,500 range with \$183.5k and earns 6.3× | Uniswap's example is 1,000–**2,250** at a price of 1,500, which gives ≈ **5.45×**. With 2,500, Bob would need ≈ \$204k (4.89×). The interactive checker shows both. | [Uniswap v3 launch post](https://blog.uniswap.org/uniswap-v3) |
| 2 | Concentrated liquidity | Efficiency = 115.5 "sqrt-price units" ÷ (√2500 − √1000) | Removed. A full range is infinite in √p, and efficiency depends on the current price. Replaced with 2√P / (2√P − √pa − P/√pb), derived in *Real and virtual reserves*. | [v3 whitepaper](https://app.uniswap.org/whitepaper-v3.pdf) §2, §6.2.3 |
| 3 | Concentrated liquidity | "Fees in concentrated liquidity are much higher than normal liquidity" | The fee *rate* is the same; a concentrated LP earns more *per dollar* while in range. | Uniswap docs: [fees](https://docs.uniswap.org/concepts/protocol/fees) |
| 4 | Ticks | p(i) = 1.0001^(i/2); "each tick is the square root of 0.01% away" | p(i) = 1.0001^i, so each tick is 0.01% apart. √p(i) = 1.0001^(i/2). | v3 whitepaper §6.1 |
| 5 | Real and virtual reserves | "x_v·y_v = k and x·y = L²"; "Let L² be the amount of liquidity" | L is the liquidity and L² plays the role of k. **Virtual** reserves satisfy x_v·y_v = L²; **real** reserves do not. Added the general x_v = L/√P, y_v = L√P and the real-reserve formulas. | v3 whitepaper eq. 2.2 |
| 6 | Limit order | Price above 2,200 in a USDC-ETH pool → "entirely DAI" | Entirely **USDC** (typo). | — |
| 7 | Limit order | Going out of range "has the effect of minimizing impermanent loss" | Reversed. Out of range you're fully in the worse-performing token and IL keeps growing; concentration amplifies IL per dollar. The explorer shows this, and shows that in-range IL scales by exactly the capital-efficiency factor. | v3 whitepaper; [Loesch et al. 2021](https://arxiv.org/abs/2111.09192) |
| 8 | Observations | "three fee tiers – 0.05%, 0.3%, 1%" | 0.01% was added by governance in late 2021. Governance can enable more tiers. v4 allows any fee, including dynamic fees via hooks. Added a tick-spacing table. | [Uniswap governance: 1 bp fee tier](https://gov.uniswap.org/t/proposal-add-1-basis-point-fee-tier/14745); [v4 docs](https://docs.uniswap.org/contracts/v4/overview) |
| 9 | Observations | Management is gas-intensive "as the liquidity is represented as an NFT" | The cost comes from repeated withdraw/re-deposit transactions, not the NFT. Added L2 deployments and automated liquidity managers. | Uniswap docs |
| 10 | Governor contracts | "Most Ethereum governance is conducted using … GovernorBravo" | GovernorBravo is marked historical but still in use; OpenZeppelin Governor is the common modern base. | [OpenZeppelin Governor](https://docs.openzeppelin.com/contracts/5.x/governance), [Compound docs](https://docs.compound.finance/v2/governance/) |
| 11 | MEV fundamentals | Framed around miners throughout | Updated for proof of stake (validators, proposers, builders, searchers since Sept 2022). Miner-era material is labelled historical. | [ethereum.org MEV](https://ethereum.org/en/developers/docs/mev/) |
| 12 | MEV fundamentals | Censorship is "more of a social attack" | Added the post-August-2022 OFAC/Tornado Cash context: censorship by some builders and relays. | [mevwatch.info](https://www.mevwatch.info/) |
| 13 | Sandwich attacks | "minders"; implies only miners sandwich | Typo fixed. Searchers run most sandwiches. Explained that slippage tolerance caps the attack. | [Flash Boys 2.0](https://arxiv.org/abs/1904.05234) |
| 14 | Flashbots | "The contents of the bundle are not revealed to the miner" | In Flashbots Auction (mev-geth), miners could see bundles; trust was reputational. Content hiding came with MEV-Boost relays, where proposers sign only a header. | [Flashbots docs](https://docs.flashbots.net/) |
| 15 | Flashbots | "90% of miners … as of late 2021" | Kept, labelled historical. Added MEV-Boost (~90% of blocks in recent measurements, with a link to live data), builder/relay concentration and enshrined PBS (EIP-7732). | [relayscan.io](https://www.relayscan.io/), [EIP-7732](https://eips.ethereum.org/EIPS/eip-7732), [ethereum.org PBS](https://ethereum.org/en/roadmap/pbs/) |
| 16 | Priority gas auctions | Ordering by gas price | Labelled historical. Noted that EIP-1559 (Aug 2021) means ordering is by priority fee. | [EIP-1559](https://eips.ethereum.org/EIPS/eip-1559) |
| 17 | Bad vs good MEV | Sandwiching "can act as a form of routing" stated without attribution | Labelled a minority view. Added order-flow auctions (MEV Blocker, MEV-Share) that refund users. | [MEV Blocker docs](https://docs.cow.fi/mevblocker/concepts/order-flow-auction), [MEV-Share](https://docs.flashbots.net/flashbots-mev-share/introduction) |

## Additions

| Section | Addition | Source |
|---|---|---|
| Intro | Learning objectives, how to use the notebook, glossary of terms from earlier weeks | — |
| Uniswap v3 | Launch date (May 2021). Why positions are NFTs (non-fungible ranges). | Uniswap v3 launch post |
| Ticks | Tick spacing per fee tier; tick calculator; note about token decimals | [Uniswap support: price to tick](https://support.uniswap.org/hc/en-us/articles/21068898875661-How-to-convert-a-price-to-a-tick-that-can-be-initialized) |
| Providing liquidity | Concentrated liquidity explorer, with stated assumptions | v3 whitepaper §6.2.3 |
| Swapping | Swap-across-ticks interactive | v3 whitepaper §6.2 |
| Real and virtual reserves | Full derivation, including where capital efficiency comes from | v3 whitepaper |
| Uniswap v4 | Expanded: launched January 2025; hook callback points and example hooks; hook risk; singleton `PoolManager`; flash accounting with transient storage (EIP-1153, Dencun, March 2024); native ETH | [v4 docs](https://docs.uniswap.org/contracts/v4/overview), [hooks](https://docs.uniswap.org/contracts/v4/concepts/hooks), [EIP-1153](https://eips.ethereum.org/EIPS/eip-1153) |
| Governance | What governance controls; proposal lifecycle diagram; snapshots and timelocks; offchain voting (Snapshot); ERC20Votes delegation; Sybil weakness of quadratic voting | [OpenZeppelin Governor](https://docs.openzeppelin.com/contracts/5.x/governance), [Uniswap governance process](https://docs.uniswap.org/concepts/governance/process), [Snapshot docs](https://docs.snapshot.box/), [Buterin 2021](https://vitalik.eth.limo/general/2021/08/16/voting3.html) |
| Governance | Beanstalk attack (April 2022, ≈\$182M, historical) and the governance attack sandbox | [Immunefi analysis](https://immunefi.com/blog/bug-fix-reviews/hack-analysis-beanstalk-governance-attack-april-2022/) |
| MEV | Sandwich simulator comparing gas auctions, MEV-Boost, and a private RPC with a 90% back-run refund | [MEV Blocker docs](https://docs.cow.fi/mevblocker/concepts/order-flow-auction) |
| MEV | Answers to every original "Sanity check" toggle (the originals were empty or unreadable) | — |
| Arbitrage | Worked example from the lesson's linked slides (4,500 ETH / 10M USDC) | Original *arbitrage mev* slides |
| Flashbots | PBS supply-chain diagram and walkthrough of MEV-Boost | [Flashbots MEV-Boost docs](https://docs.flashbots.net/flashbots-mev-boost/introduction) |
| Bad vs good MEV | Sorting exercise with feedback; LVR paper for the cost of arbitrage to LPs | [Milionis et al. 2022](https://arxiv.org/abs/2208.06046) |
| End | Key takeaways; consolidated sources | — |

## Items to double-check before publishing

- The exact onchain execution date of the 0.01% fee tier. Sources disagree between November and December 2021, so the notebook says "late 2021".
- The MEV-Boost share and the status of EIP-7732 change over time. The notebook links to live data rather than giving a fixed figure.
