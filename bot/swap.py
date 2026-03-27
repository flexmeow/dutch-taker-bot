import json
from urllib.request import Request, urlopen


def get_swap_route(
    api_key: str,
    chain_id: int,
    input_token: str,
    output_token: str,
    amount: int,
    sender: str,
) -> tuple[str, bytes]:
    """
    Get swap route from Enso API.
    Returns (router_address, swap_calldata).
    """
    url = "https://api.enso.build/api/v1/shortcuts/route"
    payload = {
        "chainId": chain_id,
        "fromAddress": sender,
        "routingStrategy": "router",
        "tokenIn": [input_token],
        "tokenOut": [output_token],
        "amountIn": [str(amount)],
        "slippage": "100",
    }
    req = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    resp = json.loads(urlopen(req, timeout=30).read())  # noqa: S310
    router = resp["tx"]["to"]
    calldata = bytes.fromhex(resp["tx"]["data"][2:])
    return router, calldata
