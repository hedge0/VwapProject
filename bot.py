import os
import asyncio
from aiohttp import web
from datetime import datetime, timedelta
from dotenv import load_dotenv
from asyncio import Lock
import pytz
import logging
import requests
from decimal import Decimal

from tastytrade import ProductionSession, Account
from tastytrade.instruments import Future
from tastytrade.order import *


# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants and Global Variables
nyc_tz = pytz.timezone('America/New_York')
lock = Lock()
timestamps = {"ES": [], "NQ": []}
config = {}
in_position = []
is_live = False
is_bullish = True

# Global variables for Tastytrade
session = None
account = None
symbol_ES = ''
symbol_NQ = ''


def load_config():
    """
    Load configuration from environment variables and validate them.
    
    Raises:
        ValueError: If any required environment variable is not set.
    """
    global config
    config = {
        "PAYLOAD_TOKEN": os.getenv('PAYLOAD_TOKEN'),
        "NARROW_NQ": int(os.getenv('NARROW_NQ')),
        "MEDIUM_NQ": int(os.getenv('MEDIUM_NQ')),
        "WIDE_NQ": int(os.getenv('WIDE_NQ')),
        "NARROW_ES": int(os.getenv('NARROW_ES')),
        "MEDIUM_ES": int(os.getenv('MEDIUM_ES')),
        "WIDE_ES": int(os.getenv('WIDE_ES')),
        "BULLISH": os.getenv('BULLISH').lower() == 'true',
        "SIZE_ES": int(os.getenv('SIZE_ES')),
        "SIZE_NQ": int(os.getenv('SIZE_NQ')),
        "TICKER_ES": os.getenv('TICKER_ES'),
        "TICKER_NQ": os.getenv('TICKER_NQ'),
        "PUSHOVER_TOKEN": os.getenv('PUSHOVER_TOKEN'),
        "PUSHOVER_USER": os.getenv('PUSHOVER_USER'),
        "TASTYTRADE_USERNAME": os.getenv('TASTYTRADE_USERNAME'),
        "TASTYTRADE_PASSWORD": os.getenv('TASTYTRADE_PASSWORD'),
        "TASTYTRADE_ACCOUNT_NUMBER": os.getenv('TASTYTRADE_ACCOUNT_NUMBER'),
        "LIVE": os.getenv('LIVE').lower() == 'true',
    }

    for key, value in config.items():
        if value is None:
            raise ValueError(f"{key} environment variable not set")


def set_ticker_symbols():
    """
    Set the active ticker symbols for ES and NQ futures contracts.
    """
    global symbol_ES, symbol_NQ

    def get_active_symbol(product_code):
        symbols = Future.get_futures(session, product_codes=product_code.strip('/'))
        for symbol in symbols:
            if symbol.active_month:
                return symbol.symbol
        return ''

    symbol_ES = get_active_symbol(config["TICKER_ES"])
    symbol_NQ = get_active_symbol(config["TICKER_NQ"])


def log_initial_config():
    """
    Log the initial configuration of the bot.
    """
    bias = 'Bullish' if is_bullish else 'Bearish'
    logger.info(f'\nBot Bias: {bias}\nIs Live: {is_live}\n')
    logger.info(f'\nNQ Narrow SL Size: {config["NARROW_NQ"]} pts\nNQ Medium SL Size: {config["MEDIUM_NQ"]} pts\nNQ Wide SL Size: {config["WIDE_NQ"]} pts\nNQ lots: {config["SIZE_NQ"]}\nNQ ticker name: {config["TICKER_NQ"]}\nNQ ticker month: {symbol_NQ}\n')
    logger.info(f'\nES Narrow SL Size: {config["NARROW_ES"]} pts\nES Medium SL Size: {config["MEDIUM_ES"]} pts\nES Wide SL Size: {config["WIDE_ES"]} pts\nES lots: {config["SIZE_ES"]}\nES ticker name: {config["TICKER_ES"]}\nES ticker month: {symbol_ES}\n')


def send_pushover_message(message):
    """
    Send a notification message via Pushover.

    Args:
        message (str): The message to be sent.
    """
    pushover_token = config.get('PUSHOVER_TOKEN')
    pushover_user = config.get('PUSHOVER_USER')

    if pushover_token and pushover_user:
        response = requests.post("https://api.pushover.net/1/messages.json", data={
            "token": pushover_token,
            "user": pushover_user,
            "message": message
        })
        if response.status_code != 200:
            logger.error(f"Failed to send Pushover notification: {response.text}")
    else:
        logger.error("Pushover credentials not set in environment variables")


