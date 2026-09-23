#!/usr/bin/env python3
"""
Historical Stock Data Fetcher and Chart Generator
Fetches daily closing prices from Alpaca and generates a line chart.

Usage:
    python historical_chart.py AAPL 30          # Last 30 days of daily closing prices
    python historical_chart.py AMZN 60          # Last 60 days of daily closing prices
    python historical_chart.py TSLA 7 --save    # Last 7 days, save to file
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging

import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class AlpacaHistoricalFetcher:
    """Fetch historical stock data from Alpaca."""
    
    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")
        self.data_url = os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")
        self.feed = "iex"  # Use IEX for historical quotes (has better availability)
        
        if not self.api_key or not self.secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY not found in .env")
        
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }
    
    def fetch_daily_closing_prices(self, symbol: str, days: int) -> pd.DataFrame:
        """
        Fetch end-of-day (EOD) closing prices by fetching the last quote of each day.
        Paginates through each day in the date range efficiently.
        
        Args:
            symbol: Stock ticker (e.g., 'AAPL')
            days: Number of days of historical data
            
        Returns:
            DataFrame with daily closing prices, indexed by date
        """
        try:
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=days)
            
            logger.info(f"Fetching EOD closing prices for {symbol}")
            logger.info(f"Date range: {start_date} to {end_date} ({days} days)")
            
            url = f"{self.data_url}/v2/stocks/quotes"
            daily_closes = []
            current_date = start_date
            
            # Iterate through each day
            while current_date <= end_date:
                # Set time range for this specific day (00:00 to 23:59 UTC)
                day_start = f"{current_date}T00:00:00Z"
                day_end = f"{current_date}T23:59:59Z"
                
                params = {
                    "symbols": symbol,
                    "start": day_start,
                    "end": day_end,
                    "feed": self.feed,
                    "limit": 10000,
                    "sort": "asc",
                }
                
                try:
                    logger.debug(f"Fetching quotes for {current_date}...")
                    response = requests.get(url, headers=self.headers, params=params, timeout=30)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    if "quotes" not in data or not data["quotes"]:
                        logger.debug(f"No quotes for {current_date}")
                        current_date += timedelta(days=1)
                        continue
                    
                    # API returns quotes as dict keyed by symbol
                    quotes_dict = data["quotes"]
                    
                    # Get quotes for our symbol
                    if isinstance(quotes_dict, dict) and symbol in quotes_dict:
                        quotes = quotes_dict[symbol]
                    elif isinstance(quotes_dict, list):
                        quotes = quotes_dict
                    else:
                        logger.warning(f"Unexpected quotes format for {current_date}")
                        current_date += timedelta(days=1)
                        continue
                    
                    if quotes:
                        # Take the last quote of the day (EOD closing price)
                        last_quote = quotes[-1]
                        try:
                            eod_close = {
                                "date": current_date,
                                "timestamp": pd.to_datetime(last_quote.get("t", last_quote.get("time", ""))),
                                "bid": float(last_quote.get("bp", last_quote.get("bid", 0))),
                                "ask": float(last_quote.get("ap", last_quote.get("ask", 0))),
                            }
                            eod_close["close"] = (eod_close["bid"] + eod_close["ask"]) / 2
                            daily_closes.append(eod_close)
                            logger.info(f"{current_date}: EOD close = ${eod_close['close']:.2f}")
                        except Exception as e:
                            logger.warning(f"Failed to parse EOD quote for {current_date}: {e}")
                    
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Failed to fetch quotes for {current_date}: {e}")
                
                current_date += timedelta(days=1)
            
            if not daily_closes:
                logger.warning(f"No closing prices found for {symbol}")
                return pd.DataFrame()
            
            logger.info(f"Successfully fetched {len(daily_closes)} daily closing prices")
            
            # Convert to DataFrame indexed by date
            df = pd.DataFrame(daily_closes)
            df.set_index("date", inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch closing prices: {e}")
            raise


def create_daily_chart(df: pd.DataFrame, symbol: str, save_path: str = None):
    """
    Create a line chart from daily closing price data.
    Google Finance style chart: clean line showing daily closing prices.
    
    Args:
        df: DataFrame with 'close' column, indexed by date
        symbol: Stock ticker symbol
        save_path: Optional path to save the chart
    """
    if df.empty:
        logger.error("DataFrame is empty, cannot create chart")
        return
    
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # Convert date index to datetime for plotting
    dates = pd.to_datetime(df.index)
    
    # Plot line (similar to Google Finance)
    ax.plot(dates, df["close"], label="Close", color="#1f77b4", linewidth=2.5, marker="o", markersize=4)
    
    # Styling
    ax.set_xlabel("Date", fontsize=12, fontweight="bold")
    ax.set_ylabel("Price ($)", fontsize=12, fontweight="bold")
    ax.set_title(f"{symbol} - Daily Closing Prices", fontsize=14, fontweight="bold")
    ax.legend(loc="best", fontsize=11)
    ax.grid(True, alpha=0.3, linestyle="--")
    
    # Format y-axis as currency
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:.2f}"))
    
    # Format x-axis dates
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    
    # Rotate x-axis labels
    plt.xticks(rotation=45, ha="right")
    
    plt.tight_layout()
    
    # Save or display
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        logger.info(f"Chart saved to {save_path}")
    else:
        plt.show()
    
    # Print statistics
    print("\n" + "="*60)
    print(f"Daily Closing Prices - {symbol}")
    print("="*60)
    print(f"Period: {df.index[0]} to {df.index[-1]}")
    print(f"Trading Days: {len(df)}")
    print(f"Price Range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print(f"Average Close: ${df['close'].mean():.2f}")
    print(f"First Close: ${df['close'].iloc[0]:.2f}")
    print(f"Last Close: ${df['close'].iloc[-1]:.2f}")
    change = df['close'].iloc[-1] - df['close'].iloc[0]
    pct_change = (change / df['close'].iloc[0]) * 100
    print(f"Change: ${change:+.2f} ({pct_change:+.2f}%)")
    print("="*60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch daily closing prices and generate a price chart"
    )
    parser.add_argument("symbol", help="Stock ticker symbol (e.g., AAPL)")
    parser.add_argument("days", type=int, help="Number of days of historical data")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save chart to file instead of displaying"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: {symbol}_{days}d.png)"
    )
    
    args = parser.parse_args()
    
    # Determine output path
    if args.save:
        output_path = args.output or f"{args.symbol}_{args.days}d.png"
    else:
        output_path = None
    
    try:
        # Fetch data
        fetcher = AlpacaHistoricalFetcher()
        df = fetcher.fetch_daily_closing_prices(args.symbol, args.days)
        
        if df.empty:
            logger.error("No data to display")
            return 1
        
        # Create chart
        create_daily_chart(df, args.symbol, output_path)
        return 0
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
