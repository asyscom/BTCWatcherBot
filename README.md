# BTCWatcherBot

BTCWatcherBot is a Telegram bot designed to monitor and provide information on Bitcoin and the Lightning Network. The bot offers a variety of features including transaction monitoring, fee alerts, market statistics, and more.

## Features

- **Price & Market Tools**
  - Show the current Bitcoin price in USD and EUR.
  - Set price alerts.
  - Display the 24-hour price trend.
  - Show arbitrage opportunities across different exchanges.
  - Show fiat-Bitcoin exchange rates.

- **Monitoring Tools**
  - Monitor large unconfirmed transactions (whales).
  - Monitor new blocks mined.
  - Track the confirmation status of transactions.

- **Fees & Forecasts**
  - Display current Bitcoin network fees.
  - Calculate the estimated fee for a transaction.
  - Set fee alerts.
  - Show fee forecast for the next few hours.

- **Security & Node Info**
  - Provide Bitcoin security tips.
  - Display detailed information about Lightning Network nodes.

- **Daily Report**
  - Enable and disable daily reports with Bitcoin statistics.

- **Stats & Resources**
  - Show blockchain and Lightning Network stats.
  - Display global market cap and Bitcoin dominance.
  - Show Bitcoin volatility index.
  - Provide educational resources on Bitcoin and the Lightning Network.

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/asyscom/BTCWatcherBot.git
   cd BTCWatcherBot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the .env file**
   Create a `.env` file in the root directory and add your Telegram bot token:
   ```env
   BOT_TOKEN=your-telegram-bot-token
   ```

4. **Set up the database**
   The bot uses SQLite to store data. Tables will be created automatically when the bot starts.

## Usage

1. **Start the bot**
   ```bash
   python bot.py
   ```

2. **Use the commands on Telegram**
   - `/start`: Start the bot.
   - `/price`: Show the current Bitcoin price.
   - `/fees`: Display current Bitcoin network fees.
   - `/monitor_blocks`: Start monitoring new blocks.
   - `/monitor_whales`: Monitor large Bitcoin transactions.
   - `/stop_monitor_whales`: Stop monitoring large transactions.
   - `/set_price_alert [price]`: Set a price alert.
   - `/track_tx [txid]`: Track the status of a transaction.
   - `/calc_fee [size]`: Calculate the estimated fee for a transaction.
   - `/price_trend`: Show the 24-hour price trend.
   - `/set_fee_alert [fee]`: Set a fee alert.
   - `/node_info [public key]`: Display information about a Lightning Network node.
   - `/donate`: Show donation information.
   - `/fiat_rates`: Show fiat-Bitcoin exchange rates.
   - `/fee_forecast`: Show fee forecast.
   - `/market_cap`: Show global market cap.
   - `/volatility`: Show Bitcoin volatility index.
   - `/dominance`: Show Bitcoin and Ethereum dominance.
   - `/resources`: Provide educational resources.
   - `/faq`: Show FAQs about Bitcoin and the Lightning Network.
   - `/daily_report_on`: Enable the daily report.
   - `/daily_report_off`: Disable the daily report.

## Contributing

If you would like to contribute to the project, feel free to fork the repository and submit a pull request. All contributions are welcome!

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
