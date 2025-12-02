import os
import sqlite3
from typing import Iterable, Dict

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'stocks.db')


class StockDatabase:
    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS daily_price (
                code TEXT,
                date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                PRIMARY KEY (code, date)
            )
            '''
        )
        self.conn.commit()

    def upsert_daily_prices(self, code: str, rows: Iterable[Dict]):
        cur = self.conn.cursor()
        cur.executemany(
            '''
            INSERT OR REPLACE INTO daily_price (code, date, open, high, low, close, volume)
            VALUES (:code, :date, :open, :high, :low, :close, :volume)
            ''',
            [
                {
                    'code': code,
                    'date': r['date'],
                    'open': float(r.get('open', 0) or 0),
                    'high': float(r.get('high', 0) or 0),
                    'low': float(r.get('low', 0) or 0),
                    'close': float(r.get('close', 0) or 0),
                    'volume': int(r.get('volume', 0) or 0),
                }
                for r in rows
            ]
        )
        self.conn.commit()

    def get_daily_prices(self, code: str, limit: int = 500):
        cur = self.conn.cursor()
        cur.execute(
            '''
            SELECT date, open, high, low, close, volume
            FROM daily_price WHERE code = ?
            ORDER BY date DESC
            LIMIT ?
            ''',
            (code, limit)
        )
        rows = cur.fetchall()
        return [
            {
                'date': r[0],
                'open': float(r[1] or 0),
                'high': float(r[2] or 0),
                'low': float(r[3] or 0),
                'close': float(r[4] or 0),
                'volume': int(r[5] or 0),
            }
            for r in rows
        ]

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass