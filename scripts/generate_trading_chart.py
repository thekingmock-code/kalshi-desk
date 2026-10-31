"""Generate mock arbitrage chart HTML (composite, strike, TWAP boundary, signals)."""
from __future__ import annotations

import json
import os

import numpy as np

# Create a local web folder if it doesn't exist
os.makedirs("generated", exist_ok=True)

LIGHTWEIGHT_CHARTS_CDN = (
    "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
)


def generate_mock_arbitrage_data():
    """
    Generates historical data simulating a 60-second settlement run
    to demonstrate the composite index, strike line, and signals.
    """
    np.random.seed(42)
    timesteps = 120  # 120 seconds of data
    base_time = 1793782400  # Example unix timestamp

    strike_price = 65000.0

    coinbase = 65010 + np.cumsum(np.random.normal(0.2, 3, timesteps))
    kraken = coinbase + np.random.normal(0, 1.5, timesteps)
    bitstamp = coinbase + np.random.normal(0, 2, timesteps)

    composite_spot = (coinbase + kraken + bitstamp) / 3

    data_list = []
    price_window_60s: list[float] = []

    for t in range(timesteps):
        current_time = base_time + t
        current_spot = float(composite_spot[t])
        price_window_60s.append(current_spot)

        if len(price_window_60s) > 60:
            price_window_60s.pop(0)

        ticks_passed = len(price_window_60s)
        ticks_remaining = max(1, 60 - ticks_passed)
        sum_passed = sum(price_window_60s)

        target_total_sum = strike_price * 60
        required_spot_avg = (target_total_sum - sum_passed) / ticks_remaining

        if t > 5:
            recent_prices = composite_spot[max(0, t - 15) : t + 1]
            returns = np.diff(recent_prices) / recent_prices[:-1]
            current_vol = float(np.std(returns)) if len(returns) > 0 else 0.0001
        else:
            current_vol = 0.0002

        time_left = ticks_remaining
        denom = current_vol * current_spot * np.sqrt(time_left)
        sigma_distance = abs(current_spot - required_spot_avg) / denom if denom > 0 else 0.0

        signal = "none"
        if 0.5 <= sigma_distance <= 1.5:
            if t > 2 and composite_spot[t] > composite_spot[t - 2] and current_spot < strike_price:
                signal = "buy"
            elif t > 2 and composite_spot[t] < composite_spot[t - 2] and current_spot > strike_price:
                signal = "sell"

        data_list.append(
            {
                "time": current_time,
                "open": float(current_spot - np.random.uniform(1, 3)),
                "high": float(current_spot + np.random.uniform(2, 5)),
                "low": float(current_spot - np.random.uniform(2, 5)),
                "close": current_spot,
                "strike": float(strike_price),
                "required_spot": float(required_spot_avg if t < 60 else strike_price),
                "signal": signal,
            }
        )

    return data_list


def build_chart_html(data_json: str) -> None:
    """Interactive HTML using TradingView Lightweight Charts (v4 standalone API)."""
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Arbitrage Engine Trading Terminal</title>
    <script src="{LIGHTWEIGHT_CHARTS_CDN}"></script>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background-color: #0f1115;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #e1e4ea;
        }}
        #container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .title-badge {{
            background: linear-gradient(135deg, #2962ff, #143ca3);
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        #chart {{
            width: 100%;
            height: 600px;
            border: 1px solid #2a2e39;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }}
    </style>
</head>
<body>
    <div id="container">
        <div class="header">
            <div>
                <h2 style="margin:0; font-size:22px;">Arbitrage Execution Workspace</h2>
                <p style="margin:5px 0 0 0; font-size:13px; color:#848e9c;">Composite Index vs Settlement Lock Boundary</p>
            </div>
            <div class="title-badge">Rule-Engine Native</div>
        </div>
        <div id="chart"></div>
    </div>

    <script>
        const rawData = {data_json};

        const chartElement = document.getElementById('chart');
        const chart = LightweightCharts.createChart(chartElement, {{
            width: chartElement.clientWidth,
            height: 600,
            layout: {{
                background: {{ type: 'solid', color: '#131722' }},
                textColor: '#d1d4dc',
            }},
            grid: {{
                vertLines: {{ color: 'rgba(42, 46, 57, 0.5)' }},
                horzLines: {{ color: 'rgba(42, 46, 57, 0.5)' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
            }},
            rightPriceScale: {{
                borderColor: 'rgba(197, 203, 206, 0.8)',
            }},
            timeScale: {{
                borderColor: 'rgba(197, 203, 206, 0.8)',
                timeVisible: true,
                secondsVisible: true,
            }},
        }});

        const candlestickSeries = chart.addCandlestickSeries({{
            upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
            wickUpColor: '#26a69a', wickDownColor: '#ef5350'
        }});

        const candleData = rawData.map(d => ({{
            time: d.time, open: d.open, high: d.high, low: d.low, close: d.close
        }}));
        candlestickSeries.setData(candleData);

        const strikeSeries = chart.addLineSeries({{
            color: '#ff9800',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            title: 'Strike Level'
        }});
        strikeSeries.setData(rawData.map(d => ({{ time: d.time, value: d.strike }})));

        const requiredSpotSeries = chart.addLineSeries({{
            color: '#2962ff',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            title: 'Required TWAP Spot'
        }});
        requiredSpotSeries.setData(rawData.map(d => ({{ time: d.time, value: d.required_spot }})));

        const markers = [];
        rawData.forEach(d => {{
            if (d.signal === 'buy') {{
                markers.push({{
                    time: d.time,
                    position: 'belowBar',
                    color: '#26a69a',
                    shape: 'arrowUp',
                    text: 'BUY EDGE'
                }});
            }} else if (d.signal === 'sell') {{
                markers.push({{
                    time: d.time,
                    position: 'aboveBar',
                    color: '#ef5350',
                    shape: 'arrowDown',
                    text: 'SELL EDGE'
                }});
            }}
        }});
        candlestickSeries.setMarkers(markers);

        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: chartElement.clientWidth }});
        }});
    </script>
</body>
</html>
"""

    with open("generated/trading_chart.html", "w", encoding="utf-8") as f:
        f.write(html_template)


if __name__ == "__main__":
    print("Compiling data models and calculating execution thresholds...")
    market_data = generate_mock_arbitrage_data()
    build_chart_html(json.dumps(market_data))
    print("Success! Trading terminal generated inside 'generated/trading_chart.html'")