def clean_old_timestamps(current_time):
    """
    Remove timestamps older than 1 hour and 30 minutes.

    Args:
        current_time (datetime): The current time to compare against.
    """
    time_threshold = current_time - timedelta(hours=1, minutes=30)
    timestamps["ES"] = [t for t in timestamps["ES"] if t > time_threshold]
    timestamps["NQ"] = [t for t in timestamps["NQ"] if t > time_threshold]


def clear_timestamps():
    """
    Clear all timestamps for ES and NQ.
    """
    timestamps["ES"].clear()
    timestamps["NQ"].clear()


async def handle_bullish_alert(ticker, alert_type, stop_type, current_price, current_time, forbidden_start, forbidden_end, bypass):
    """
    Handle alerts when the bot is in bullish mode.

    Args:
        ticker (str): The ticker symbol.
        alert_type (str): The type of alert ("Long" or "Short").
        stop_type (str): The type of stop ("Narrow", "Medium", or "Wide").
        current_price (float): The current price of the ticker.
        current_time (datetime): The current time.
        forbidden_start (datetime): Start of the forbidden time range.
        forbidden_end (datetime): End of the forbidden time range.
        bypass (bool): Flag to bypass forbidden time range.
    """
    global in_position
    if alert_type == "Long":
        timestamps[ticker].append(current_time)
        clean_old_timestamps(current_time)

        if ticker == "ES" and ((timestamps["NQ"] and not (forbidden_start <= current_time <= forbidden_end)) or (bypass)):
            await process_trade("ES", stop_type, current_price, OrderAction.BUY)
        elif ticker == "NQ" and ((timestamps["ES"] and not (forbidden_start <= current_time <= forbidden_end)) or (bypass)):
            await process_trade("NQ", stop_type, current_price, OrderAction.BUY)
    elif alert_type == "Short" and in_position:
        await close_positions("Long", current_price)


async def handle_bearish_alert(ticker, alert_type, stop_type, current_price, current_time, forbidden_start, forbidden_end, bypass):
    """
    Handle alerts when the bot is in bearish mode.

    Args:
        ticker (str): The ticker symbol.
        alert_type (str): The type of alert ("Long" or "Short").
        stop_type (str): The type of stop ("Narrow", "Medium", or "Wide").
        current_price (float): The current price of the ticker.
        current_time (datetime): The current time.
        forbidden_start (datetime): Start of the forbidden time range.
        forbidden_end (datetime): End of the forbidden time range.
        bypass (bool): Flag to bypass forbidden time range.
    """
    global in_position
    if alert_type == "Short":
        timestamps[ticker].append(current_time)
        clean_old_timestamps(current_time)

        if ticker == "ES" and ((timestamps["NQ"] and not (forbidden_start <= current_time <= forbidden_end)) or (bypass)):
            await process_trade("ES", stop_type, current_price, OrderAction.SELL)
        elif ticker == "NQ" and ((timestamps["ES"] and not (forbidden_start <= current_time <= forbidden_end)) or (bypass)):
            await process_trade("NQ", stop_type, current_price, OrderAction.SELL)
    elif alert_type == "Long" and in_position:
        await close_positions("Short", current_price)


