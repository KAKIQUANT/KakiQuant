import pandas as pd
import pymongo
from datetime import datetime
import logging
import time
import concurrent.futures
import okx.MarketData as MarketData
import okx.PublicData as PublicData
from pymongo import MongoClient
from datetime import datetime
import random

class CryptoDataUpdater:
    def __init__(self):
        self.client = MongoClient('localhost', 27017)
        self.db = self.client.crypto
        self.collection = self.db.crypto_kline
        self.api_client = MarketData.MarketAPI(flag="0")  # Adjust this based on your API client initialization
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", 
                            handlers=[logging.FileHandler("crypto_AIO.log"), logging.StreamHandler()])

    def find_bounds(self, inst_id, bar):
        latest_record = self.collection.find_one({'instId': inst_id, 'bar': bar}, sort=[('timestamp', pymongo.DESCENDING)])
        if latest_record:
            return latest_record['timestamp']
        return None

    def insert_data_to_mongodb(self, data):
        if not data.empty:
            data_dict = data.to_dict('records')
            self.collection.insert_many(data_dict)
            logging.info(f"Inserted {len(data_dict)} new records.")

    def get_all_coin_pairs(self):
        publicDataAPI = PublicData.PublicAPI(flag="0")
        spot_result = publicDataAPI.get_instruments(instType="SPOT")
        swap_result = publicDataAPI.get_instruments(instType="SWAP")
        spot_list = [i["instId"] for i in spot_result["data"]]
        swap_list = [i["instId"] for i in swap_result["data"]]
        return spot_list + swap_list

    def process_kline(self, data, inst_id, bar):
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'])
        df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
        numeric_fields = ['open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm']
        for field in numeric_fields:
            df[field] = pd.to_numeric(df[field], errors='coerce')
        df['instId'] = inst_id
        df['bar'] = bar
        return df

    def newest_data_ts(self, inst_id, bar):
        result = self.api_client.get_history_candlesticks(
                        instId=inst_id,
                        bar=bar
                    )['data'][0][0]
        return result

    def fetch_kline_data(self, inst_id: str, bar: str, start_date="2019-01-01", initial_delay=1):
        # Always ensure the newest data is the end_date
        end_timestamp = self.newest_data_ts(inst_id, bar)
        # Convert start and end dates to Unix timestamp in milliseconds
        start_timestamp = int(pd.Timestamp(start_date).timestamp()) * 1000

        # Initially, 'before' is None to fetch the latest data
        a = end_timestamp
        b = None
        is_first_time = True

        # Initialize dynamic sleep time
        sleep_time = initial_delay
        min_sleep_time = 0.1  # Minimum sleep time
        max_sleep_time = 5.0  # Maximum sleep time
        sleep_adjustment_factor = 0.5  # Factor to adjust sleep time

        while True:
            try:
                result = self.api_client.get_history_candlesticks(
                    instId=inst_id,
                    before=str(b) if b else "",
                    after=str(a),
                    bar=bar
                )

                # Check if result is empty or contains data
                if not result['data']:
                    logging.info("No more data to fetch or empty data returned.")
                    return

                # Process the data
                df = self.process_kline(result['data'], inst_id=inst_id, bar=bar)
                
                # Insert data to MongoDB if applicable
                if not df.empty:
                    self.insert_data_to_mongodb(df)
                    logging.info(f"Successfully inserted data for {inst_id} {bar}.")

                # Update 'before' and 'after' for the next request
                earliest_timestamp = int(result['data'][-1][0])
                if is_first_time:
                    time_interval = int(result['data'][0][0]) - earliest_timestamp
                    is_first_time = False
                a = earliest_timestamp
                b = a - time_interval - 4 + random.randint(1, 10)*2

                # Reduce sleep time after a successful request, but not below the minimum
                sleep_time = max(min_sleep_time, sleep_time - sleep_adjustment_factor)

                # Break if we have reached the starting timestamp
                if a <= start_timestamp:
                    logging.info(f"Reached the start date for {inst_id} {bar}.")
                    return
                time.sleep(sleep_time)

            except Exception as e:
                logging.error(f"Error occurred: {e}")
                # Increase sleep time after an error, but not above the maximum
                sleep_time = min(max_sleep_time, sleep_time + sleep_adjustment_factor)
                time.sleep(sleep_time)



    @staticmethod
    def today(tushare_format=False):
        if tushare_format:
            return datetime.today().strftime("%Y%m%d")
        return datetime.today().strftime("%Y-%m-%d")

    def update_data(self):
        pair_list = self.get_all_coin_pairs()
        # pair_list = ["BTC-USDT-SWAP"]
        bar_sizes = ['1m', '3m', '5m', '15m', '30m', '1H', '4H', '1D', '1W']
        # bar_sizes = ['1m']
        # self.fetch_kline_data(inst_id=pair_list[0], bar=bar_sizes[0])
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for inst_id in pair_list:
                for bar in bar_sizes:
                    futures.append(executor.submit(self.fetch_kline_data, inst_id, bar))
            concurrent.futures.wait(futures)

if __name__ == "__main__":
    updater = CryptoDataUpdater()
    updater.update_data()
