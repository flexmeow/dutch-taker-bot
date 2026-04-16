import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from tinybot import multicall
from web3 import Web3


class NetworkCfg(TypedDict):
    registry: str
    taker_contract: str
    explorer: str


NETWORKS: Mapping[str, NetworkCfg] = {
    "ethereum": {
        "registry": "0xA6D5efF88aB2D192db11A32912c346c8c0AFe125",
        "taker_contract": "0xD8cE6ED969266E529779b6D6C35aefBD5DaD68EC",
        "explorer": "https://etherscan.io/",
    },
}

USDC = Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")

# Profit buffer on top of gas cost
PROFIT_BUFFER = 1.001

# Interval
INTERVAL = 50

# ABIs
_abis = Path(__file__).parent / "abis"
REGISTRY_ABI = json.loads((_abis / "registry.json").read_text())
TROVE_MANAGER_ABI = json.loads((_abis / "trove_manager.json").read_text())
DUTCH_DESK_ABI = json.loads((_abis / "dutch_desk.json").read_text())
AUCTION_ABI = json.loads((_abis / "auction.json").read_text())
TAKER_ABI = json.loads((_abis / "taker.json").read_text())


def network() -> str:
    return os.environ.get("NETWORK", "ethereum")


def cfg() -> NetworkCfg:
    return NETWORKS[network()]


def explorer_tx_url() -> str:
    return cfg()["explorer"] + "tx/"


def taker_contract_addr() -> str:
    return Web3.to_checksum_address(cfg()["taker_contract"])


def enso_api_key() -> str:
    key = os.getenv("ENSO_API_KEY", "")
    if not key:
        raise RuntimeError("!ENSO_API_KEY")
    return key


def get_all_auctions(w3: Web3) -> list[str]:
    """Get all auction contract addresses from endorsed markets in the registry."""
    registry = w3.eth.contract(address=w3.to_checksum_address(cfg()["registry"]), abi=REGISTRY_ABI)
    markets: list[str] = registry.functions.get_all_markets().call()

    if not markets:
        return []

    # Filter to only endorsed markets (Status.ENDORSED = 1)
    status_calls = [registry.functions.market_status(w3.to_checksum_address(m)) for m in markets]
    statuses = multicall(w3, status_calls)
    markets = [m for m, s in zip(markets, statuses) if s == 1]

    if not markets:
        return []

    # Get dutch_desk for each market
    dutch_desk_calls = [
        w3.eth.contract(address=w3.to_checksum_address(m), abi=TROVE_MANAGER_ABI).functions.dutch_desk()
        for m in markets
    ]
    dutch_desks = multicall(w3, dutch_desk_calls)

    # Get auction address for each dutch_desk
    auction_calls = [
        w3.eth.contract(address=w3.to_checksum_address(dd), abi=DUTCH_DESK_ABI).functions.auction()
        for dd in dutch_desks
    ]
    auction_addrs = multicall(w3, auction_calls)

    return list(set(w3.to_checksum_address(a) for a in auction_addrs))