async def process_trade(ticker, stop_type, current_price, order_action):
    """
    Process a trade based on the alert and current position.

    Args:
        ticker (str): The ticker symbol.
        stop_type (str): The type of stop ("Narrow", "Medium", or "Wide").
        current_price (float): The current price of the ticker.
        order_action (OrderAction): The action for the order (BUY or SELL).
    """
    global in_position
    if not in_position and is_live:
        if stop_type not in ["Narrow", "Medium", "Wide"]:
            raise ValueError("Invalid stop type. Must be 'Narrow', 'Medium', or 'Wide'.")

        stop_size = config[f"{stop_type.upper()}_{ticker}"]
        profit_multipliers = {"Narrow": 3, "Medium": 5, "Wide": 7}
        profit_size = stop_size * profit_multipliers[stop_type]

        size = config[f"SIZE_{ticker}"]
        symbol = Future.get_future(session, globals()[f"symbol_{ticker}"])
        opening_leg = symbol.build_leg(Decimal(size), order_action)
        closing_leg = symbol.build_leg(Decimal(size), OrderAction.SELL if order_action == OrderAction.BUY else OrderAction.BUY)

        main_order_price_effect = PriceEffect.DEBIT if order_action == OrderAction.BUY else PriceEffect.CREDIT
        main_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[opening_leg],
            price_effect=main_order_price_effect
        )

        take_profit_price = Decimal(current_price + profit_size if order_action == OrderAction.BUY else current_price - profit_size)
        profit_order_price_effect = PriceEffect.CREDIT if order_action == OrderAction.BUY else PriceEffect.DEBIT
        profit_order = NewOrder(
            time_in_force=OrderTimeInForce.GTC,
            order_type=OrderType.LIMIT,
            legs=[closing_leg],
            price=take_profit_price,
            price_effect=profit_order_price_effect
        )

        stop_loss_price = Decimal(current_price - stop_size if order_action == OrderAction.BUY else current_price + stop_size)
        stop_order_price_effect = PriceEffect.CREDIT if order_action == OrderAction.BUY else PriceEffect.DEBIT
        stop_order = NewOrder(
            time_in_force=OrderTimeInForce.GTC,
            order_type=OrderType.STOP,
            legs=[closing_leg],
            stop_trigger=stop_loss_price,
            price_effect=stop_order_price_effect
        )

        otoco_order = NewComplexOrder(
            trigger_order=main_order,
            orders=[profit_order, stop_order]
        )

        try:
            account.place_complex_order(session, otoco_order, dry_run=False)
            send_pushover_message(f'Entering {"Long" if order_action == OrderAction.BUY else "Short"} Position\nTicker: {config[f"TICKER_{ticker}"]}\nPrice: {current_price}\nSize: {"+" if order_action == OrderAction.BUY else "-"}{size}\nStop Size: {stop_size} pts\nProfit Size: {profit_size} pts')
            
            position_object = {
                "ticker": ticker,
                "symbol_ticker": globals()[f"symbol_{ticker}"],
                "current_price": current_price,
                "stop_size": stop_size,
                "profit_size": profit_size,
                "order_action": order_action,
                "size": size,
            }

            await asyncio.sleep(1)

            clear_timestamps()
            in_position.append(position_object)
        except Exception as e:
            logger.error(f"Error placing opening order: {e}")
            send_pushover_message(f"Error placing opening order: {e}")


async def close_positions(direction, current_price):
    """
    Close all open positions in the given direction.

    Args:
        direction (str): The direction of the positions to close ("Long" or "Short").
        current_price (float): The current price of the ticker.
    """
    global in_position

    if is_live:
        positions = account.get_positions(session)
        for pos in positions:
            if pos.quantity_direction == direction and pos.instrument_type == InstrumentType.FUTURE and pos.quantity > 0:
                await cancel_live_orders()
                closing_leg = Future.get_future(session, pos.symbol).build_leg(
                    quantity=pos.quantity,
                    action=OrderAction.SELL if direction == "Long" else OrderAction.BUY
                )

                closing_order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.MARKET,
                    legs=[closing_leg],
                    price_effect=PriceEffect.CREDIT if direction == "Long" else PriceEffect.DEBIT
                )
                
                try:
                    account.place_order(session, closing_order, dry_run=False)
                    send_pushover_message(f'Closing {direction} Position\nTicker: {pos.underlying_symbol}\nPrice: {current_price}\nSize: {"-" if direction == "Long" else "+"}{pos.quantity}')
                except Exception as e:
                    logger.error(f"Error placing closing order: {e}")
                    send_pushover_message(f"Error placing closing order: {e}")
                    return
        
        await asyncio.sleep(1)
        in_position = []


async def cancel_live_orders():
    """
    Cancel all live stop and limit orders.
    """
    if is_live:
        working_orders = account.get_live_orders(session)
        for working_order in working_orders:
            if working_order.order_type in {OrderType.STOP, OrderType.LIMIT} and working_order.status == OrderStatus.LIVE:
                account.delete_order(session, working_order.id)
                logger.info(f"Cancelled order ID: {working_order.id}")


