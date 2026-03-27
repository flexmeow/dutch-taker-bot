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
    known_addresses: dict[str, str]


NETWORKS: Mapping[str, NetworkCfg] = {
    "ethereum": {
        "registry": "0x686725E618742071D52966e90ca4727B506bC5f1",
        "taker_contract": "0xD8cE6ED969266E529779b6D6C35aefBD5DaD68EC",
        "explorer": "https://etherscan.io/",
        "known_addresses": {
            "0xEf77cc176c748d291EfB6CdC982c5744fC7211c8": "yRoboTreasury",
            "0x16388463d60FFE0661Cf7F1f31a7D658aC790ff7": "SMS",
            "0x9008D19f58AAbD9eD0D60971565AA8510560ab41": "Mooo 🐮",
            "0x1DA3902C196446dF28a2b02Bf733cA31A00A161b": "TradeHandler",
            "0x84483314d2AD44Aa96839F048193CE9750AA66B0": "gekko",
            "0x5CECc042b2A320937c04980148Fc2a4b66Da0fbF": "gekko",
            "0xb911Fcce8D5AFCEc73E072653107260bb23C1eE8": "Yearn veCRV Fee Burner",
            "0xE08D97e151473A848C3d9CA3f323Cb720472D015": "c0ffeebabe.eth",
            "0x5b6046ca3b7EA44Eb016757C2E6A7ecc41273ca3": "piggy",
        },
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
ERC20_ABI = json.loads((_abis / "erc20.json").read_text())


def network() -> str:
    return os.environ.get("NETWORK", "ethereum")


def cfg() -> NetworkCfg:
    return NETWORKS[network()]


def explorer_tx_url() -> str:
    return cfg()["explorer"] + "tx/"


def safe_name(w3: Web3, address: str) -> str:
    address = w3.to_checksum_address(address)
    try:
        c = w3.eth.contract(address=address, abi=ERC20_ABI)
        return c.functions.name().call()
    except Exception:
        pass
    try:
        name = w3.ens.name(address)
        if name:
            return str(name)
    except Exception:
        pass
    return cfg()["known_addresses"].get(address, address)


def taker_contract_addr() -> str:
    return Web3.to_checksum_address(cfg()["taker_contract"])


def enso_api_key() -> str:
    key = os.getenv("ENSO_API_KEY", "")
    if not key:
        raise RuntimeError("!ENSO_API_KEY")
    return key


def get_all_auctions(w3: Web3) -> list[str]:
    """Get all auction contract addresses from the registry."""
    registry = w3.eth.contract(address=w3.to_checksum_address(cfg()["registry"]), abi=REGISTRY_ABI)
    markets: list[str] = registry.functions.get_all_markets().call()

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
