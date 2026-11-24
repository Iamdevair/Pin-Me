"""EVM chain presets.

To support another EVM chain, add one entry here and an RPC URL in .env.
You do not need a new Python provider. `explorer_style` picks the transfer API:

- etherscan_v2: https://api.etherscan.io/v2/api?chainid=...
- etherscan_v1: a chain-specific explorer that still speaks the old module=account API
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvmChain:
    key: str
    chain_id: int
    symbol: str
    decimals: int
    explorer_style: str
    explorer_base: str


EVM_CHAINS: dict[str, EvmChain] = {
    "ethereum": EvmChain("ethereum", 1, "ETH", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    # Sepolia is Ethereum's testnet. Same balance poller, different chain id and RPC URL.
    "sepolia": EvmChain("sepolia", 11155111, "ETH", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    "base": EvmChain("base", 8453, "ETH", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    "polygon": EvmChain("polygon", 137, "POL", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    "bsc": EvmChain("bsc", 56, "BNB", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    "arbitrum": EvmChain("arbitrum", 42161, "ETH", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    "optimism": EvmChain("optimism", 10, "ETH", 18, "etherscan_v2", "https://api.etherscan.io/v2/api"),
    # Celo's own explorer still speaks the v1 shape. Balance checks use your RPC either way.
    "celo": EvmChain("celo", 42220, "CELO", 18, "etherscan_v1", "https://api.celoscan.io/api"),
}


# TRC-20 USDT on TRON mainnet. Listed so a new wallet file can copy it.
TRON_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