async def handle_webhook(request):
    """
    Handle incoming webhook requests.

    Args:
        request (aiohttp.web.Request): The incoming request.

    Returns:
        aiohttp.web.Response: The response to the request.
    """
    global in_position
    async with lock:
        data = await request.json()

        if data.get('payload_token') == config["PAYLOAD_TOKEN"] and is_live:
            ticker = data.get('ticker')
            current_price = Decimal(data.get('price'))
            alert_type = data.get('alert_type')
            stop_type = data.get('stop_type')
            current_time = datetime.now(nyc_tz)
            bypass = data.get('bypass', None)

            forbidden_start = current_time.replace(hour=8, minute=30, second=0, microsecond=0)
            forbidden_end = current_time.replace(hour=8, minute=35, second=0, microsecond=0)

            if is_bullish:
                await handle_bullish_alert(ticker, alert_type, stop_type, current_price, current_time, forbidden_start, forbidden_end, bypass)
            else:
                await handle_bearish_alert(ticker, alert_type, stop_type, current_price, current_time, forbidden_start, forbidden_end, bypass)

        return web.Response(text='')
    

async def handle_status_check(request):
    """
    Handle incoming status check requests.

    Args:
        request (aiohttp.web.Request): The incoming request.

    Returns:
        aiohttp.web.Response: The response to the request.
    """    
    status = "Bullish" if is_bullish else "Bearish"
    live_status = "True" if is_live else "False"
    positions = "\n".join([f"Ticker: {pos['ticker']}, Price: {pos['current_price']}, Size: {pos['size']}, Stop Size: {pos['stop_size']}, Profit Size: {pos['profit_size']}, Action: {'BUY' if pos['order_action'] == OrderAction.BUY else 'SELL'}" for pos in in_position])

    response_text = f"Bot Bias: {status}\nIs Live: {live_status}\nActive Positions:\n{positions if positions else 'None'}"

    return web.Response(text=response_text)


async def handle_switch_bias(request):
    """
    Handle incoming requests to switch the bias.

    Args:
        request (aiohttp.web.Request): The incoming request.

    Returns:
        aiohttp.web.Response: The response to the request.
    """
    global is_bullish

    data = await request.json()
    if data.get('payload_token') == config["PAYLOAD_TOKEN"]:
        await close_positions("Long" if is_bullish else "Short", 0)
        clear_timestamps()

        is_bullish = not is_bullish
        new_status = "Bullish" if is_bullish else "Bearish"

        return web.Response(text=f"Bot has been switched to {new_status}")

    return web.Response(status=403, text="Forbidden")


async def handle_switch_live_status(request):
    """
    Handle incoming requests to switch the live status.

    Args:
        request (aiohttp.web.Request): The incoming request.

    Returns:
        aiohttp.web.Response: The response to the request.
    """
    global is_live

    data = await request.json()
    if data.get('payload_token') == config["PAYLOAD_TOKEN"]:
        is_live = not is_live
        new_status = "True" if is_live else "False"

        return web.Response(text=f"Bot 'Is Live' status has been switched to {new_status}")

    return web.Response(status=403, text="Forbidden")


async def run_web_server():
    """
    Run the web server to handle incoming webhook requests.
    """
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_get('/status', handle_status_check)
    app.router.add_post('/switch-bias', handle_switch_bias)
    app.router.add_post('/switch-live-status', handle_switch_live_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()


async def main():
    """
    Main function to initialize the bot and run the web server.
    """
    global session, account, in_position, is_live, is_bullish

    load_config()
    is_live = config["LIVE"]
    is_bullish = config["BULLISH"]

    session = ProductionSession(login=config["TASTYTRADE_USERNAME"], password=config["TASTYTRADE_PASSWORD"], remember_me=True)
    account = Account.get_account(session, config["TASTYTRADE_ACCOUNT_NUMBER"])
    set_ticker_symbols()

    log_initial_config()
    await run_web_server()

    for _ in range(14):
        for _ in range(2880):
            if in_position and is_live:
                positions = account.get_positions(session)

                if not positions:
                    await cancel_live_orders()
                    await asyncio.sleep(1)
                    
                    in_position = []
            await asyncio.sleep(15)

        session = ProductionSession(config["TASTYTRADE_USERNAME"], password=config["TASTYTRADE_PASSWORD"], remember_me=True)
        account = Account.get_account(session, config["TASTYTRADE_ACCOUNT_NUMBER"])
        set_ticker_symbols()

    is_live = False
    for _ in range(14):
        send_pushover_message(f'Bot is Dead\nRedeploy ASAP')
        await asyncio.sleep(60*60*12)

if __name__ == '__main__':
    asyncio.run(main())
