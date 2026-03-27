import os

from tinybot import DEV_GROUP_CHAT_ID, TinyBot, multicall, notify_group_chat
from web3.contract import Contract

from bot.config import (
    AUCTION_ABI,
    ERC20_ABI,
    INTERVAL,
    PROFIT_BUFFER,
    TAKER_ABI,
    USDC,
    enso_api_key,
    explorer_tx_url,
    get_all_auctions,
    network,
    safe_name,
    taker_contract_addr,
)
from bot.swap import get_swap_route

# =============================================================================
# Event Handlers
# =============================================================================


async def on_auction_kick(bot: TinyBot, log: object) -> None:
    auction_addr: str = log.address
    auction_id: int = log.args.auction_id
    kick_amount: int = log.args.kick_amount

    bot.state.add_item(auction_addr, str(auction_id))

    auction = bot.w3.eth.contract(address=auction_addr, abi=AUCTION_ABI)
    sell_token = bot.w3.eth.contract(address=auction.functions.sell_token().call(), abi=ERC20_ABI)
    symbol, decimals = multicall(bot.w3, [sell_token.functions.symbol(), sell_token.functions.decimals()])

    re_kick = "Re-Kicked" if log.args.is_re_kick else "Kicked"
    emoji = "🚨" if log.args.is_re_kick else "🥾"

    await notify_group_chat(
        f"{emoji} <b>Auction {re_kick}</b>\n\n"
        f"<b>Auction ID:</b> {auction_id}\n"
        f"<b>Kick Amount:</b> {kick_amount / (10**decimals):.4f} {symbol}\n\n"
        f"<a href='{explorer_tx_url()}{log.transactionHash.hex()}'>🔗 View Transaction</a>"
    )


async def on_auction_take(bot: TinyBot, log: object) -> None:
    auction_addr: str = log.address
    auction_id: int = log.args.auction_id
    take_amount: int = log.args.take_amount
    remaining: int = log.args.remaining_amount
    needed_amount: int = log.args.needed_amount
    tx_origin: str = bot.w3.eth.get_transaction(log.transactionHash)["from"]

    auction = bot.w3.eth.contract(address=auction_addr, abi=AUCTION_ABI)
    sell_token = bot.w3.eth.contract(address=auction.functions.sell_token().call(), abi=ERC20_ABI)
    buy_token = bot.w3.eth.contract(address=auction.functions.buy_token().call(), abi=ERC20_ABI)
    sell_symbol, sell_decimals, buy_symbol, buy_decimals = multicall(
        bot.w3,
        [sell_token.functions.symbol(), sell_token.functions.decimals(), buy_token.functions.symbol(), buy_token.functions.decimals()],
    )

    status = "fully taken" if remaining == 0 else "partially taken"
    remaining_line = "" if remaining == 0 else f"<b>Remaining:</b> {remaining / (10**sell_decimals):.4f} {sell_symbol}\n"
    await notify_group_chat(
        f"🎯 <b>Auction {status}!</b>\n\n"
        f"<b>Auction ID:</b> {auction_id}\n"
        f"<b>Take Amount:</b> {take_amount / (10**sell_decimals):.4f} {sell_symbol}\n"
        f"<b>Paid:</b> {needed_amount / (10**buy_decimals):.4f} {buy_symbol}\n"
        f"{remaining_line}"
        f"<b>Taker:</b> {safe_name(bot.w3, tx_origin)}\n\n"
        f"<a href='{explorer_tx_url()}{log.transactionHash.hex()}'>🔗 View Transaction</a>"
    )


# =============================================================================
# Periodic Tasks
# =============================================================================


async def check_auctions_and_take(bot: TinyBot) -> None:
    if not bot.state.active_items:
        return

    taker = bot.w3.eth.contract(address=taker_contract_addr(), abi=TAKER_ABI)

    for pair in bot.state.active_items[:]:
        auction_addr, auction_id_str = pair
        auction_id = int(auction_id_str)
        auction_addr = bot.w3.to_checksum_address(auction_addr)

        auction = bot.w3.eth.contract(address=auction_addr, abi=AUCTION_ABI)
        available = auction.functions.get_available_amount(auction_id).call()

        if available == 0:
            bot.state.remove_item(pair)
            continue

        await execute_take(bot, taker, auction, auction_addr, auction_id, available)


async def execute_take(
    bot: TinyBot,
    taker: Contract,
    auction: Contract,
    auction_addr: str,
    auction_id: int,
    available: int,
) -> None:
    sell_token_addr = auction.functions.sell_token().call()

    # Get swap route (collateral --> USDC)
    router, swap_data = get_swap_route(
        api_key=enso_api_key(),
        chain_id=1,
        input_token=sell_token_addr,
        output_token=USDC,
        amount=available,
        sender=taker.address,
    )

    # Estimate gas cost
    call = taker.functions.take(
        auction_addr,
        auction_id,
        sell_token_addr,
        bot.w3.to_checksum_address(router),
        swap_data,
        0,
        bot.executor.address,
    )
    gas_estimate = call.estimate_gas({"from": bot.executor.address})
    base_fee = bot.w3.eth.get_block("latest").baseFeePerGas
    gas_cost = gas_estimate * base_fee
    min_profit = int(gas_cost * PROFIT_BUFFER)

    # Execute take
    call = taker.functions.take(
        auction_addr,
        auction_id,
        sell_token_addr,
        bot.w3.to_checksum_address(router),
        swap_data,
        min_profit,
        bot.executor.address,
    )
    tx_hash = bot.executor.execute(call, max_priority_fee_gwei=0.1, wait=120)
    print(f"take tx sent: {tx_hash}")

    await notify_group_chat(
        f"🦅 <b>Take tx sent!</b>\n\n"
        f"<b>Auction:</b> {auction_addr}\n"
        f"<b>Auction ID:</b> {auction_id}\n\n"
        f"<a href='{explorer_tx_url()}{tx_hash}'>🔗 View Transaction</a>",
        chat_id=DEV_GROUP_CHAT_ID,
    )


# =============================================================================
# Main
# =============================================================================


async def run() -> None:
    bot = TinyBot(
        rpc_url=os.environ["RPC_URL"],
        name=f"🦅 {network()} dutch taker",
        private_key=os.environ["TAKER_PRIVATE_KEY"],
    )

    auction_addrs = get_all_auctions(bot.w3)

    bot.listen(
        poll_interval=INTERVAL,
        event="AuctionKick",
        addresses=auction_addrs,
        abi=AUCTION_ABI,
        handler=on_auction_kick,
    )
    bot.listen(
        poll_interval=INTERVAL,
        event="AuctionTake",
        addresses=auction_addrs,
        abi=AUCTION_ABI,
        handler=on_auction_take,
    )

    # # # TEST: replay AuctionKick
    # await bot.replay("on_auction_kick", from_block=24750789, to_block=24750791)
    # await bot.replay("on_auction_take", from_block=24750633, to_block=24750635)

    bot.every(INTERVAL, check_auctions_and_take)

    await bot.run()
