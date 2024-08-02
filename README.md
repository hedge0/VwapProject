# VWAP Trading Bot in Python

## Overview

The VWAP Trading Bot is a Python-based solution designed to streamline your trading strategy by automating trades in index futures. This bot interacts with TradingView and the Tastytrade API, allowing for seamless execution of trades based on your TradingView alerts.

## Key Features

- **Real-Time Alerts:** Accepts incoming TradingView requests via webhooks to trigger trades. Alerts are sent to an application called Pushover in real-time using their API.
- **Automated Trading:** Executes trades in index futures using the Tastytrade API.
- **Customizable Scripts:** Integrate and modify Pine Script strategies from TradingView for precise trading decisions.

### Prerequisites

- Docker
- Docker Compose

### Setup

1. Clone the repository:
    ```bash
    git clone https://github.com/hedge0/tradingview-discord-bot.git
    cd tradingview-discord-bot
    ```

2. Create a `.env` file in the root directory and add the required environment variables:
    ```env
    PAYLOAD_TOKEN=your_payload_token
    NARROW_NQ=your_narrow_nq_value
    WIDE_NQ=your_wide_nq_value
    NARROW_ES=your_narrow_es_value
    WIDE_ES=your_wide_es_value
    BULLISH=true_or_false
    SIZE_ES=your_size_es_value
    SIZE_NQ=your_size_nq_value
    TICKER_ES=your_ticker_es_value
    TICKER_NQ=your_ticker_nq_value
    PUSHOVER_TOKEN=your_pushover_token
    PUSHOVER_USER=your_pushover_user
    TASTYTRADE_USERNAME=your_tastytrade_username
    TASTYTRADE_PASSWORD=your_tastytrade_password
    TASTYTRADE_ACCOUNT_NUMBER=your_tastytrade_account_number
    LIVE=true_or_false
    ```

3. Build and run the Docker container:
    ```bash
    docker-compose up --build
    ```

### Usage

- The bot will automatically start and listen for webhook triggers to execute trades.
- Configure your TradingView alerts to send webhooks to `http://your-server-ip:5000/webhook`.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any changes or improvements.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
